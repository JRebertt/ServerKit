"""Monitors — the panel's synthetic-check engine.

A monitor is a ``StatusComponent`` row: one probe (http / keyword / tcp / dns /
smtp / ping) against a URL, host or managed WordPress site, on an interval, with
its results kept as ``HealthCheck`` rows and its outages surfaced as
``StatusIncident``.

This lives in core, not in the serverkit-status extension, because monitoring a
site should not depend on publishing a status page. The extension now delegates
its check-running here and keeps only page publishing and branding.

Everything funnels through :meth:`_record` so that a network probe and a managed
site's health verdict produce identical bookkeeping: a sample, a live status, a
recomputed uptime, and the incident open/resolve edges.
"""
import logging
import os
import socket
import ssl
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from app import db
from app.models.status_page import (
    StatusComponent, HealthCheck, StatusIncident, StatusIncidentUpdate,
)

logger = logging.getLogger(__name__)

# A monitor's TLS certificate barely moves, and reading it costs a second
# connection. Refresh at most this often rather than on every probe.
CERT_REFRESH_SECONDS = 6 * 3600

# Certificate timestamps come back from OpenSSL in this format.
_CERT_TIME_FORMAT = '%b %d %H:%M:%S %Y %Z'

UPTIME_WINDOWS = {'uptime_24h': 24, 'uptime_7d': 24 * 7,
                  'uptime_30d': 24 * 30, 'uptime_90d': 24 * 90}


def _parse_expected_status(spec):
    """Parse an expected-status spec into a list of (low, high) ranges.

    Accepts "200-299", "200", "200,204,301-302" and whitespace around any part.
    Returns None for an unparseable or empty spec so the caller can fall back to
    the default "anything below 400 is fine".
    """
    if not spec:
        return None
    ranges = []
    for part in str(spec).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            if '-' in part:
                low, high = part.split('-', 1)
                ranges.append((int(low), int(high)))
            else:
                code = int(part)
                ranges.append((code, code))
        except ValueError:
            continue
    return ranges or None


def _status_matches(code, spec):
    ranges = _parse_expected_status(spec)
    if ranges is None:
        return code < 400
    return any(low <= code <= high for low, high in ranges)


class MonitorService:
    """Create, run and report on monitors."""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    WRITABLE_FIELDS = (
        'name', 'description', 'group', 'sort_order', 'page_id',
        'check_type', 'check_target', 'check_interval', 'check_timeout',
        'check_method', 'expected_status', 'keyword', 'follow_redirects',
        'verify_tls', 'retries', 'wordpress_site_id', 'status',
    )

    @staticmethod
    def list_monitors(status=None, check_type=None, q=None, page_id=None,
                      include_paused=True):
        query = StatusComponent.query
        if status == 'paused':
            query = query.filter(StatusComponent.is_paused.is_(True))
        elif status:
            query = query.filter(StatusComponent.status == status,
                                 StatusComponent.is_paused.is_(False))
        if not include_paused:
            query = query.filter(StatusComponent.is_paused.is_(False))
        if check_type:
            query = query.filter(StatusComponent.check_type == check_type)
        if page_id is not None:
            query = query.filter(StatusComponent.page_id == page_id)
        if q:
            like = f'%{q}%'
            query = query.filter(db.or_(StatusComponent.name.ilike(like),
                                        StatusComponent.check_target.ilike(like)))
        return query.order_by(StatusComponent.sort_order, StatusComponent.name).all()

    @staticmethod
    def get(monitor_id):
        return StatusComponent.query.get(monitor_id)

    @staticmethod
    def _validate_site_binding(site_id):
        """A monitor may bind to a WordPress site only when that site exists.

        With the WordPress extension absent (or the site removed) the bind
        fails loudly here instead of creating an orphan monitor that never
        gets health-synced (plan 52 task 17). The model itself stays core
        (D1), so the check is a plain row lookup.
        """
        if site_id is None:
            return
        from app.models.wordpress_site import WordPressSite
        if not WordPressSite.query.get(site_id):
            raise ValueError(
                'wordpress_site_id does not match an existing WordPress site '
                '(is the WordPress extension installed?)')

    @staticmethod
    def create(data):
        if not data.get('name'):
            raise ValueError('Monitor name is required')
        check_type = data.get('check_type', 'http')
        if check_type not in StatusComponent.CHECK_TYPES:
            raise ValueError(f'Unknown check type: {check_type}')
        if check_type == 'keyword' and not data.get('keyword'):
            raise ValueError('A keyword check needs a keyword to look for')
        # A monitor needs something to probe unless it is driven by a managed
        # site's health verdict instead of the network.
        if not data.get('check_target') and not data.get('wordpress_site_id'):
            raise ValueError('Monitor needs a check target or a bound site')
        MonitorService._validate_site_binding(data.get('wordpress_site_id'))

        monitor = StatusComponent(
            page_id=data.get('page_id'),
            name=data['name'],
            description=data.get('description', ''),
            group=data.get('group', 'Services'),
            sort_order=data.get('sort_order', 0),
            check_type=check_type,
            check_target=data.get('check_target', ''),
            check_interval=data.get('check_interval', 60),
            check_timeout=data.get('check_timeout', 10),
            check_method=data.get('check_method', 'GET'),
            expected_status=data.get('expected_status', '200-299'),
            keyword=data.get('keyword'),
            follow_redirects=data.get('follow_redirects', True),
            verify_tls=data.get('verify_tls', True),
            retries=data.get('retries', 2),
            wordpress_site_id=data.get('wordpress_site_id'),
        )
        db.session.add(monitor)
        db.session.commit()
        return monitor

    @staticmethod
    def update(monitor_id, data):
        monitor = StatusComponent.query.get(monitor_id)
        if not monitor:
            return None
        if 'check_type' in data and data['check_type'] not in StatusComponent.CHECK_TYPES:
            raise ValueError(f"Unknown check type: {data['check_type']}")
        if data.get('wordpress_site_id') is not None:
            MonitorService._validate_site_binding(data['wordpress_site_id'])
        for field in MonitorService.WRITABLE_FIELDS:
            if field in data:
                setattr(monitor, field, data[field])
        db.session.commit()
        return monitor

    @staticmethod
    def delete(monitor_id):
        monitor = StatusComponent.query.get(monitor_id)
        if not monitor:
            return False
        # Resolve + unlink any incidents referencing this monitor first, so we
        # never dangle the component_id FK (enforced on PostgreSQL) or leave a
        # stale active incident behind after the monitor is gone.
        for inc in StatusIncident.query.filter_by(component_id=monitor_id).all():
            if inc.status != 'resolved':
                inc.status = 'resolved'
                inc.resolved_at = datetime.utcnow()
            inc.component_id = None
        db.session.delete(monitor)
        db.session.commit()
        return True

    @staticmethod
    def set_paused(monitor_id, paused):
        monitor = StatusComponent.query.get(monitor_id)
        if not monitor:
            return None
        monitor.is_paused = bool(paused)
        if not paused:
            # Resuming clears the failure streak so a monitor that was paused
            # mid-outage does not immediately re-open an incident.
            monitor.consecutive_failures = 0
        db.session.commit()
        return monitor

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    @staticmethod
    def due_monitors(now=None):
        """Monitors the scheduler should poll right now: not paused, not driven
        by a managed site's health sweep, and either never checked or past their
        interval."""
        now = now or datetime.utcnow()
        candidates = StatusComponent.query.filter(
            StatusComponent.is_paused.is_(False),
            StatusComponent.wordpress_site_id.is_(None),
        ).all()
        due = []
        for monitor in candidates:
            if not monitor.check_target:
                continue
            if monitor.last_check_at is None:
                due.append(monitor)
                continue
            interval = monitor.check_interval or 60
            if monitor.last_check_at + timedelta(seconds=interval) <= now:
                due.append(monitor)
        return due

    # ------------------------------------------------------------------
    # Running checks
    # ------------------------------------------------------------------

    @staticmethod
    def run_check(monitor_id):
        """Probe a monitor and record the result. Returns the HealthCheck row."""
        monitor = StatusComponent.query.get(monitor_id)
        if not monitor:
            return None
        result = MonitorService._perform_check(monitor)
        return MonitorService._record(monitor, result)

    @staticmethod
    def _record(monitor, result):
        """Single bookkeeping path for every kind of check result.

        Records the sample, moves the live status, recomputes uptime, and opens
        or resolves the monitor's incident. The old code only did the last two
        for managed-site health syncs, so network-probed monitors never produced
        an incident at all.
        """
        check_status = result['status']
        prev_status = monitor.status

        hc = HealthCheck(
            component_id=monitor.id,
            status=check_status,
            response_time=result.get('response_time'),
            status_code=result.get('status_code'),
            error=result.get('error'),
        )
        db.session.add(hc)

        monitor.last_check_at = datetime.utcnow()
        if result.get('response_time') is not None:
            monitor.last_response_time = result.get('response_time')
        if result.get('cert_checked_at'):
            monitor.cert_checked_at = result['cert_checked_at']
        if result.get('cert_issuer'):
            monitor.cert_issuer = result['cert_issuer']
        if 'cert_expires_at' in result:
            # A cert probe that ran hands back either a fresh expiry or None
            # (failed/unparseable read) — None clears the stale value so the
            # UI falls back to n/a instead of a weeks-old green "valid" chip.
            monitor.cert_expires_at = result['cert_expires_at']

        if check_status == 'up':
            monitor.consecutive_failures = 0
            monitor.status = StatusComponent.STATUS_OPERATIONAL
        elif check_status == 'degraded':
            monitor.status = StatusComponent.STATUS_DEGRADED
        else:
            monitor.consecutive_failures = (monitor.consecutive_failures or 0) + 1
            # Hold at degraded until the failure streak clears `retries`, so a
            # single blip does not page anyone.
            if monitor.consecutive_failures > (monitor.retries or 0):
                monitor.status = StatusComponent.STATUS_MAJOR
            else:
                monitor.status = StatusComponent.STATUS_DEGRADED

        db.session.commit()

        MonitorService.recompute_uptime(monitor)

        # Open an incident when ENTERING a major outage; resolve it when LEAVING
        # major (to operational OR degraded). Resolving on the leaving-edge — not
        # only on a clean major->operational hop — ensures a recovery that passes
        # through an intermediate degraded poll (a common path) never leaves the
        # incident stuck open. Degraded itself never opens a full incident.
        if monitor.status == StatusComponent.STATUS_MAJOR and prev_status != StatusComponent.STATUS_MAJOR:
            MonitorService._open_incident_for_component(monitor, result.get('error'))
        elif monitor.status != StatusComponent.STATUS_MAJOR and prev_status == StatusComponent.STATUS_MAJOR:
            MonitorService._resolve_incident_for_component(monitor)
        return hc

    @staticmethod
    def _perform_check(monitor):
        """Execute one probe. Never raises — a failure is a 'down' result."""
        start = time.time()
        result = {'status': 'down', 'response_time': None, 'error': None}
        elapsed = lambda: int((time.time() - start) * 1000)  # noqa: E731

        try:
            check_type = monitor.check_type or 'http'

            if check_type in ('http', 'keyword'):
                import requests
                method = (monitor.check_method or 'GET').upper()
                resp = requests.request(
                    method,
                    monitor.check_target,
                    timeout=monitor.check_timeout,
                    verify=bool(monitor.verify_tls),
                    allow_redirects=bool(monitor.follow_redirects),
                )
                result['response_time'] = elapsed()
                result['status_code'] = resp.status_code

                if not _status_matches(resp.status_code, monitor.expected_status):
                    result['error'] = (f'HTTP {resp.status_code} is outside the '
                                       f'expected {monitor.expected_status or "2xx/3xx"}')
                    # A 4xx is the app answering badly; a 5xx (or anything else
                    # unexpected) is treated as an outage.
                    result['status'] = 'degraded' if 400 <= resp.status_code < 500 else 'down'
                elif check_type == 'keyword':
                    # A 200 carrying the wrong page is an outage, not a success —
                    # that is the entire point of a keyword check.
                    if monitor.keyword and monitor.keyword in (resp.text or ''):
                        result['status'] = 'up'
                    else:
                        result['status'] = 'down'
                        result['error'] = f'Keyword not found in response: {monitor.keyword!r}'
                else:
                    result['status'] = 'up'

                MonitorService._maybe_attach_certificate(monitor, result)

            elif check_type == 'tcp':
                host, port = MonitorService._split_host_port(monitor.check_target)
                sock = socket.create_connection((host, port), timeout=monitor.check_timeout)
                result['response_time'] = elapsed()
                result['status'] = 'up'
                sock.close()

            elif check_type == 'ping':
                result.update(MonitorService._ping(monitor))
                result['response_time'] = elapsed()

            elif check_type == 'dns':
                socket.getaddrinfo(monitor.check_target, None)
                result['response_time'] = elapsed()
                result['status'] = 'up'

            elif check_type == 'smtp':
                import smtplib
                host, port = MonitorService._split_host_port(monitor.check_target, default_port=25)
                server = smtplib.SMTP(host, port, timeout=monitor.check_timeout)
                try:
                    code, _msg = server.noop()
                finally:
                    try:
                        server.quit()
                    except Exception:
                        pass
                result['response_time'] = elapsed()
                result['status_code'] = code
                result['status'] = 'up' if code == 250 else 'degraded'

            else:
                result['error'] = f'Unknown check type: {check_type}'

        except Exception as e:
            result['response_time'] = elapsed()
            result['error'] = str(e)
            result['status'] = 'down'

        return result

    @staticmethod
    def _split_host_port(target, default_port=None):
        """Split 'host:port' (or a bare host when *default_port* is given)."""
        target = (target or '').strip()
        if ':' in target:
            host, port = target.rsplit(':', 1)
            return host, int(port)
        if default_port is not None:
            return target, default_port
        raise ValueError(f'Target must be host:port, got {target!r}')

    @staticmethod
    def _ping(monitor):
        """One ICMP echo. The previous implementation ignored the return code
        entirely, so a ping check could only ever report 'up'."""
        from app.utils.system import run_unprivileged
        timeout = monitor.check_timeout or 10
        if os.name == 'nt':
            cmd = ['ping', '-n', '1', '-w', str(int(timeout) * 1000), monitor.check_target]
        else:
            cmd = ['ping', '-c', '1', '-W', str(int(timeout)), monitor.check_target]
        res = run_unprivileged(cmd, timeout=timeout + 5)
        if res.get('returncode') == 0:
            return {'status': 'up'}
        return {
            'status': 'down',
            'error': (res.get('stderr') or res.get('stdout') or 'Ping failed').strip()[:500],
        }

    # ------------------------------------------------------------------
    # TLS certificate
    # ------------------------------------------------------------------

    @staticmethod
    def _maybe_attach_certificate(monitor, result):
        """Read the peer certificate for https monitors, at most every
        CERT_REFRESH_SECONDS — it costs a second connection and barely moves.

        Throttled on ``cert_checked_at``, not ``last_check_at``: an active
        monitor is checked every 30s, so gating on the probe clock would read the
        certificate once and then never refresh it.
        """
        target = monitor.check_target or ''
        if not target.startswith('https://'):
            return
        if monitor.cert_checked_at:
            age = (datetime.utcnow() - monitor.cert_checked_at).total_seconds()
            if age < CERT_REFRESH_SECONDS:
                return
        # Stamped even when the read fails, so an unreachable TLS endpoint is
        # retried on the same cadence instead of on every single probe.
        result['cert_checked_at'] = datetime.utcnow()
        try:
            cert = MonitorService._probe_certificate(
                target, monitor.check_timeout or 10, bool(monitor.verify_tls))
        except Exception as e:
            logger.debug('Certificate probe failed for monitor %s: %s', monitor.id, e)
            cert = None
        if cert:
            result.update(cert)
        if not (cert or {}).get('cert_expires_at'):
            # The probe ran but produced no expiry (failed read, no peer cert,
            # unparseable notAfter). Clear the stale expiry downstream so the
            # UI shows n/a until a successful probe repopulates it.
            result['cert_expires_at'] = None

    @staticmethod
    def _probe_certificate(url, timeout, verify=True):
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return None
        port = parsed.port or 443

        context = ssl.create_default_context()
        if not verify:
            # Still read the certificate even when the monitor does not require
            # it to validate — an expiring self-signed cert is worth surfacing.
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        if not cert:
            return None

        out = {}
        not_after = cert.get('notAfter')
        if not_after:
            try:
                out['cert_expires_at'] = datetime.strptime(not_after, _CERT_TIME_FORMAT)
            except ValueError:
                pass
        issuer = cert.get('issuer') or ()
        for rdn in issuer:
            for key, value in rdn:
                if key == 'organizationName':
                    out['cert_issuer'] = value
        return out or None

    # ------------------------------------------------------------------
    # History and uptime
    # ------------------------------------------------------------------

    @staticmethod
    def get_check_history(monitor_id, hours=24, limit=None):
        since = datetime.utcnow() - timedelta(hours=hours)
        query = HealthCheck.query.filter(
            HealthCheck.component_id == monitor_id,
            HealthCheck.checked_at >= since,
        ).order_by(HealthCheck.checked_at.desc())
        if limit:
            query = query.limit(limit)
        return query.all()

    @staticmethod
    def recent_response_times(monitor_ids, per_monitor=24, hours=6):
        """Last N response times per monitor, oldest first — the list sparkline.

        One query for the whole page rather than one per row, bounded by a time
        window so a busy monitor's history can't crowd out a quiet one's (which
        a single global LIMIT would do).
        """
        if not monitor_ids:
            return {}
        since = datetime.utcnow() - timedelta(hours=hours)
        rows = HealthCheck.query.filter(
            HealthCheck.component_id.in_(list(monitor_ids)),
            HealthCheck.response_time.isnot(None),
            HealthCheck.checked_at >= since,
        ).order_by(HealthCheck.checked_at.desc()).all()

        out = {}
        for row in rows:
            bucket = out.setdefault(row.component_id, [])
            if len(bucket) < per_monitor:
                bucket.append(row.response_time)
        return {mid: list(reversed(values)) for mid, values in out.items()}

    @staticmethod
    def recompute_uptime(monitor):
        """Recompute uptime_24h/7d/30d/90d from HealthCheck rows (fraction of
        recorded checks with status 'up'). Only fully-healthy checks count as up
        — 'degraded' periods reduce the percentage, matching the status-page
        convention where degraded is not "operational". Leaves a window's
        existing value untouched when it has no samples yet."""
        now = datetime.utcnow()
        for field, hours in UPTIME_WINDOWS.items():
            since = now - timedelta(hours=hours)
            base = HealthCheck.query.filter(
                HealthCheck.component_id == monitor.id,
                HealthCheck.checked_at >= since,
            )
            total = base.count()
            if total:
                up = base.filter(HealthCheck.status == 'up').count()
                setattr(monitor, field, round(up / total * 100, 2))
        db.session.commit()

    @staticmethod
    def uptime_days(monitor_id, days=90):
        """Per-day uptime buckets for the 90-day bar strip.

        A day with no samples reports state 'none' rather than 100% so the strip
        can render "we weren't watching" differently from "it was fine".
        """
        now = datetime.utcnow()
        start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = HealthCheck.query.filter(
            HealthCheck.component_id == monitor_id,
            HealthCheck.checked_at >= start,
        ).all()

        buckets = {}
        for row in rows:
            key = row.checked_at.date().isoformat()
            bucket = buckets.setdefault(key, {'total': 0, 'up': 0, 'down': 0})
            bucket['total'] += 1
            if row.status == 'up':
                bucket['up'] += 1
            elif row.status == 'down':
                bucket['down'] += 1

        out = []
        for offset in range(days):
            day = (start + timedelta(days=offset)).date()
            bucket = buckets.get(day.isoformat())
            if not bucket or not bucket['total']:
                out.append({'date': day.isoformat(), 'state': 'none',
                            'uptime': None, 'checks': 0, 'down_checks': 0})
                continue
            uptime = round(bucket['up'] / bucket['total'] * 100, 3)
            if bucket['down'] and uptime < 50:
                state = 'down'
            elif uptime < 100:
                state = 'partial'
            else:
                state = 'up'
            out.append({'date': day.isoformat(), 'state': state, 'uptime': uptime,
                        'checks': bucket['total'], 'down_checks': bucket['down']})
        return out

    @staticmethod
    def stats():
        """KPI-band counts for the Monitors tab."""
        monitors = StatusComponent.query.all()
        active = [m for m in monitors if not m.is_paused]
        by_status = {'operational': 0, 'degraded': 0, 'major_outage': 0,
                     'partial_outage': 0, 'maintenance': 0}
        for monitor in active:
            if monitor.status in by_status:
                by_status[monitor.status] += 1
        overall = None
        if active:
            values = [m.uptime_30d for m in active if m.uptime_30d is not None]
            if values:
                overall = round(sum(values) / len(values), 2)
        return {
            'total': len(monitors),
            'paused': len(monitors) - len(active),
            'by_status': by_status,
            'operational': by_status['operational'],
            'degraded': by_status['degraded'] + by_status['partial_outage'],
            'down': by_status['major_outage'],
            'overall_uptime_30d': overall,
        }

    # ------------------------------------------------------------------
    # Managed-site health bridge
    # ------------------------------------------------------------------

    # Map an EnvironmentHealthService overall_status to a HealthCheck status.
    # 'unknown' is intentionally absent — indeterminate checks are not recorded
    # so they don't pollute the uptime %.
    _HEALTH_MAP = {'healthy': 'up', 'degraded': 'degraded', 'unhealthy': 'down'}

    @staticmethod
    def sync_component_from_health(monitor, overall_status, error=None):
        """Drive a managed-site-bound monitor from an EnvironmentHealthService
        verdict instead of a network probe (#26).

        Returns the recorded HealthCheck, or None for an indeterminate
        ('unknown') verdict (not recorded).
        """
        check_status = MonitorService._HEALTH_MAP.get(overall_status)
        if not check_status:
            return None
        # A health verdict is authoritative, not a flaky network blip, so it
        # should reach major outage on the first 'unhealthy' rather than waiting
        # out the retry streak.
        if check_status == 'down':
            monitor.consecutive_failures = max(monitor.consecutive_failures or 0,
                                               monitor.retries or 0)
        return MonitorService._record(monitor, {'status': check_status, 'error': error})

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------

    @staticmethod
    def list_incidents(state=None, limit=100):
        query = StatusIncident.query
        if state == 'active':
            query = query.filter(StatusIncident.status != 'resolved')
        elif state == 'resolved':
            query = query.filter(StatusIncident.status == 'resolved')
        return query.order_by(StatusIncident.created_at.desc()).limit(limit).all()

    @staticmethod
    def create_incident(page_id, data):
        incident = StatusIncident(
            page_id=page_id,
            component_id=data.get('component_id'),
            title=data['title'],
            status=data.get('status', 'investigating'),
            impact=data.get('impact', 'minor'),
            body=data.get('body', ''),
            is_maintenance=data.get('is_maintenance', False),
            scheduled_start=data.get('scheduled_start'),
            scheduled_end=data.get('scheduled_end'),
        )
        db.session.add(incident)
        db.session.commit()
        return incident

    @staticmethod
    def update_incident(incident_id, data):
        incident = StatusIncident.query.get(incident_id)
        if not incident:
            return None
        for field in ['title', 'status', 'impact', 'body']:
            if field in data:
                setattr(incident, field, data[field])
        if data.get('status') == 'resolved':
            incident.resolved_at = datetime.utcnow()

        # Add timeline update
        if data.get('update_body'):
            update = StatusIncidentUpdate(
                incident_id=incident_id,
                status=data.get('status', incident.status),
                body=data['update_body'],
            )
            db.session.add(update)

        db.session.commit()
        return incident

    @staticmethod
    def delete_incident(incident_id):
        incident = StatusIncident.query.get(incident_id)
        if not incident:
            return False
        db.session.delete(incident)
        db.session.commit()
        return True

    @staticmethod
    def _open_incident_for_component(monitor, error=None):
        """Open a major-impact incident for a monitor if one is not already open."""
        existing = StatusIncident.query.filter(
            StatusIncident.component_id == monitor.id,
            StatusIncident.status != 'resolved',
        ).first()
        if existing:
            return existing
        # page_id may be None — a monitor that belongs to no status page still
        # gets an incident, it just isn't published anywhere.
        return MonitorService.create_incident(monitor.page_id, {
            'title': f'{monitor.name} is experiencing an outage',
            'status': 'investigating',
            'impact': 'major',
            'body': error or 'Automated health check detected an outage.',
            'component_id': monitor.id,
        })

    @staticmethod
    def _resolve_incident_for_component(monitor):
        """Resolve the open auto-incident for a monitor, if any."""
        existing = StatusIncident.query.filter(
            StatusIncident.component_id == monitor.id,
            StatusIncident.status != 'resolved',
        ).first()
        if existing:
            MonitorService.update_incident(existing.id, {
                'status': 'resolved',
                'update_body': 'Automated health check detected recovery.',
            })
