"""Reconcile-on-connect (plan 22 Phase 3).

When the operator finally connects a DNS provider / sets a server IP / picks a
base domain, the sites they already created are still pointing at nothing. This
service reconciles that backlog explicitly (never auto-applied — Decision 3):

* **DNS backfill** — enumerate the managed hosts that need an A record given the
  current base/mode, preview which a connected provider would cover, then loop
  ``DNSProviderService.ensure_a_record`` over them. Idempotent: an existing
  record returns ``created: False`` and is left untouched.
* **WordPress URL-fix** — detect WordPress sites whose live siteurl/home still
  points at ``localhost``/a stale IP and swap it to the site's real managed URL
  via the URL-swap rails (keeping the old-host redirect). A site already on its
  target URL is not detected, so a second run is a no-op.

Both apply loops are exposed as job handlers so a large backfill/heal runs off
the request thread (the API enqueues; see ``app/api/setup_health.py``).
"""
import ipaddress
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DNS_BACKFILL_JOB_KIND = 'setup.reconcile.dns_backfill'
URL_FIX_JOB_KIND = 'setup.reconcile.url_fix'

# Loopback / local host labels that a live site URL must be swapped away from.
_LOCAL_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '::1'}

# Reserved / dev suffixes whose hosts never get a public DNS record (the doctor's
# own filter — bare IPs and no-dot single labels are handled separately).
_DEV_SUFFIXES = ('.lvh.me', '.local', '.test', '.internal', '.localhost')


class SetupReconcileService:
    """DNS backfill + WordPress URL-fix for apps adopted before setup finished."""

    # ------------------------------------------------------------------ #
    # Host classification
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_ip(host):
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    @classmethod
    def _skip_dns_host(cls, host):
        """Dev/loopback names and bare IPs are skipped (the doctor's own filter)."""
        h = (host or '').strip().lower().rstrip('.')
        if not h or '.' not in h:
            return True
        if cls._is_ip(h):
            return True
        if h == 'localhost' or any(h.endswith(suf) for suf in _DEV_SUFFIXES):
            return True
        return False

    # ------------------------------------------------------------------ #
    # DNS backfill — candidate enumeration
    # ------------------------------------------------------------------ #

    @classmethod
    def _dns_candidates(cls):
        """The managed hosts that need a DNS record, by mode:

        * a base in ``wildcard`` mode → a single ``*.<base>`` candidate (the
          per-site subdomains are covered by it, so they aren't separate),
        * a base in ``per-site`` mode → each subdomain as its own candidate,
        * a domain outside every base → a ``custom`` candidate.

        Dev/loopback names and bare IPs are skipped.
        """
        from app.models.domain import Domain
        from app.services.site_domain_service import SiteDomainService

        candidates = []
        seen = set()
        # query_active: a tombstone here made DNS backfill CREATE a real A record
        # at the provider for a domain the user had deleted.
        for domain in Domain.query_active().order_by(Domain.name.asc()).all():
            host = (domain.name or '').strip().lower()
            if cls._skip_dns_host(host):
                continue
            base = SiteDomainService.covering_base(host)
            if base:
                mode = SiteDomainService.dns_mode(base)
                if mode == 'wildcard':
                    wildcard = f'*.{base}'
                    if wildcard in seen:
                        continue
                    seen.add(wildcard)
                    candidates.append({'host': wildcard, 'mode': 'wildcard',
                                       'base': base})
                else:  # per-site
                    if host in seen:
                        continue
                    seen.add(host)
                    candidates.append({'host': host, 'mode': 'per-site',
                                       'base': base})
            else:
                if host in seen:
                    continue
                seen.add(host)
                candidates.append({'host': host, 'mode': 'custom', 'base': None})
        return candidates

    @staticmethod
    def _provider_covers_zone(host):
        """Whether a connected provider authoritatively covers ``host``'s zone.
        Never raises (provider listing hits the network)."""
        try:
            from app.services.dns_provider_service import DNSProviderService
            config, _zone = DNSProviderService.find_zone_for_domain(host)
            return bool(config)
        except Exception:  # noqa: BLE001
            return False

    @classmethod
    def dns_backfill_preview(cls):
        """Dry-run: the managed hosts a backfill would ensure an A record for, and
        whether a connected provider covers each host's zone. Never writes."""
        from app.models.email import DNSProviderConfig
        from app.services.site_domain_service import SiteDomainService

        server_ip = SiteDomainService.server_ip()
        has_provider = DNSProviderConfig.query.count() > 0
        ready = bool(server_ip)

        items = []
        for cand in cls._dns_candidates():
            # Only probe provider coverage when the backfill could actually run —
            # avoids a network round-trip when there's nothing to apply.
            covered = (cls._provider_covers_zone(cand['host'])
                       if (has_provider and ready) else False)
            items.append({
                'host': cand['host'],
                'mode': cand['mode'],
                'target_ip': server_ip,
                'provider_covers_zone': covered,
            })

        return {
            'ready': ready,
            'has_provider': has_provider,
            'server_ip': server_ip,
            'items': items,
            'count': len(items),
            'total': len(items),
        }

    @classmethod
    def dns_backfill_apply(cls):
        """Loop ``ensure_a_record`` over every candidate. Idempotent — an existing
        record returns ``created: False`` and is left untouched. Returns per-host
        results + a created count."""
        from app.services.dns_provider_service import DNSProviderService
        from app.services.site_domain_service import SiteDomainService

        server_ip = SiteDomainService.server_ip()
        if not server_ip:
            return {'applied': 0, 'results': [], 'total': 0,
                    'error': 'No server public IP set.'}

        candidates = cls._dns_candidates()
        results = []
        applied = 0
        for cand in candidates:
            host = cand['host']
            try:
                res = DNSProviderService.ensure_a_record(host, server_ip)
            except Exception as e:  # noqa: BLE001
                res = {'created': False, 'reason': 'error', 'error': str(e)}
            created = bool(res.get('created'))
            if created:
                applied += 1
            row = {'host': host, 'mode': cand['mode']}
            row.update(res)
            row['created'] = created
            results.append(row)

        return {'applied': applied, 'results': results, 'total': len(candidates)}

    @classmethod
    def run_dns_backfill_job(cls, job):
        """Job handler for ``setup.reconcile.dns_backfill``."""
        return cls.dns_backfill_apply()

    # ------------------------------------------------------------------ #
    # WordPress url-fix — classifier
    # ------------------------------------------------------------------ #

    @staticmethod
    def _host_of(url):
        try:
            return (urlparse(url).hostname or '').strip().lower()
        except Exception:  # noqa: BLE001
            return ''

    @classmethod
    def _is_local_host(cls, host):
        """A loopback/local label or a bare IP — not a real public host."""
        if not host:
            return False
        if host in _LOCAL_HOSTS:
            return True
        if cls._is_ip(host):
            return True
        if '.' not in host:  # a bare single label (e.g. 'localhost')
            return True
        return False

    @classmethod
    def _is_real_domain(cls, host):
        return bool(host) and '.' in host and not cls._is_ip(host) \
            and host not in _LOCAL_HOSTS

    @classmethod
    def url_fix_needed(cls, current_url, target_url):
        """Pure classifier (testable without wp-cli): does a site at
        ``current_url`` need swapping to ``target_url``?

        Needs a fix when the current host is a local/loopback name or a bare IP
        AND there is a real domain target that differs. A current host that is
        already a proper domain (== target or otherwise) is left alone.
        """
        if not current_url or not target_url:
            return False
        current = cls._host_of(current_url)
        target = cls._host_of(target_url)
        if not current or not target:
            return False
        if not cls._is_real_domain(target):
            return False
        if not cls._is_local_host(current):
            return False
        return current != target

    # ------------------------------------------------------------------ #
    # WordPress url-fix — site enumeration + target resolution
    # ------------------------------------------------------------------ #

    @classmethod
    def _wp_sites(cls):
        """Production WordPress sites with a root path, or [] when the WordPress
        extension isn't loadable (dev without it, minimal test env)."""
        try:
            from app.models.wordpress_site import WordPressSite
        except Exception:  # noqa: BLE001
            return []
        try:
            sites = WordPressSite.query.all()
        except Exception:  # noqa: BLE001
            return []
        return [s for s in sites
                if s.application and getattr(s.application, 'root_path', None)]

    @classmethod
    def _target_url_for(cls, app):
        """The real managed URL a site should serve under — its primary domain,
        else None (nothing to point at)."""
        from app.models.domain import Domain
        from app.services.site_domain_service import SiteDomainService

        # query_active: delete_domain does not reassign is_primary, so the only
        # is_primary row can be a TOMBSTONE -- and this drives a WP-CLI
        # search-replace across the whole database. Pointing it at a deleted host
        # takes the live site down.
        domain = Domain.query_active().filter_by(
            application_id=app.id, is_primary=True).first()
        if not domain or not domain.name:
            return None
        host = domain.name.strip().lower()

        ssl = bool(getattr(domain, 'ssl_enabled', False))
        if not ssl:
            try:
                base = SiteDomainService.covering_base(host)
                ssl = bool(base and SiteDomainService.https_enabled(base)
                           and SiteDomainService.covers(host))
            except Exception:  # noqa: BLE001
                ssl = False
        scheme = 'https' if ssl else 'http'
        return f'{scheme}://{host}'

    @classmethod
    def url_fix_preview(cls):
        """Detect WordPress sites whose live URL is still localhost/a stale IP and
        show the per-site swap (current → target) via the URL-swap preview rails.
        Never mutates."""
        import app.services.wordpress_bridge as bridge
        try:
            wp = bridge.wordpress_service()
        except Exception as e:  # noqa: BLE001
            return {'count': 0, 'items': [], 'warning': str(e)}

        items = []
        for site in cls._wp_sites():
            app = site.application
            target = cls._target_url_for(app)
            if not target:
                continue
            try:
                current = wp._site_current_url(app)
            except Exception:  # noqa: BLE001
                continue
            if not cls.url_fix_needed(current, target):
                continue
            entry = {'site_id': site.id, 'current_url': current, 'new_url': target}
            try:
                preview = wp.preview_url_change(app, target)
                entry['pairs'] = preview.get('pairs')
                entry['total'] = preview.get('total')
                entry['success'] = preview.get('success', True)
            except Exception as e:  # noqa: BLE001
                entry['warning'] = str(e)
            items.append(entry)

        return {'count': len(items), 'items': items}

    @classmethod
    def url_fix_apply(cls):
        """Apply the URL swap to every detected site via ``change_site_url``
        (keeps the old-host redirect). Idempotent — a site already on its target
        URL is not detected, so a second run is a no-op."""
        import app.services.wordpress_bridge as bridge
        try:
            wp = bridge.wordpress_service()
        except Exception as e:  # noqa: BLE001
            return {'fixed': 0, 'results': [], 'error': str(e)}

        results = []
        fixed = 0
        for site in cls._wp_sites():
            app = site.application
            target = cls._target_url_for(app)
            if not target:
                continue
            try:
                current = wp._site_current_url(app)
            except Exception:  # noqa: BLE001
                continue
            if not cls.url_fix_needed(current, target):
                continue
            try:
                res = wp.change_site_url(app, target, keep_old_redirect=True)
            except Exception as e:  # noqa: BLE001
                res = {'success': False, 'error': str(e)}
            if res.get('success'):
                fixed += 1
            results.append({'site_id': site.id, 'new_url': target,
                            'old_url': res.get('old_url', current),
                            'success': bool(res.get('success'))})

        return {'fixed': fixed, 'results': results}

    @classmethod
    def run_url_fix_job(cls, job):
        """Job handler for ``setup.reconcile.url_fix``."""
        return cls.url_fix_apply()

    # ------------------------------------------------------------------ #
    # Job registration
    # ------------------------------------------------------------------ #

    @classmethod
    def register_jobs(cls):
        """Register both reconcile handlers with the job registry (called once at
        app startup, see app/__init__.py)."""
        from app.jobs import registry
        registry.register(DNS_BACKFILL_JOB_KIND, cls.run_dns_backfill_job,
                          replace=True)
        registry.register(URL_FIX_JOB_KIND, cls.run_url_fix_job, replace=True)
