"""Publish a private service over a WireGuard tunnel (roadmap Phase 2).

Ties the pieces together: start a forwarder on the private peer (#13),
write the edge nginx vhost that proxies to the peer's WG IP (#12), point
DNS at the edge (#14), put basic-auth in front (#16), and obtain a cert
(#15). The nginx / DNS / cert / auth steps run on the panel host, which
acts as the edge (where the WG edge interface and nginx live). See
docs/REMOTE_ACCESS_ROADMAP.md.
"""

import logging
import re

from app import db
from app.models.exposed_service import ExposedService
from app.models.server import Server
from app.models.tunnel import Tunnel
from app.services.remote_command_dispatcher import dispatch_agent_command
from app.services.dns_provider_service import DNSProviderService
from app.services.environment_domain_service import EnvironmentDomainService
from app.services.nginx_service import NginxService
from app.services.ssl_service import SSLService

logger = logging.getLogger(__name__)

_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})+$'
)


class TunnelPublishError(Exception):
    """A publish step failed. ``status`` is the HTTP status the API returns."""

    def __init__(self, message, code='PUBLISH_ERROR', status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class TunnelPublishService:

    @staticmethod
    def list_for_tunnel(tunnel_id):
        return (ExposedService.query
                .filter_by(tunnel_id=tunnel_id)
                .order_by(ExposedService.created_at.desc())
                .all())

    @staticmethod
    def get(service_id):
        svc = ExposedService.query.get(service_id)
        if not svc:
            raise TunnelPublishError('exposed service not found', code='NOT_FOUND', status=404)
        return svc

    @classmethod
    def publish(cls, tunnel_id, hostname, port, *, require_auth=False,
                auth_username=None, auth_password=None, ssl=True,
                email=None, user_id=None):
        """Publish <hostname> → the private service on <port>. The forwarder
        and nginx steps are essential (failure aborts); DNS / auth / cert are
        best-effort and reported in the returned ``steps`` dict."""
        hostname = (hostname or '').strip().lower().rstrip('.')
        if not _HOSTNAME_RE.match(hostname):
            raise TunnelPublishError('invalid hostname', code='BAD_REQUEST')
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise TunnelPublishError('port must be an integer', code='BAD_REQUEST')
        if port < 1 or port > 65535:
            raise TunnelPublishError('port out of range', code='BAD_REQUEST')
        if require_auth and (not auth_username or not auth_password):
            raise TunnelPublishError(
                'auth_username and auth_password are required when require_auth is set',
                code='BAD_REQUEST')

        tunnel = Tunnel.query.get(tunnel_id)
        if not tunnel:
            raise TunnelPublishError('tunnel not found', code='NOT_FOUND', status=404)
        edge = Server.query.get(tunnel.edge_server_id)

        svc = ExposedService(
            tunnel_id=tunnel.id, hostname=hostname, port=port,
            nginx_site_name=hostname, require_auth=require_auth,
            auth_username=auth_username if require_auth else None,
            status='pending',
        )
        db.session.add(svc)
        db.session.commit()

        steps = {}
        try:
            # 1. Forwarder on the private peer (essential): WG IP:port → the
            #    real local service on 127.0.0.1:port.
            fwd = dispatch_agent_command(
                server_id=tunnel.private_server_id, action='wireguard:forward',
                params={'interface': tunnel.interface_name, 'listen_ip': tunnel.private_wg_ip,
                        'listen_port': port, 'target_host': '127.0.0.1', 'target_port': port},
                user_id=user_id, timeout=15.0,
            )
            if not fwd.get('success'):
                raise TunnelPublishError(
                    'failed to start forwarder on private host: %s' % fwd.get('error'),
                    code=fwd.get('code', 'FORWARD_FAILED'), status=502)
            steps['forward'] = {'ok': True}

            # 2. Edge nginx vhost (essential): proxy to the peer's WG IP.
            upstream = '%s:%d' % (tunnel.private_wg_ip, port)
            created = NginxService.create_site(
                name=hostname, app_type='remote', domains=[hostname],
                root_path='', upstream=upstream)
            if not created.get('success'):
                raise TunnelPublishError(
                    'failed to write nginx vhost: %s' % created.get('error'),
                    code='NGINX_FAILED', status=500)
            enabled = NginxService.enable_site(hostname)
            if not enabled.get('success'):
                raise TunnelPublishError(
                    'failed to enable nginx vhost: %s' % enabled.get('error'),
                    code='NGINX_FAILED', status=500)
            steps['nginx'] = {'ok': True}

            # 3. DNS A record → the edge's public IP (best-effort, #14).
            edge_ip = edge.ip_address if edge else None
            steps['dns'] = DNSProviderService.ensure_a_record(hostname, edge_ip)

            # 4. Basic-auth in front (best-effort, #16).
            if require_auth:
                steps['auth'] = EnvironmentDomainService.enable_basic_auth(
                    hostname, auth_username, auth_password)

            # 5. Cert on the edge (best-effort, #15). certbot --nginx wires
            #    the TLS into the vhost and reloads, so we only flag success.
            if ssl:
                cert = SSLService.obtain_certificate([hostname], email or ('admin@%s' % hostname))
                steps['ssl'] = {'ok': bool(cert.get('success')), 'error': cert.get('error')}
                if cert.get('success'):
                    svc.ssl_enabled = True

            svc.status = 'published'
            db.session.commit()
            return svc, steps
        except TunnelPublishError as e:
            svc.status = 'error'
            svc.last_error = e.message
            db.session.commit()
            raise

    @classmethod
    def unpublish(cls, service_id, user_id=None):
        svc = ExposedService.query.get(service_id)
        if not svc:
            raise TunnelPublishError('exposed service not found', code='NOT_FOUND', status=404)
        tunnel = Tunnel.query.get(svc.tunnel_id)

        # Remove the edge nginx vhost (best-effort).
        try:
            NginxService.delete_site(svc.nginx_site_name or svc.hostname)
        except Exception:
            logger.info('nginx delete_site failed during unpublish of %s', svc.hostname)

        # Stop the forwarder on the private peer (best-effort).
        if tunnel:
            try:
                dispatch_agent_command(
                    server_id=tunnel.private_server_id, action='wireguard:unforward',
                    params={'interface': tunnel.interface_name, 'listen_port': svc.port},
                    user_id=user_id, timeout=10.0)
            except Exception:
                logger.info('wireguard:unforward failed during unpublish of %s', svc.hostname)

        db.session.delete(svc)
        db.session.commit()
        return True
