import os
import json
import logging
import re
from app.utils.system import run_command, run_privileged

logger = logging.getLogger(__name__)


class NginxAdvancedService:
    """Advanced Nginx configuration: reverse proxy, load balancing, caching, rate limiting."""

    NGINX_CONF_DIR = '/etc/nginx'
    SITES_AVAILABLE = '/etc/nginx/sites-available'
    SITES_ENABLED = '/etc/nginx/sites-enabled'

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

        # Write config
        conf_path = os.path.join(NginxAdvancedService.SITES_AVAILABLE, domain)
        with open(conf_path, 'w') as f:
            f.write(config)

        return {'domain': domain, 'config': config, 'path': conf_path}

    @staticmethod
    def test_config():
        """Test nginx config syntax."""
        # run_privileged, not run_command: `nginx -t` reads root-owned config
        # and nginx lives in /usr/sbin, which the panel's unit PATH omits. The
        # unprivileged bare-name call raised FileNotFoundError and this method
        # reported every config as INVALID.
        try:
            result = run_privileged(['nginx', '-t'])
            return {
                'valid': result.returncode == 0,
                'output': (result.stdout or '') + (result.stderr or ''),
            }
        except Exception as e:
            return {'valid': False, 'output': str(e)}

    @staticmethod
    def preview_diff(domain, new_config):
        """Preview config changes as a diff."""
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
        """Reload nginx configuration."""
        try:
            result = run_privileged(['nginx', '-s', 'reload'])
            if result.returncode != 0:
                return {'success': False,
                        'error': (result.stderr or 'nginx reload failed').strip()}
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

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
            result = run_command(['tail', '-n', str(lines), log_file])
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
