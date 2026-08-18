"""Roundcube webmail management service (Docker-based)."""
import subprocess
from typing import Dict

from app.utils.system import run_checked, run_privileged, is_command_available


class RoundcubeService:
    """Service for managing Roundcube webmail via Docker."""

    CONTAINER_NAME = 'serverkit-roundcube'
    VOLUME_NAME = 'roundcube_data'
    IMAGE = 'roundcube/roundcubemail:latest'
    HOST_PORT = 9000

    @classmethod
    def get_status(cls) -> Dict:
        """Get Roundcube container status."""
        if not is_command_available('docker'):
            return {'installed': False, 'running': False, 'error': 'Docker not available'}

        try:
            result = run_checked(
                ['docker', 'inspect', '--format', '{{.State.Status}}', cls.CONTAINER_NAME],
                timeout=None)
            if not result['success']:
                return {'installed': False, 'running': False}

            status = result['output'].strip()
            return {
                'installed': True,
                'running': status == 'running',
                'status': status,
                'port': cls.HOST_PORT,
            }
        except Exception as e:
            return {'installed': False, 'running': False, 'error': str(e)}

    @classmethod
    def install(cls, imap_host: str = 'host.docker.internal',
                smtp_host: str = 'host.docker.internal',
                domain: str = None) -> Dict:
        """Install Roundcube via Docker container."""
        if not is_command_available('docker'):
            return {'success': False, 'error': 'Docker is not installed'}

        try:
            # Remove existing container if any
            run_checked(['docker', 'rm', '-f', cls.CONTAINER_NAME], timeout=None)

            # Create volume
            run_checked(['docker', 'volume', 'create', cls.VOLUME_NAME], timeout=None)

            # Run container
            result = run_checked([
                'docker', 'run', '-d',
                '--name', cls.CONTAINER_NAME,
                '--restart', 'unless-stopped',
                '--add-host', 'host.docker.internal:host-gateway',
                '-p', f'{cls.HOST_PORT}:80',
                '-e', f'ROUNDCUBEMAIL_DEFAULT_HOST=ssl://{imap_host}',
                '-e', f'ROUNDCUBEMAIL_SMTP_SERVER=tls://{smtp_host}',
                '-e', 'ROUNDCUBEMAIL_DEFAULT_PORT=993',
                '-e', 'ROUNDCUBEMAIL_SMTP_PORT=587',
                '-e', 'ROUNDCUBEMAIL_UPLOAD_MAX_FILESIZE=25M',
                '-e', 'ROUNDCUBEMAIL_SKIN=elastic',
                '-v', f'{cls.VOLUME_NAME}:/var/roundcube/db',
                cls.IMAGE,
            ], timeout=None)

            if not result['success']:
                return {'success': False,
                        'error': result['error'] or 'Failed to start container'}

            # Build a public URL: prefer a supplied domain, then auto-generate
            # webmail.<panel_domain>, and only fall back to localhost:port.
            from app.services.site_domain_service import SiteDomainService
            public_url = None
            warning = None
            if domain:
                public_url = f'http://{domain}'
                proxy_res = cls.configure_nginx_proxy(domain)
                if not proxy_res.get('success'):
                    warning = proxy_res.get('error')
            else:
                panel_origin = SiteDomainService.panel_origin()
                panel_host = None
                if panel_origin:
                    from urllib.parse import urlparse
                    panel_host = urlparse(panel_origin).hostname
                if panel_host:
                    webmail_domain = f'webmail.{panel_host}'
                    public_url = f'http://{webmail_domain}'
                    proxy_res = cls.configure_nginx_proxy(webmail_domain)
                    if not proxy_res.get('success'):
                        warning = proxy_res.get('error')

            if not public_url:
                public_url = f'http://localhost:{cls.HOST_PORT}'

            result = {
                'success': True,
                'message': 'Roundcube installed successfully',
                'port': cls.HOST_PORT,
                'url': public_url,
            }
            if warning:
                result['warning'] = warning
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def uninstall(cls) -> Dict:
        """Stop and remove Roundcube container."""
        try:
            run_checked(['docker', 'rm', '-f', cls.CONTAINER_NAME], timeout=None)
            return {'success': True, 'message': 'Roundcube uninstalled'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def start(cls) -> Dict:
        """Start Roundcube container."""
        try:
            result = run_checked(['docker', 'start', cls.CONTAINER_NAME], timeout=None)
            if result['success']:
                return {'success': True, 'message': 'Roundcube started'}
            return {'success': False, 'error': result['error'] or 'Start failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def stop(cls) -> Dict:
        """Stop Roundcube container."""
        try:
            result = run_checked(['docker', 'stop', cls.CONTAINER_NAME], timeout=None)
            if result['success']:
                return {'success': True, 'message': 'Roundcube stopped'}
            return {'success': False, 'error': result['error'] or 'Stop failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def restart(cls) -> Dict:
        """Restart Roundcube container."""
        try:
            result = run_checked(['docker', 'restart', cls.CONTAINER_NAME], timeout=None)
            if result['success']:
                return {'success': True, 'message': 'Roundcube restarted'}
            return {'success': False, 'error': result['error'] or 'Restart failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def configure_nginx_proxy(cls, domain: str) -> Dict:
        """Create Nginx reverse proxy config for Roundcube."""
        try:
            from app.services.nginx_service import NginxService

            config = f"""# Roundcube Webmail - Managed by ServerKit
server {{
    listen 80;
    server_name {domain};

    location / {{
        proxy_pass http://127.0.0.1:{cls.HOST_PORT};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 25m;
    }}
}}
"""
            site_name = f'roundcube-{domain.replace(".", "-")}'
            config_path = f'/etc/nginx/sites-available/{site_name}'
            enabled_path = f'/etc/nginx/sites-enabled/{site_name}'

            run_privileged(['tee', config_path], input=config)
            run_privileged(['ln', '-sf', config_path, enabled_path])

            # Test and reload
            test = run_privileged(['nginx', '-t'])
            if test.returncode != 0:
                # Rollback
                run_privileged(['rm', '-f', enabled_path])
                return {'success': False, 'error': f'Nginx config test failed: {test.stderr}'}

            run_privileged(['systemctl', 'reload', 'nginx'])

            return {
                'success': True,
                'message': f'Nginx proxy configured for {domain}',
                'url': f'http://{domain}',
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
