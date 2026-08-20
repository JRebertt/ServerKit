import os
import json
import logging
import re
from app.services.nginx_service import NginxService
from app.utils.system import run_unprivileged

logger = logging.getLogger(__name__)


class NginxAdvancedService:
    """Advanced Nginx configuration: reverse proxy, load balancing, caching, rate limiting."""

    # NginxService owns these (plan 75 §G4). Hardcoding them here meant an
    # NGINX_CONF_DIR override — the env var NginxService honours, and what
    # tests redirect — silently did not apply to this service.
    NGINX_CONF_DIR = NginxService.NGINX_CONF_DIR
    SITES_AVAILABLE = NginxService.SITES_AVAILABLE
    SITES_ENABLED = NginxService.SITES_ENABLED

    @staticmethod
    def get_proxy_rules(domain):
        """Get reverse proxy rules for a virtual host."""
        conf_path = os.path.join(NginxAdvancedService.SITES_AVAILABLE, domain)
        if not os.path.isfile(conf_path):
            return {'error': 'Config not found'}
        try:
            with open(conf_path, 'r') as f:
                content = f.read()
            return {'domain': domain, 'config': content}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def create_reverse_proxy(data):
        """Create a reverse proxy configuration."""
        domain = data['domain']
        upstreams = data.get('upstreams', [])
        lb_method = data.get('lb_method', 'round_robin')
        cache = data.get('cache', {})
        rate_limit = data.get('rate_limit', {})
        headers = data.get('headers', {})
        locations = data.get('locations', [])

        upstream_name = domain.replace('.', '_')

        lines = []

        # Upstream block
        if upstreams:
            lines.append(f'upstream {upstream_name} {{')
            if lb_method == 'least_conn':
                lines.append('    least_conn;')
            elif lb_method == 'ip_hash':
                lines.append('    ip_hash;')
            for u in upstreams:
                weight = f' weight={u["weight"]}' if u.get('weight') else ''
                lines.append(f'    server {u["address"]}{weight};')
            lines.append('}')
            lines.append('')

        # Rate limiting zone
        if rate_limit.get('enabled'):
            rps = rate_limit.get('requests_per_second', 10)
            lines.append(f'limit_req_zone $binary_remote_addr zone={upstream_name}_limit:10m rate={rps}r/s;')
            lines.append('')

        # Cache zone
        if cache.get('enabled'):
            cache_size = cache.get('size', '100m')
            cache_ttl = cache.get('ttl', '60m')
            lines.append(f'proxy_cache_path /var/cache/nginx/{upstream_name} levels=1:2 keys_zone={upstream_name}_cache:10m max_size={cache_size} inactive={cache_ttl};')
            lines.append('')

        # Server block
        lines.append('server {')
        lines.append(f'    listen 80;')
        lines.append(f'    server_name {domain};')
        lines.append('')

        # Custom headers
        for header_name, header_value in headers.get('add', {}).items():
            lines.append(f'    add_header {header_name} "{header_value}";')
        for header_name in headers.get('remove', []):
            lines.append(f'    proxy_hide_header {header_name};')

        if rate_limit.get('enabled'):
            burst = rate_limit.get('burst', 20)
            lines.append(f'    limit_req zone={upstream_name}_limit burst={burst} nodelay;')

        lines.append('')

        # Custom location blocks
        for loc in locations:
            lines.append(f'    location {loc["path"]} {{')
            if loc.get('proxy_pass'):
                lines.append(f'        proxy_pass {loc["proxy_pass"]};')
            elif upstreams:
                lines.append(f'        proxy_pass http://{upstream_name};')
            lines.append('        proxy_set_header Host $host;')
            lines.append('        proxy_set_header X-Real-IP $remote_addr;')
            lines.append('        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;')
            lines.append('        proxy_set_header X-Forwarded-Proto $scheme;')

            if cache.get('enabled') and not loc.get('no_cache'):
                lines.append(f'        proxy_cache {upstream_name}_cache;')
                for bypass in cache.get('bypass_rules', []):
                    lines.append(f'        proxy_cache_bypass {bypass};')

            lines.append('    }')
            lines.append('')

        # Default location if no custom locations
        if not locations:
            lines.append('    location / {')
            if upstreams:
                lines.append(f'        proxy_pass http://{upstream_name};')
            lines.append('        proxy_set_header Host $host;')
            lines.append('        proxy_set_header X-Real-IP $remote_addr;')
            lines.append('        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;')
            lines.append('        proxy_set_header X-Forwarded-Proto $scheme;')
            if cache.get('enabled'):
                lines.append(f'        proxy_cache {upstream_name}_cache;')
            lines.append('    }')

        lines.append('}')

        config = '\n'.join(lines)

        # Write config through the shared vhost door (plan 75 §G4). This was a
        # plain `open(conf_path, 'w')`: unprivileged, so it raises
        # PermissionError against a root-owned /etc/nginx/sites-available, and
        # it neither config-tested nor reloaded what it wrote.
        result = NginxService.write_vhost(domain, config)
        if not result['success']:
            return {'error': result['error'], 'domain': domain}

        return {'domain': domain, 'config': config, 'path': result['path']}

    @staticmethod
    def test_config():
        """Test nginx config syntax — NginxService owns the call (plan 75 §G4).

        Kept as a distinct method because its result shape (``valid``/
        ``output``) is what this service's API consumers read.
        """
        result = NginxService.test_config()
        return {
            'valid': result['success'],
            'output': result.get('message') or result.get('error') or '',
        }

    @staticmethod
    def preview_diff(domain, new_config):
        """Preview config changes as a diff."""
        # `domain` is joined onto SITES_AVAILABLE below — refuse anything that
        # is not a plain filename so ../ can't turn this into an arbitrary
        # file read (the API layer gates admins, but never trust one layer).
        if not domain or os.path.basename(domain) != domain or domain in ('.', '..'):
            return {'error': 'invalid domain'}
        conf_path = os.path.join(NginxAdvancedService.SITES_AVAILABLE, domain)
        old_config = ''
        if os.path.isfile(conf_path):
            with open(conf_path, 'r') as f:
                old_config = f.read()

        import difflib
        diff = list(difflib.unified_diff(
            old_config.splitlines(keepends=True),
            new_config.splitlines(keepends=True),
            fromfile=f'{domain} (current)',
            tofile=f'{domain} (new)',
        ))
        return {'diff': ''.join(diff), 'has_changes': len(diff) > 0}

    @staticmethod
    def reload_nginx():
        """Reload nginx — NginxService owns it (plan 75 §G4).

        The private version ran `nginx -s reload` with no config test first, so
        a broken vhost written by this same service reloaded straight into
        production instead of being refused.
        """
        return NginxService.reload()

    @staticmethod
    def get_vhost_logs(domain, log_type='access', lines=100):
        """Get access or error log for a virtual host."""
        log_dir = '/var/log/nginx'
        if log_type == 'error':
            log_file = os.path.join(log_dir, f'{domain}.error.log')
        else:
            log_file = os.path.join(log_dir, f'{domain}.access.log')

        if not os.path.isfile(log_file):
            # Fallback to default logs
            log_file = os.path.join(log_dir, f'{log_type}.log')

        if not os.path.isfile(log_file):
            return {'lines': [], 'error': 'Log file not found'}

        try:
            result = run_unprivileged(['tail', '-n', str(lines), log_file])
            log_lines = result.get('stdout', '').strip().split('\n')
            return {'lines': log_lines, 'file': log_file}
        except Exception as e:
            return {'lines': [], 'error': str(e)}

    @staticmethod
    def get_load_balancing_methods():
        return {
            'round_robin': 'Round Robin (default)',
            'least_conn': 'Least Connections',
            'ip_hash': 'IP Hash (sticky sessions)',
        }
