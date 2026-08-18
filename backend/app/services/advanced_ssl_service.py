import json
import logging
import subprocess
from datetime import datetime
from app.utils.system import run_unprivileged
from app.services.ssl_service import resolve_certbot_bin


def _certbot_bin():
    """Resolved certbot binary, falling back to the bare name (PATH lookup)."""
    return resolve_certbot_bin() or 'certbot'

logger = logging.getLogger(__name__)


class AdvancedSSLService:
    """Service for advanced SSL certificate features."""

    SSL_PROFILES = {
        'modern': {
            'label': 'Modern (TLS 1.3 only)',
            'protocols': 'TLSv1.3',
            'ciphers': '',
            'description': 'Best security. Supports only modern browsers.',
        },
        'intermediate': {
            'label': 'Intermediate (TLS 1.2+)',
            'protocols': 'TLSv1.2 TLSv1.3',
            'ciphers': 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384',
            'description': 'Recommended for most servers. Good compatibility.',
        },
        'legacy': {
            'label': 'Legacy (TLS 1.0+)',
            'protocols': 'TLSv1 TLSv1.1 TLSv1.2 TLSv1.3',
            'ciphers': 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256',
            'description': 'Maximum compatibility. Supports old clients.',
        },
    }

    @staticmethod
    def get_ssl_profiles():
        return AdvancedSSLService.SSL_PROFILES

    @staticmethod
    def issue_wildcard_cert(domain, dns_provider, credentials, email=None):
        """Issue a wildcard cert (domain + *.domain) via Let's Encrypt DNS-01.

        Supports cloudflare (API token) and route53 (AWS key/secret). The certbot
        DNS plugin matching the system certbot is installed best-effort first.
        Returns the on-disk cert/key paths on success.
        """
        import os
        from app.utils.system import PackageManager

        wildcard = f'*.{domain}'
        cmd = [_certbot_bin(), 'certonly', '--non-interactive', '--agree-tos',
               '--dns-' + dns_provider, '-d', domain, '-d', wildcard]
        cmd.extend(['--email', email] if email else ['--register-unsafely-without-email'])

        # Best-effort: ensure the DNS plugin matching the system certbot exists.
        if PackageManager.is_available():
            try:
                PackageManager.install([f'python3-certbot-dns-{dns_provider}'], timeout=300)
            except Exception:
                pass  # certbot reports a clear error below if the plugin is truly missing

        run_kwargs = {}
        if dns_provider == 'cloudflare':
            cred_file = f'/tmp/certbot-{dns_provider}.ini'
            with open(cred_file, 'w') as f:
                f.write(f"dns_cloudflare_api_token = {credentials.get('api_token', '')}\n")
            os.chmod(cred_file, 0o600)
            cmd.extend(['--dns-cloudflare-credentials', cred_file])
        elif dns_provider == 'route53':
            run_kwargs['env'] = {
                **os.environ,
                'AWS_ACCESS_KEY_ID': credentials.get('api_key', ''),
                'AWS_SECRET_ACCESS_KEY': credentials.get('api_secret', ''),
            }

        try:
            result = run_unprivileged(cmd, **run_kwargs)
            return {
                'success': True, 'domain': domain, 'type': 'wildcard',
                'certificate_path': f'/etc/letsencrypt/live/{domain}/fullchain.pem',
                'private_key_path': f'/etc/letsencrypt/live/{domain}/privkey.pem',
                'output': result.get('stdout', ''),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def issue_san_cert(domains):
        """Issue multi-domain (SAN) certificate."""
        if not domains or len(domains) < 1:
            raise ValueError('At least one domain required')

        cmd = [_certbot_bin(), 'certonly', '--non-interactive', '--agree-tos',
               '--webroot', '-w', '/var/www/html']
        for d in domains:
            cmd.extend(['-d', d])

        try:
            result = run_unprivileged(cmd)
            return {'success': True, 'domains': domains, 'type': 'san', 'output': result.get('stdout', '')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def upload_custom_cert(domain, cert_pem, key_pem, chain_pem=None):
        """Upload custom certificate files."""
        import os
        cert_dir = f'/etc/ssl/serverkit/{domain}'
        os.makedirs(cert_dir, exist_ok=True)

        cert_path = os.path.join(cert_dir, 'cert.pem')
        key_path = os.path.join(cert_dir, 'key.pem')
        chain_path = os.path.join(cert_dir, 'chain.pem')

        with open(cert_path, 'w') as f:
            f.write(cert_pem)
        with open(key_path, 'w') as f:
            f.write(key_pem)
        if os.name != 'nt':
            os.chmod(key_path, 0o600)
        if chain_pem:
            with open(chain_path, 'w') as f:
                f.write(chain_pem)

        return {
            'domain': domain,
            'cert_path': cert_path,
            'key_path': key_path,
            'chain_path': chain_path if chain_pem else None,
        }

    @staticmethod
    def get_cert_health(domain):
        """Check SSL health — grade, cipher suites, protocol versions."""
        import ssl
        import socket
        from datetime import timezone

        result = {
            'domain': domain,
            'valid': False,
            'grade': 'F',
            'protocols': [],
            'cipher_suites': [],
            'issuer': None,
            'expires_at': None,
            'days_remaining': None,
        }

        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((domain, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
                    cipher = ssock.cipher()

                    result['valid'] = True
                    result['cipher_suites'] = [cipher[0]] if cipher else []
                    result['protocols'] = [ssock.version()]

                    # Parse expiry
                    not_after = cert.get('notAfter')
                    if not_after:
                        expiry = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                        result['expires_at'] = expiry.isoformat()
                        result['days_remaining'] = (expiry - datetime.utcnow()).days

                    # Issuer
                    issuer = cert.get('issuer', ())
                    for field in issuer:
                        for k, v in field:
                            if k == 'organizationName':
                                result['issuer'] = v

                    # Simple grading
                    version = ssock.version()
                    if version == 'TLSv1.3':
                        result['grade'] = 'A+'
                    elif version == 'TLSv1.2':
                        result['grade'] = 'A'
                    elif version == 'TLSv1.1':
                        result['grade'] = 'B'
                    else:
                        result['grade'] = 'C'

        except Exception as e:
            result['error'] = str(e)

        return result

    @staticmethod
    def get_expiry_alerts(days_threshold=30):
        """Get certificates expiring within threshold days."""
        import os
        import glob

        alerts = []
        cert_paths = glob.glob('/etc/letsencrypt/live/*/cert.pem')
        cert_paths += glob.glob('/etc/ssl/serverkit/*/cert.pem')

        for cert_path in cert_paths:
            try:
                domain = os.path.basename(os.path.dirname(cert_path))
                result = run_unprivileged(['openssl', 'x509', '-enddate', '-noout', '-in', cert_path])
                stdout = result.get('stdout', '')
                if 'notAfter=' in stdout:
                    date_str = stdout.split('notAfter=')[1].strip()
                    expiry = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                    days = (expiry - datetime.utcnow()).days
                    if days <= days_threshold:
                        alerts.append({
                            'domain': domain,
                            'expires_at': expiry.isoformat(),
                            'days_remaining': days,
                            'severity': 'critical' if days <= 7 else 'warning',
                        })
            except Exception:
                continue

        return sorted(alerts, key=lambda x: x.get('days_remaining', 999))
