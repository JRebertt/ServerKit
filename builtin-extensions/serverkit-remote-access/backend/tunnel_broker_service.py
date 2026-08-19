"""WireGuard tunnel broker (roadmap Phase 1 — #8 / #10 / #11).

Pairs two agents over the existing agent command channel:
keygen → interface:up → peer:set → verify. The panel is the source of
truth; private keys never leave the hosts (only public keys are brokered
and persisted). See docs/REMOTE_ACCESS_ROADMAP.md.
"""

import logging
import time
from datetime import datetime

from app import db
from app.models.server import Server
from app.models.tunnel import Tunnel
from app.services.agent_registry import agent_registry
from app.services.remote_command_dispatcher import dispatch_agent_command
from . import tunnel_netutil

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 25


class TunnelBrokerError(Exception):
    """A broker step failed. ``code`` mirrors the agent send_command codes
    (AGENT_OFFLINE, PERMISSION_DENIED, TIMEOUT) plus broker-specific ones
    (NOT_CONNECTED, NO_WIREGUARD, NO_EDGE_IP, POOL_EXHAUSTED, NOT_FOUND,
    BAD_REQUEST). ``status`` is the HTTP status the API should return."""

    def __init__(self, message, code='BROKER_ERROR', status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class TunnelBrokerService:

    # ---- agent command helper ------------------------------------------

    @staticmethod
    def _cmd(server_id, action, params=None, user_id=None, timeout=20.0):
        """Send an agent command; raise TunnelBrokerError on failure.
        Returns the agent handler's ``data`` payload on success."""
        res = dispatch_agent_command(
            server_id=server_id, action=action, params=params or {},
            user_id=user_id, timeout=timeout,
        )
        if not res.get('success'):
            code = res.get('code', 'BROKER_ERROR')
            status = 409 if code == 'AGENT_OFFLINE' else (502 if code == 'TIMEOUT' else 400)
            raise TunnelBrokerError(
                "%s on %s failed: %s" % (action, server_id, res.get('error', 'unknown error')),
                code=code, status=status,
            )
        return res.get('data')

    # ---- preflight -----------------------------------------------------

    @staticmethod
    def _require_wireguard_agent(server_id, role):
        server = Server.query.get(server_id)
        if not server:
            raise TunnelBrokerError("%s server not found" % role, code='NOT_FOUND', status=404)
        agent = agent_registry.get_agent(server_id)
        if not agent:
            raise TunnelBrokerError(
                "%s server '%s' is not connected" % (role, server.name),
                code='NOT_CONNECTED', status=409,
            )
        if not (agent.capabilities or {}).get('wireguard'):
            raise TunnelBrokerError(
                "%s server '%s' lacks the wireguard capability "
                "(needs wireguard-tools + iproute2 on a Linux agent)" % (role, server.name),
                code='NO_WIREGUARD', status=409,
            )
        return server

    # ---- create --------------------------------------------------------

    @classmethod
    def create_tunnel(cls, edge_server_id, private_server_id, name=None, user_id=None):
        if not edge_server_id or not private_server_id:
            raise TunnelBrokerError("edge_server_id and private_server_id are required", code='BAD_REQUEST')
        if edge_server_id == private_server_id:
            raise TunnelBrokerError("edge and private servers must differ", code='BAD_REQUEST')

        edge = cls._require_wireguard_agent(edge_server_id, 'edge')
        private = cls._require_wireguard_agent(private_server_id, 'private')

        # The private peer dials the edge's public endpoint, so the edge
        # needs a reachable address.
        if not tunnel_netutil.validate_endpoint_host(edge.ip_address):
            raise TunnelBrokerError(
                "edge server '%s' has no usable public IP (ip_address=%r)" % (edge.name, edge.ip_address),
                code='NO_EDGE_IP', status=409,
            )

        used = [t.subnet for t in Tunnel.query.with_entities(Tunnel.subnet).all()]
        try:
            subnet, edge_ip, private_ip = tunnel_netutil.pick_subnet(used)
        except RuntimeError as e:
            raise TunnelBrokerError(str(e), code='POOL_EXHAUSTED', status=409)

        # Allocate a listen port unique to this edge (#20) so one edge can
        # front multiple private peers without UDP-port conflicts.
        used_ports = [t.listen_port for t in Tunnel.query
                      .with_entities(Tunnel.listen_port)
                      .filter(Tunnel.edge_server_id == edge_server_id).all()]
        try:
            listen_port = tunnel_netutil.pick_listen_port(used_ports)
        except RuntimeError as e:
            raise TunnelBrokerError(str(e), code='PORT_POOL_EXHAUSTED', status=409)

        tunnel = Tunnel(
            name=name or ("%s → %s" % (edge.name, private.name)),
            edge_server_id=edge_server_id,
            private_server_id=private_server_id,
            subnet=subnet,
            edge_wg_ip=edge_ip,
            private_wg_ip=private_ip,
            listen_port=listen_port,
            status='pending',
        )
        db.session.add(tunnel)
        db.session.flush()  # assign tunnel.id before deriving the interface name
        tunnel.interface_name = tunnel_netutil.interface_name_for(tunnel.id)
        db.session.commit()

        try:
            cls._bring_up(tunnel, edge, private, user_id)
        except TunnelBrokerError as e:
            tunnel.status = 'error'
            tunnel.last_error = e.message
            db.session.commit()
            raise

        return tunnel

    @classmethod
    def _bring_up(cls, tunnel, edge, private, user_id):
        iface = tunnel.interface_name

        # 1. keygen on both ends — public keys only come back.
        edge_kg = cls._cmd(edge.id, 'wireguard:keygen', {'interface': iface}, user_id)
        priv_kg = cls._cmd(private.id, 'wireguard:keygen', {'interface': iface}, user_id)
        edge_pub = (edge_kg or {}).get('public_key')
        priv_pub = (priv_kg or {}).get('public_key')
        if not edge_pub or not priv_pub:
            raise TunnelBrokerError("agent keygen returned no public key", code='BROKER_ERROR', status=502)
        tunnel.edge_pubkey = edge_pub
        tunnel.private_pubkey = priv_pub
        db.session.commit()

        # 2. interfaces up — the edge listens; the private side dials out.
        cls._cmd(edge.id, 'wireguard:interface:up',
                 {'name': iface, 'address': tunnel.edge_address(), 'listen_port': tunnel.listen_port}, user_id)
        cls._cmd(private.id, 'wireguard:interface:up',
                 {'name': iface, 'address': tunnel.private_address(), 'listen_port': 0}, user_id)

        # 3. peers — the private peer carries the edge endpoint + keepalive
        #    so it punches and holds the NAT mapping.
        cls._cmd(edge.id, 'wireguard:peer:set', {
            'interface': iface,
            'public_key': priv_pub,
            'allowed_ips': ["%s/32" % tunnel.private_wg_ip],
        }, user_id)
        cls._cmd(private.id, 'wireguard:peer:set', {
            'interface': iface,
            'public_key': edge_pub,
            'allowed_ips': ["%s/32" % tunnel.edge_wg_ip],
            'endpoint': "%s:%d" % (edge.ip_address, tunnel.listen_port),
            'persistent_keepalive': KEEPALIVE_SECONDS,
        }, user_id)

        db.session.commit()

        # 4. open the edge's inbound WireGuard UDP port (best-effort, #10).
        tunnel.firewall_status = cls._ensure_edge_port(edge.id, tunnel.listen_port, user_id)

        # 5. best-effort immediate verify (handshake may take a few seconds;
        #    #11 health-refresh confirms it later regardless).
        try:
            cls.refresh_status(tunnel, user_id=user_id)
        except TunnelBrokerError:
            logger.info("post-create status refresh failed for tunnel %s (will settle on next refresh)", tunnel.id)

    # ---- status / health (#11) -----------------------------------------

    @classmethod
    def refresh_status(cls, tunnel, user_id=None):
        """Poll wireguard:status on both ends and update the row's health.
        Returns {tunnel, edge, private}."""
        now = time.time()
        edge_status = cls._safe_status(tunnel.edge_server_id, tunnel.interface_name, user_id)
        private_status = cls._safe_status(tunnel.private_server_id, tunnel.interface_name, user_id)

        latest = max(cls._latest_handshake(edge_status), cls._latest_handshake(private_status))
        iface_up = bool((edge_status or {}).get('up')) and bool((private_status or {}).get('up'))
        tunnel.status = tunnel_netutil.derive_status(latest, now, interface_up=iface_up)
        if latest:
            tunnel.last_handshake_at = datetime.utcfromtimestamp(latest)
        db.session.commit()
        # Reachability diagnostic (#21): flag a likely blocked-UDP case.
        age = None
        if tunnel.created_at:
            try:
                age = now - tunnel.created_at.timestamp()
            except Exception:
                age = None
        diagnostic = tunnel_netutil.diagnose_reachability(latest, age, iface_up)
        return {'tunnel': tunnel.to_dict(), 'edge': edge_status,
                'private': private_status, 'diagnostic': diagnostic}

    @classmethod
    def _safe_status(cls, server_id, iface, user_id):
        """wireguard:status that returns None instead of raising — a
        disconnected end shouldn't blow up the whole status read."""
        try:
            return cls._cmd(server_id, 'wireguard:status', {'interface': iface}, user_id, timeout=10.0)
        except TunnelBrokerError:
            return None

    @staticmethod
    def _latest_handshake(status):
        if not status:
            return 0
        best = 0
        for p in (status.get('peers') or []):
            hs = p.get('latest_handshake') or 0
            if hs > best:
                best = hs
        return best

    # ---- teardown ------------------------------------------------------

    @classmethod
    def teardown_tunnel(cls, tunnel_id, user_id=None):
        tunnel = Tunnel.query.get(tunnel_id)
        if not tunnel:
            raise TunnelBrokerError("tunnel not found", code='NOT_FOUND', status=404)
        # Best-effort interface teardown on both ends — don't block delete on
        # a disconnected agent (the row is the source of truth; #19 reconciles).
        for sid in (tunnel.edge_server_id, tunnel.private_server_id):
            try:
                dispatch_agent_command(
                    server_id=sid, action='wireguard:interface:down',
                    params={'interface': tunnel.interface_name}, user_id=user_id, timeout=10.0,
                )
            except Exception:
                logger.info("interface:down on %s during teardown failed (continuing)", sid)
        db.session.delete(tunnel)
        db.session.commit()
        return True

    # ---- reads ---------------------------------------------------------

    @staticmethod
    def get_tunnel(tunnel_id):
        tunnel = Tunnel.query.get(tunnel_id)
        if not tunnel:
            raise TunnelBrokerError("tunnel not found", code='NOT_FOUND', status=404)
        return tunnel

    # ---- reconcile (#19: panel-authoritative persistence) --------------

    @staticmethod
    def schedule_reconcile(server_id):
        """Spawn a non-blocking background reconcile for a (re)connected
        server (#19). Safe to call from a Socket.IO handler — captures the
        Flask app and runs reconcile_server in its own context, so tunnels
        self-heal after an agent or panel restart."""
        try:
            from app import socketio
            from flask import current_app
            app = current_app._get_current_object()
        except Exception:
            logger.exception("reconcile: could not capture app/socketio")
            return

        def _run():
            with app.app_context():
                try:
                    TunnelBrokerService.reconcile_server(server_id)
                except Exception:
                    logger.exception("tunnel reconcile failed for %s", server_id)

        try:
            socketio.start_background_task(_run)
        except Exception:
            logger.exception("could not start reconcile task for %s", server_id)

    @classmethod
    def reconcile_server(cls, server_id, user_id=None):
        """Re-apply the config for every tunnel this server participates in.
        The panel is the source of truth; relies on the Phase-0 commands
        being idempotent. Best-effort per tunnel (a down peer doesn't block
        the others). Returns a per-tunnel result list."""
        from app.models.exposed_service import ExposedService
        tunnels = Tunnel.query.filter(
            ((Tunnel.edge_server_id == server_id) | (Tunnel.private_server_id == server_id)),
            Tunnel.status.in_(('up', 'degraded', 'pending')),
        ).all()
        out = []
        for t in tunnels:
            try:
                cls._reconcile_side(t, server_id, ExposedService, user_id)
                out.append({'tunnel_id': t.id, 'ok': True})
            except TunnelBrokerError as e:
                logger.info("reconcile of tunnel %s on %s failed: %s", t.id, server_id, e.message)
                out.append({'tunnel_id': t.id, 'ok': False, 'error': e.message})
        if out:
            logger.info("reconciled %d tunnel(s) for server %s", len(out), server_id)
        return out

    @classmethod
    def _reconcile_side(cls, tunnel, server_id, exposed_service_model, user_id):
        """Re-apply just the side of `tunnel` that belongs to server_id (the
        other end reconciles when it reconnects). Rebuilds from the stored
        public keys + endpoint — no private key ever needed here."""
        iface = tunnel.interface_name
        if tunnel.edge_server_id == server_id:
            cls._cmd(server_id, 'wireguard:interface:up',
                     {'name': iface, 'address': tunnel.edge_address(),
                      'listen_port': tunnel.listen_port}, user_id)
            if tunnel.private_pubkey:
                cls._cmd(server_id, 'wireguard:peer:set',
                         {'interface': iface, 'public_key': tunnel.private_pubkey,
                          'allowed_ips': ['%s/32' % tunnel.private_wg_ip]}, user_id)
            try:
                cls._ensure_edge_port(server_id, tunnel.listen_port, user_id)
            except Exception:
                pass
        else:
            cls._cmd(server_id, 'wireguard:interface:up',
                     {'name': iface, 'address': tunnel.private_address(),
                      'listen_port': 0}, user_id)
            edge = Server.query.get(tunnel.edge_server_id)
            if tunnel.edge_pubkey and edge and edge.ip_address:
                cls._cmd(server_id, 'wireguard:peer:set',
                         {'interface': iface, 'public_key': tunnel.edge_pubkey,
                          'allowed_ips': ['%s/32' % tunnel.edge_wg_ip],
                          'endpoint': '%s:%d' % (edge.ip_address, tunnel.listen_port),
                          'persistent_keepalive': KEEPALIVE_SECONDS}, user_id)
            # Re-apply the service forwarders for this tunnel.
            for svc in exposed_service_model.query.filter_by(tunnel_id=tunnel.id).all():
                try:
                    cls._cmd(server_id, 'wireguard:forward',
                             {'interface': iface, 'listen_ip': tunnel.private_wg_ip,
                              'listen_port': svc.port, 'target_host': '127.0.0.1',
                              'target_port': svc.port}, user_id)
                except TunnelBrokerError:
                    pass

    # ---- firewall (#10) ------------------------------------------------

    @staticmethod
    def _ensure_edge_port(edge_server_id, port, user_id=None):
        """Open the edge's inbound UDP <port> via the agent's
        firewall:allow_port command (#10). Best-effort — a failure (no
        firewall present, missing `firewall:*` grant, or an older agent
        without the command) is non-fatal: the tunnel still works if the
        port is already open, and the create response always carries the
        manual commands too. Returns a small outcome dict for the UI."""
        try:
            res = dispatch_agent_command(
                server_id=edge_server_id, action='firewall:allow_port',
                params={'port': port, 'protocol': 'udp'}, user_id=user_id, timeout=15.0,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.info("edge firewall open failed for %s: %s", edge_server_id, e)
            return {'opened': False, 'error': str(e)}
        if res.get('success'):
            data = res.get('data') or {}
            return {'opened': True, 'method': data.get('method')}
        logger.info("edge firewall open not applied for %s: %s", edge_server_id, res.get('error'))
        return {'opened': False, 'error': res.get('error'), 'code': res.get('code')}

    @staticmethod
    def firewall_hint(port):
        """The edge must accept inbound UDP for the WireGuard handshake.
        There's no dedicated firewall agent command yet (a small follow-up,
        like the wireguard:* primitives), so for now we surface the exact
        step/commands rather than guessing at system:exec."""
        return {
            'port': port,
            'protocol': 'udp',
            'target': 'edge',
            'note': "Open inbound UDP %d on the edge server for the WireGuard handshake." % port,
            'commands': [
                "ufw allow %d/udp" % port,
                "firewall-cmd --add-port=%d/udp --permanent && firewall-cmd --reload" % port,
            ],
        }
