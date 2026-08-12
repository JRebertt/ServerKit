"""Per-domain bandwidth accounting from nginx access logs.

A daily job (kind ``bandwidth.aggregate``) streams each site's nginx access
log — the ``/var/log/nginx/{name}.access.log`` files the vhost templates
write (see ``NginxService.site_access_log_path``) — plus the server-wide
``access.log`` catch-all, sums ``$body_bytes_sent`` and request counts per
domain for one calendar day, and upserts :class:`SiteBandwidthDaily` rows.

Log format handling:
  * standard "combined" lines are attributed to the owning app's primary
    domain (per-site logs don't record ``$host``);
  * vhost-prefixed lines (``$host[:$port] `` before the combined fields, as
    produced by ``vcombined``-style formats) are split by that host — the
    only way lines in the shared default ``access.log`` can be attributed.

Re-running a day replaces that day's rows (incremental-safe). On dev boxes
with no nginx logs (e.g. Windows) the job is a clean no-op.
"""
import logging
import os
import re
from datetime import date, datetime, timedelta

from app import db

logger = logging.getLogger(__name__)

BANDWIDTH_JOB_KIND = 'bandwidth.aggregate'
BANDWIDTH_SCHEDULE_NAME = 'bandwidth-aggregate'

# Keep a little over a year of daily rows.
RETENTION_DAYS = 400

# nginx "combined" format:
#   $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent ...
_COMBINED_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\d+|-)'
)
# Same fields with a leading $host[:$port] (Apache "vcombined"-style, also a
# common custom nginx log_format for shared logs).
_VHOST_RE = re.compile(
    r'^(?P<host>[^\s:]+)(?::\d+)? (?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\d+|-)'
)

# nginx writes $time_local with English month abbreviations regardless of
# locale; build the day prefix by hand so we never depend on the C runtime's.
_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def _day_prefix(day):
    """``date(2026, 7, 3)`` → ``'03/Jul/2026'`` (start of ``$time_local``)."""
    return f'{day.day:02d}/{_MONTHS[day.month - 1]}/{day.year}'


def _normalize_host(host):
    """Lowercase a logged $host and strip a trailing dot. Returns None for
    values that clearly aren't a domain ('-', '_', empty)."""
    host = (host or '').strip().rstrip('.').lower()
    if not host or host in ('-', '_'):
        return None
    return host


class BandwidthService:

    # ------------------------------------------------------------------ #
    # Log parsing
    # ------------------------------------------------------------------ #

    @classmethod
    def parse_log_file(cls, path, day):
        """Stream one access log, keeping only ``day``'s lines.

        Returns ``(per_host, plain, skipped)``:
          * ``per_host`` — {host: [bytes, requests]} from vhost-prefixed lines
          * ``plain``    — [bytes, requests] from standard combined lines
          * ``skipped``  — count of unparsable lines
        Missing/unreadable files count as empty (best-effort by design).
        """
        per_host = {}
        plain = [0, 0]
        skipped = 0
        prefix = _day_prefix(day)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    match = _COMBINED_RE.match(line)
                    host = None
                    if not match:
                        match = _VHOST_RE.match(line)
                        if match:
                            host = _normalize_host(match.group('host'))
                    if not match:
                        skipped += 1
                        continue
                    if not match.group('time').startswith(prefix):
                        continue
                    raw = match.group('bytes')
                    nbytes = int(raw) if raw.isdigit() else 0
                    if host:
                        bucket = per_host.setdefault(host, [0, 0])
                        bucket[0] += nbytes
                        bucket[1] += 1
                    else:
                        plain[0] += nbytes
                        plain[1] += 1
        except OSError:
            pass  # no log on this box (dev) or unreadable — clean zero result
        return per_host, plain, skipped

    # ------------------------------------------------------------------ #
    # Aggregation job
    # ------------------------------------------------------------------ #

    @classmethod
    def aggregate(cls, day=None, log_dir=None):
        """Aggregate one day's nginx access logs into SiteBandwidthDaily.

        ``day`` defaults to yesterday (accepts a ``date`` or 'YYYY-MM-DD').
        ``log_dir`` overrides the nginx log directory (tests). Re-running a
        day replaces that day's rows. Also prunes rows older than
        ``RETENTION_DAYS``.
        """
        from app.models.application import Application
        from app.models.domain import Domain
        from app.models.site_bandwidth import SiteBandwidthDaily
        from app.services.nginx_service import NginxService

        if day is None:
            day = date.today() - timedelta(days=1)
        elif isinstance(day, str):
            day = datetime.strptime(day, '%Y-%m-%d').date()

        if log_dir is None:
            log_dir = NginxService.LOG_DIR

        # domain (lowercased) -> app_id, for attributing vhost-split lines.
        domain_app = {
            d.name.lower(): d.application_id
            for d in Domain.query_active().all() if d.name
        }

        # domain -> {'app_id': ..., 'bytes': ..., 'requests': ...}
        totals = {}
        skipped = 0
        files_read = 0

        def _add(domain, app_id, nbytes, nreqs):
            if nreqs == 0 and nbytes == 0:
                return
            entry = totals.setdefault(
                domain, {'app_id': app_id, 'bytes': 0, 'requests': 0})
            if entry['app_id'] is None:
                entry['app_id'] = app_id
            entry['bytes'] += nbytes
            entry['requests'] += nreqs

        def _parse_with_rotation(base_path):
            """Parse a log plus its ``.1`` rotation (day spillover)."""
            nonlocal skipped, files_read
            merged_hosts = {}
            merged_plain = [0, 0]
            for path in (base_path, base_path + '.1'):
                if not os.path.isfile(path):
                    continue
                per_host, plain, bad = cls.parse_log_file(path, day)
                files_read += 1
                skipped += bad
                merged_plain[0] += plain[0]
                merged_plain[1] += plain[1]
                for host, (b, r) in per_host.items():
                    bucket = merged_hosts.setdefault(host, [0, 0])
                    bucket[0] += b
                    bucket[1] += r
            return merged_hosts, merged_plain

        # Per-site logs: /var/log/nginx/{app.name}.access.log
        for app_row in Application.query.all():
            base = os.path.join(log_dir, f'{app_row.name}.access.log')
            per_host, plain = _parse_with_rotation(base)
            primary = None
            for d in (app_row.domains or []):
                if d.is_primary:
                    primary = d.name
                    break
            if primary is None and app_row.domains:
                primary = app_row.domains[0].name
            default_domain = (primary or app_row.name or '').lower()
            if default_domain:
                _add(default_domain, app_row.id, plain[0], plain[1])
            for host, (b, r) in per_host.items():
                _add(host, domain_app.get(host, app_row.id), b, r)

        # Server-wide catch-all: only vhost-prefixed lines are attributable.
        default_hosts, _default_plain = _parse_with_rotation(
            os.path.join(log_dir, 'access.log'))
        for host, (b, r) in default_hosts.items():
            _add(host, domain_app.get(host), b, r)

        # Replace the day's rows (idempotent re-runs).
        SiteBandwidthDaily.query.filter_by(day=day).delete(
            synchronize_session=False)
        for domain, entry in totals.items():
            db.session.add(SiteBandwidthDaily(
                app_id=entry['app_id'],
                domain=domain,
                day=day,
                bytes_sent=entry['bytes'],
                requests=entry['requests'],
            ))

        # Retention prune.
        cutoff = date.today() - timedelta(days=RETENTION_DAYS)
        pruned = SiteBandwidthDaily.query.filter(
            SiteBandwidthDaily.day < cutoff).delete(synchronize_session=False)
        db.session.commit()

        return {
            'day': day.isoformat(),
            'domains': len(totals),
            'bytes_sent': sum(e['bytes'] for e in totals.values()),
            'requests': sum(e['requests'] for e in totals.values()),
            'files_read': files_read,
            'skipped_lines': skipped,
            'pruned': int(pruned or 0),
        }

    # ------------------------------------------------------------------ #
    # Read side
    # ------------------------------------------------------------------ #

    @classmethod
    def series(cls, app_id=None, domain=None, days=30):
        """Daily series for one app (all its domains summed) or one domain,
        newest last, zero-filled: [{day, bytes_sent, requests}, ...]."""
        from app.models.site_bandwidth import SiteBandwidthDaily

        days = max(1, min(int(days), RETENTION_DAYS))
        end = date.today()
        start = end - timedelta(days=days - 1)

        query = SiteBandwidthDaily.query.filter(
            SiteBandwidthDaily.day >= start, SiteBandwidthDaily.day <= end)
        if app_id is not None:
            query = query.filter(SiteBandwidthDaily.app_id == int(app_id))
        if domain is not None:
            query = query.filter(SiteBandwidthDaily.domain == domain.lower())

        by_day = {}
        for row in query.all():
            bucket = by_day.setdefault(row.day, [0, 0])
            bucket[0] += int(row.bytes_sent or 0)
            bucket[1] += int(row.requests or 0)

        out = []
        for offset in range(days):
            d = start + timedelta(days=offset)
            b, r = by_day.get(d, (0, 0))
            out.append({'day': d.isoformat(), 'bytes_sent': b, 'requests': r})
        return out

    @classmethod
    def monthly_total(cls, app_id):
        """Total bytes_sent for the app in the current calendar month."""
        from app.models.site_bandwidth import SiteBandwidthDaily

        today = date.today()
        first = today.replace(day=1)
        total = (db.session.query(
                    db.func.coalesce(db.func.sum(SiteBandwidthDaily.bytes_sent), 0))
                 .filter(SiteBandwidthDaily.app_id == int(app_id),
                         SiteBandwidthDaily.day >= first,
                         SiteBandwidthDaily.day <= today)
                 .scalar())
        return int(total or 0)

    @classmethod
    def overview(cls, days=30):
        """One-call payload for the Services list:
        {app_id: {'month_bytes': int, 'series30': [bytes...]}} — only apps
        that have any recorded traffic."""
        from app.models.site_bandwidth import SiteBandwidthDaily

        days = max(1, min(int(days), RETENTION_DAYS))
        end = date.today()
        start = end - timedelta(days=days - 1)
        month_first = end.replace(day=1)
        window_start = min(start, month_first)

        rows = (SiteBandwidthDaily.query
                .filter(SiteBandwidthDaily.day >= window_start,
                        SiteBandwidthDaily.day <= end,
                        SiteBandwidthDaily.app_id.isnot(None))
                .all())

        per_app = {}
        for row in rows:
            entry = per_app.setdefault(row.app_id, {'month': 0, 'by_day': {}})
            b = int(row.bytes_sent or 0)
            if row.day >= month_first:
                entry['month'] += b
            if row.day >= start:
                entry['by_day'][row.day] = entry['by_day'].get(row.day, 0) + b

        out = {}
        for app_id, entry in per_app.items():
            series = [
                entry['by_day'].get(start + timedelta(days=i), 0)
                for i in range(days)
            ]
            out[app_id] = {'month_bytes': entry['month'], 'series30': series}
        return out

    # ------------------------------------------------------------------ #
    # Job plumbing
    # ------------------------------------------------------------------ #

    @classmethod
    def run_aggregate_job(cls, job):
        """Job handler for ``bandwidth.aggregate`` (payload may pin a day)."""
        payload = job.get_payload() if job is not None else {}
        return cls.aggregate(day=payload.get('day'))

    @classmethod
    def register_jobs(cls):
        """Register the aggregation handler. Called once at app startup
        (see app/__init__.py); the daily schedule row is seeded with the
        other builtins in seed_builtin_schedules()."""
        from app.jobs import registry
        registry.register(BANDWIDTH_JOB_KIND, cls.run_aggregate_job,
                          replace=True)
