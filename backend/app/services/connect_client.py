"""ServerKit Cloud connect — panel side.

Pairing: enroll with ServerKit Cloud, print the pairing code + fingerprint, poll with an
Ed25519 proof-of-possession until the user approves in the browser, then
write ``connect.json`` next to the panel config. The enrollment_secret is
kept in memory for the pairing session only — never written to disk or
logged.

Transport: once ``connect.json`` exists, a managed background thread (``RelayClient``,
started from app init via ``start_client_if_paired`` — same pattern as
linked_panel_agent) holds an outbound WebSocket to the relay: signed hello
(``device_id|ts|nonce``), a ``{"t":"ping"}`` heartbeat every 20 s, jittered
exponential backoff on drops, flap detection, and a long-poll fallback for
networks that break WebSockets. Runtime state is persisted to
``connect-state.json`` so `serverkit connect status` and the API show it
without the thread running. Stream opens this client does not implement are answered with close +
``unsupported``.

ServerKit Cloud endpoints (no session auth on the panel side):
  POST /api/pair/enroll   -> enrollment_id, enrollment_secret (shown once), code
  POST /api/pair/poll     -> 202 pending / 200 claimed (signed proof-of-possession)
  POST /api/pair/rotate   -> new code + expires_at
"""
import collections
import json
import logging
import os
import random
import secrets
import socket
import threading
import time
import urllib.parse
from datetime import datetime, timezone

import requests

from app import paths
from app.services import connect_keys

logger = logging.getLogger(__name__)

DEFAULT_CLOUD_URL = 'https://app.serverkit.ai'
CONNECT_FILENAME = 'connect.json'
KEY_PATH_FIELD = 'key_path'

# Connection state enum — the same names ServerKit Cloud uses on the Device row.
STATES = ('unpaired', 'pairing', 'paired_offline', 'online', 'degraded', 'revoked')

HTTP_TIMEOUT_S = 20
DEFAULT_PAIR_TIMEOUT_S = 15 * 60  # generous: the user may walk away to log in
POLL_INTERVAL_S = 3.0


class ConnectError(Exception):
    """Pairing failed in a way worth showing the operator verbatim."""


# ==================== Paths / config ====================


def resolve_cloud_url(cli_url: str = None) -> str:
    """--cloud flag > SERVERKIT_CLOUD_URL env var > DEFAULT_CLOUD_URL."""
    url = (cli_url or os.environ.get('SERVERKIT_CLOUD_URL') or DEFAULT_CLOUD_URL)
    url = url.strip().rstrip('/')
    if not url.startswith(('http://', 'https://')):
        raise ConnectError(f'ServerKit Cloud URL must start with http:// or https:// (got {url!r})')
    return url


def connect_file_path() -> str:
    return os.path.join(paths.SERVERKIT_CONFIG_DIR, CONNECT_FILENAME)


def _read_connect_file() -> dict:
    path = connect_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning('Could not read %s: %s', path, exc)
        return {}


def _write_connect_file(payload: dict):
    path = connect_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
        f.write('\n')
    if os.name != 'nt':
        os.chmod(path, 0o600)


# ==================== Facts ====================


def _panel_machine_id(fallback: str) -> str:
    """Stable id for this panel host: /etc/machine-id, else the device fingerprint."""
    for candidate in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                value = f.read().strip()
            if value:
                return value
        except OSError:
            continue
    return fallback


def _gather_hosts() -> list:
    """One host entry (kind 'agent') per agent-backed Server this panel manages.

    Server rows carry no machine_id/fingerprint for their agents, so only
    agent_id and hostname are reported. Without a Flask app context (or with
    the DB down) the honest answer is an empty list.
    """
    try:
        from flask import has_app_context
        if not has_app_context():
            return []
        from app.models.server import Server
        servers = (
            Server.query
            .filter(Server.agent_id.isnot(None))
            .with_entities(Server.agent_id, Server.hostname, Server.name)
            .all()
        )
        return [
            {
                'agent_id': s.agent_id,
                'machine_id': None,
                'fingerprint': None,
                'hostname': s.hostname or s.name,
                'kind': 'agent',
            }
            for s in servers
        ]
    except Exception as exc:  # never block pairing on host enumeration
        logger.warning('Could not enumerate managed agents: %s', exc)
        return []


# ==================== Pairing ====================


def _post(cloud_url: str, endpoint: str, body: dict) -> requests.Response:
    return requests.post(
        f'{cloud_url}/api/pair/{endpoint}',
        json=body,
        timeout=HTTP_TIMEOUT_S,
    )


def _error_detail(resp: requests.Response) -> str:
    try:
        detail = resp.json().get('detail')
    except ValueError:
        detail = None
    if isinstance(detail, dict):
        detail = detail.get('error')
    return detail or resp.text[:200] or f'HTTP {resp.status_code}'


def _print_code(echo, code: str, fingerprint: str, cloud_url: str, expires_at: str):
    echo('')
    echo(f'  Pairing code:  {code}')
    echo(f'  Fingerprint:   {connect_keys.format_fingerprint(fingerprint)}')
    echo('')
    echo(f'  Approve this server at {cloud_url}/pair — enter the code and')
    echo('  confirm the fingerprint matches exactly.')
    echo(f'  Code expires at {expires_at}; a new one is printed automatically.')
    echo('')


def connect(cloud_url: str = None, echo=print, timeout_s: int = DEFAULT_PAIR_TIMEOUT_S,
            poll_interval: float = POLL_INTERVAL_S) -> dict:
    """Pair this panel with ServerKit Cloud. Returns the written connect.json payload.

    Blocks (polling every ~3 s) until the enrollment is claimed, the overall
    timeout elapses, or ServerKit Cloud rejects the enrollment. Ctrl+C is handled by the
    caller (KeyboardInterrupt).
    """
    cloud_url = resolve_cloud_url(cloud_url)

    existing = _read_connect_file()
    if existing.get('device_id'):
        raise ConnectError(
            f'This panel is already connected to {existing.get("org_slug") or "an organization"} '
            f'as "{existing.get("name")}". Run `serverkit connect status` for details or '
            '`serverkit connect disconnect` first.'
        )

    private_key, pubkey_hex, fingerprint = connect_keys.load_or_create_keypair()

    from app.utils.version import get_panel_version
    body = {
        'pubkey': pubkey_hex,
        'fingerprint': fingerprint,
        'hostname': socket.gethostname(),
        'panel_version': get_panel_version(),
        'proto': 1,
        'machine_id': _panel_machine_id(fingerprint),
        'hosts': _gather_hosts(),
    }

    try:
        resp = _post(cloud_url, 'enroll', body)
    except requests.RequestException as exc:
        raise ConnectError(f'Cannot reach ServerKit Cloud at {cloud_url}: {exc}')
    if resp.status_code == 409:
        raise ConnectError(f'ServerKit Cloud refused enrollment: {_error_detail(resp)}')
    if resp.status_code != 201:
        raise ConnectError(f'Enroll failed ({resp.status_code}): {_error_detail(resp)}')

    enrolled = resp.json()
    enrollment_id = enrolled['enrollment_id']
    enrollment_secret = enrolled['enrollment_secret']  # session-only; never stored
    code = enrolled['code']
    expires_at = enrolled.get('expires_at')

    echo(f'Connecting this panel to ServerKit Cloud ({cloud_url}) ...')
    _print_code(echo, code, fingerprint, cloud_url, expires_at)

    deadline = time.monotonic() + timeout_s
    last_warning = 0.0
    while time.monotonic() < deadline:
        if expires_at and _past(expires_at):
            try:
                rot = _post(cloud_url, 'rotate', {
                    'enrollment_id': enrollment_id,
                    'enrollment_secret': enrollment_secret,
                })
                if rot.status_code == 200:
                    data = rot.json()
                    code, expires_at = data['code'], data.get('expires_at')
                    echo('The previous code expired; here is a new one.')
                    _print_code(echo, code, fingerprint, cloud_url, expires_at)
                elif rot.status_code != 423:  # 423 = frozen: someone is typing it — keep it
                    logger.warning('Code rotation failed (%s): %s',
                                   rot.status_code, _error_detail(rot))
                    expires_at = None  # avoid hammering; poll until claimed/timeout
            except requests.RequestException:
                pass

        ts = int(time.time())
        sig = private_key.sign(f'{enrollment_id}|{ts}'.encode()).hex()
        try:
            poll = _post(cloud_url, 'poll', {
                'enrollment_id': enrollment_id,
                'enrollment_secret': enrollment_secret,
                'ts': ts,
                'sig': sig,
            })
        except requests.RequestException as exc:
            now = time.monotonic()
            if now - last_warning > 15:
                last_warning = now
                echo(f'  ... waiting (ServerKit Cloud unreachable: {exc}); will retry')
            time.sleep(poll_interval)
            continue

        if poll.status_code == 200:
            claimed = poll.json()
            payload = {
                'device_id': claimed.get('device_id'),
                'org_slug': claimed.get('org_slug'),
                'name': claimed.get('name'),
                'relay_url': claimed.get('relay_url'),
                'scopes': claimed.get('scopes') or [],
                'fingerprint': fingerprint,
                KEY_PATH_FIELD: connect_keys.default_key_path(),
                'cloud_url': cloud_url,
                'paired_at': datetime.now(timezone.utc).isoformat(),
            }
            _write_connect_file(payload)
            echo('')
            echo(f'Connected to organization "{payload["org_slug"]}" '
                 f'as "{payload["name"]}".')
            echo(f'State saved to {connect_file_path()}')
            return payload

        if poll.status_code == 202:
            time.sleep(poll_interval)
            continue
        if poll.status_code == 423:
            raise ConnectError(f'Enrollment locked by ServerKit Cloud: {_error_detail(poll)}')
        if poll.status_code in (400, 401):
            raise ConnectError(f'ServerKit Cloud rejected this enrollment: {_error_detail(poll)}')
        logger.warning('Unexpected poll response %s: %s',
                       poll.status_code, _error_detail(poll))
        time.sleep(poll_interval)

    raise ConnectError(
        f'Pairing timed out after {timeout_s // 60} minutes. '
        'Run `serverkit connect` again to start a new enrollment.'
    )


def _past(iso_ts: str) -> bool:
    try:
        dt = datetime.fromisoformat(str(iso_ts))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= dt


# ==================== Status / disconnect ====================


def status() -> dict:
    """Connection state as the UI/CLI should show it.

    Reads connect.json (pairing), connect-state.json (runtime transport
    state, written by RelayClient) and checks the device key — no thread
    needs to be running in this process.
    """
    data = _read_connect_file()
    key_path = data.get(KEY_PATH_FIELD) or connect_keys.default_key_path()
    key_present = os.path.exists(key_path)
    if not data.get('device_id'):
        return {
            'state': 'unpaired',
            'state_reason': None,
            'paired': False,
            'cloud_url': resolve_cloud_url(),
            'key_present': key_present,
            'key_path': key_path,
        }
    saved = _read_state_file()
    if saved.get('state'):
        state = saved['state']
        reason = saved.get('state_reason')
    else:
        state = 'paired_offline' if key_present else 'degraded'
        reason = 'never_connected' if key_present else 'device_key_missing'
    return {
        'state': state,
        'state_reason': reason,
        'paired': True,
        'cloud_url': data.get('cloud_url') or resolve_cloud_url(),
        'device_id': data.get('device_id'),
        'org_slug': data.get('org_slug'),
        'name': data.get('name'),
        'relay_url': data.get('relay_url'),
        'scopes': data.get('scopes') or [],
        'transport': saved.get('transport'),
        'relay_instance': saved.get('relay_instance'),
        'last_connected_at': saved.get('last_connected_at'),
        'fingerprint': data.get('fingerprint'),
        'fingerprint_grouped': connect_keys.format_fingerprint(data['fingerprint'])
        if data.get('fingerprint') else None,
        'paired_at': data.get('paired_at'),
        'key_present': key_present,
        'key_path': key_path,
    }


def disconnect(remove_key: bool = False) -> dict:
    """Forget the pairing locally. Does NOT revoke anything on ServerKit Cloud."""
    stop_relay_client()  # no-op unless the client runs in this process
    removed = []
    for path in (connect_file_path(), state_file_path()):
        if os.path.exists(path):
            os.unlink(path)
            removed.append(path)
    if remove_key:
        key_path = connect_keys.default_key_path()
        if os.path.exists(key_path):
            os.unlink(key_path)
            removed.append(key_path)
    return {'success': True, 'removed': removed, 'state': 'unpaired'}


# ==================== Relay transport ====================

DEFAULT_RELAY_URL = 'wss://relay.serverkit.ai/v1/device'
STATE_FILENAME = 'connect-state.json'

PROTO_VERSION = 1
HELLO_TIMEOUT_S = 10        # the relay closes devices that take longer to hello
PING_INTERVAL_S = 20        # panel -> relay {"t":"ping"} heartbeat
MAX_FRAME_BYTES = 256 * 1024

BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 60.0
BACKOFF_JITTER = 0.25       # ±25%
STABLE_AFTER_S = 120        # a connection stable this long resets the backoff
WS_RETRY_AFTER_S = 15 * 60  # while on the poll fallback, re-probe WS this often
POLL_TIMEOUT_S = 35         # slightly above the relay's 25 s hold
FLAP_WINDOW_S = 600
FLAP_LIMIT = 6              # >6 reconnects in 10 minutes = flapping

# Relay close codes -> state_reason enum (mirrors the relay's protocol).
CLOSE_REASON_BY_CODE = {
    4001: 'auth_failed_signature',
    4002: 'auth_failed_clock_skew',
    4003: 'version_unsupported',
    4004: 'auth_failed_signature',  # nonce replay
    4009: 'revoked',
}


class RelayRevoked(Exception):
    """The relay closed us with 4009 — terminal until re-paired on ServerKit Cloud."""


class _HandshakeRefused(Exception):
    """WS handshake/hello failed with a classified state_reason."""


# ---------- pure helpers (unit-tested) ----------


def close_reason_for_code(code) -> str:
    """Relay close code -> state_reason; unknown codes are a dropped heartbeat."""
    return CLOSE_REASON_BY_CODE.get(code, 'heartbeat_timeout')


def backoff_delay(attempt: int, rand=random.uniform) -> float:
    """Jittered exponential backoff: 1 s doubling to a 60 s cap, ±25% jitter."""
    base = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** max(0, attempt)))
    return base * (1 + rand(-BACKOFF_JITTER, BACKOFF_JITTER))


def is_flapping(attempts_at, now: float = None,
                window: float = FLAP_WINDOW_S, limit: int = FLAP_LIMIT) -> bool:
    """True when more than `limit` reconnect attempts happened within `window`."""
    now = time.time() if now is None else now
    return sum(1 for t in attempts_at if now - t <= window) > limit


def relay_http_base(relay_url: str) -> str:
    """wss://host:port/v1/device -> https://host:port (ws -> http)."""
    parsed = urllib.parse.urlparse(relay_url)
    scheme = {'wss': 'https', 'ws': 'http'}.get(parsed.scheme, parsed.scheme)
    return urllib.parse.urlunparse((scheme, parsed.netloc, '', '', '', ''))


def poll_url_for(relay_url: str) -> str:
    """The relay's long-poll endpoint for a device WS URL."""
    return relay_http_base(relay_url) + '/v1/device/poll'


def build_hello(private_key, device_id: str, client_version: str) -> dict:
    """The signed first frame. sig covers the exact string `device_id|ts|nonce`."""
    ts = int(time.time())
    nonce = secrets.token_hex(16)
    sig = private_key.sign(f'{device_id}|{ts}|{nonce}'.encode()).hex()
    return {
        't': 'hello',
        'device_id': device_id,
        'ts': ts,
        'nonce': nonce,
        'sig': sig,
        'proto': PROTO_VERSION,
        'client_version': client_version,
    }


HELLO_HEADERS = {
    'device_id': 'X-ServerKit-Device',
    'ts': 'X-ServerKit-Ts',
    'nonce': 'X-ServerKit-Nonce',
    'sig': 'X-ServerKit-Sig',
    'proto': 'X-ServerKit-Proto',
    'client_version': 'X-ServerKit-Client-Version',
}


def hello_headers(hello: dict) -> dict:
    """The same hello carried in X-ServerKit-* headers for the poll fallback."""
    return {header: str(hello[field]) for field, header in HELLO_HEADERS.items()}


# ---------- runtime state file ----------


def state_file_path() -> str:
    return os.path.join(paths.SERVERKIT_CONFIG_DIR, STATE_FILENAME)


def _read_state_file() -> dict:
    path = state_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning('Could not read %s: %s', path, exc)
        return {}


def _write_state_file(state: str, reason: str = None, transport: str = None,
                      relay_instance: str = None, last_connected_at: str = None):
    """Persist a state transition, preserving fields not being overwritten."""
    saved = _read_state_file()
    saved.update({
        'state': state,
        'state_reason': reason,
        'transport': transport,
        'relay_instance': relay_instance if relay_instance is not None
        else saved.get('relay_instance'),
        'last_connected_at': last_connected_at or saved.get('last_connected_at'),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    })
    path = state_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(saved, f, indent=2)
        f.write('\n')


def _classify_ws_failure(exc) -> str:
    """Map a transport exception to a state_reason (pure; unit-tested)."""
    import ssl

    from websockets.exceptions import ConnectionClosed, InvalidHandshake

    if isinstance(exc, ConnectionClosed):
        code = exc.rcvd.code if exc.rcvd else None
        return close_reason_for_code(code)
    if isinstance(exc, InvalidHandshake):
        # HTTP 4xx/5xx or a non-101 answer on the upgrade: a proxy breaking WS.
        return 'relay_unreachable'
    if isinstance(exc, ssl.SSLError):
        return 'tls_error'
    if isinstance(exc, socket.gaierror):
        return 'dns_error'
    # connect refused/reset, timeouts, anything else network-shaped.
    return 'relay_unreachable'


def _relay_config() -> dict:
    """What the transport needs from connect.json + the device key.

    Returns None when the panel is not paired (anymore) or the key is gone —
    the client loop treats that as "exit", not "retry".
    """
    data = _read_connect_file()
    if not data.get('device_id') or not data.get('relay_url'):
        return None
    key_path = data.get(KEY_PATH_FIELD) or connect_keys.default_key_path()
    try:
        private_key, _pub, _fpr = connect_keys.load_keypair(key_path)
    except Exception as exc:
        logger.warning('Connect relay: cannot load device key %s: %s', key_path, exc)
        return None
    return {
        'device_id': data['device_id'],
        'relay_url': data['relay_url'],
        'private_key': private_key,
        'key_path': key_path,
    }


# ---------- the client ----------


class RelayClient:
    """Holds one outbound connection to the ServerKit relay.

    WebSocket first (signed hello, 20 s pings); when the upgrade smells like
    a proxy block (non-101 answer, timeout) the client falls back to the
    long-poll loop and reports `degraded`, re-probing WS every
    WS_RETRY_AFTER_S. All state transitions are persisted to
    connect-state.json so the CLI/API read them without this thread.
    """

    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.transport = None
        self.relay_instance = None
        self.last_error = None
        self._thread = None
        self._stop = threading.Event()
        self._ws = None
        self._attempts_at = collections.deque()
        self._flap_logged = False
        self._last_written = None  # (state, reason, transport) transition dedup

    # -- lifecycle -----------------------------------------------------

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='connect-relay')
        self._thread.start()
        logger.info('Connect relay client started')

    def stop(self):
        self.running = False
        self._stop.set()
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        # A terminal 'revoked' survives a stop: re-pairing on ServerKit Cloud, not a
        # local restart, is what clears it.
        if _read_state_file().get('state') != 'revoked':
            self._set_state('paired_offline', 'client_stopped', transport=None)

    # -- state persistence ---------------------------------------------

    def _set_state(self, state, reason, transport=None):
        key = (state, reason, transport)
        if key == self._last_written:
            return
        self._last_written = key
        connected = state in ('online', 'degraded')
        _write_state_file(
            state, reason, transport=transport, relay_instance=self.relay_instance,
            last_connected_at=datetime.now(timezone.utc).isoformat()
            if connected else None)

    def _sleep(self, seconds):
        self._stop.wait(max(0.0, seconds))

    # -- main loop ------------------------------------------------------

    def _run(self):
        attempt = 0
        ws_blocked_until = 0.0
        while self.running:
            cfg = _relay_config()
            if cfg is None:
                logger.info('Connect relay: not paired (connect.json/key gone); exiting')
                return

            if time.monotonic() < ws_blocked_until:
                if self._poll_session(cfg, ws_blocked_until) == 'stopped':
                    return
                ws_blocked_until = 0.0  # time to re-probe WS
                continue

            started = time.monotonic()
            outcome = self._ws_session(cfg)
            if outcome == 'stopped':
                return
            kind, _, reason = outcome.partition(':')

            if kind == 'revoked':
                self._set_state('revoked', 'revoked', transport=None)
                logger.warning('Connect relay: device revoked on ServerKit Cloud; stopping')
                return

            if time.monotonic() - started >= STABLE_AFTER_S:
                attempt = 0
            else:
                attempt += 1
                self._note_attempt()

            if kind == 'refused' and reason == 'relay_unreachable':
                # Proxy-blocked or unanswerable upgrade: limited mode.
                ws_blocked_until = time.monotonic() + WS_RETRY_AFTER_S
                self._set_state('degraded', 'relay_unreachable', transport='poll')
                continue

            self._set_state('paired_offline', reason, transport=None)
            self._sleep(backoff_delay(attempt))

    def _note_attempt(self):
        now = time.time()
        self._attempts_at.append(now)
        while self._attempts_at and now - self._attempts_at[0] > FLAP_WINDOW_S:
            self._attempts_at.popleft()
        flapping = is_flapping(self._attempts_at, now=now)
        if flapping and not self._flap_logged:
            self._flap_logged = True
            logger.warning(
                'Connect relay flapping: %d reconnects in the last %d s',
                len(self._attempts_at), FLAP_WINDOW_S)
        elif not flapping:
            self._flap_logged = False

    # -- websocket ------------------------------------------------------

    def _ws_session(self, cfg) -> str:
        """One WS connection: handshake, hello, heartbeat until drop.

        Returns 'stopped', 'revoked', 'refused:<reason>' (never got ready —
        auth/handshake failure) or 'drop:<reason>' (was ready, then lost).
        """
        try:
            ws = self._ws_connect(cfg)
        except RelayRevoked:
            return 'revoked'
        except _HandshakeRefused as exc:
            return f'refused:{exc}'
        except Exception as exc:
            return f'refused:{_classify_ws_failure(exc)}'

        self._ws = ws
        try:
            self.transport = 'ws'
            self._set_state('online', None, transport='ws')
            logger.info('Connect relay: online via ws (instance %s)',
                        self.relay_instance)
            while self.running:
                try:
                    raw = ws.recv(timeout=PING_INTERVAL_S)
                except TimeoutError:
                    ws.send('{"t":"ping"}')
                    continue
                self._handle_frame(ws, raw)
            return 'stopped'
        except Exception as exc:
            from websockets.exceptions import ConnectionClosed
            if isinstance(exc, ConnectionClosed):
                code = exc.rcvd.code if exc.rcvd else None
                if code == 4009:
                    return 'revoked'
                self.last_error = f'connection closed (code {code})'
                return f'drop:{close_reason_for_code(code)}'
            self.last_error = str(exc)
            return f'drop:{_classify_ws_failure(exc)}'
        finally:
            self._ws = None
            try:
                ws.close()
            except Exception:
                pass

    def _ws_connect(self, cfg):
        """Handshake + signed hello + wait for `ready` (10 s, relay-enforced)."""
        from app.utils.version import get_panel_version
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect as ws_connect

        ws = ws_connect(
            cfg['relay_url'],
            open_timeout=HELLO_TIMEOUT_S,
            close_timeout=5,
            ping_interval=None,  # heartbeats are app-level {"t":"ping"} frames
            max_size=MAX_FRAME_BYTES,
        )
        try:
            hello = build_hello(cfg['private_key'], cfg['device_id'],
                                get_panel_version())
            ws.send(json.dumps(hello))
            frame = json.loads(ws.recv(timeout=HELLO_TIMEOUT_S))
            if frame.get('t') != 'ready':
                raise _HandshakeRefused('relay_unreachable')
            self.relay_instance = frame.get('instance')
            return ws
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else None
            if code == 4009:
                raise RelayRevoked()
            raise _HandshakeRefused(close_reason_for_code(code))
        except Exception:
            try:
                ws.close()
            except Exception:
                pass
            raise

    def _handle_frame(self, ws, raw):
        try:
            frame = json.loads(raw)
        except ValueError:
            return
        if frame.get('t') == 'open':
            # M2 has no streams yet: refuse honestly (mirrors the relay).
            ws.send(json.dumps({
                's': frame.get('s'),
                't': 'close',
                'reason': 'unsupported',
                'detail': 'streams arrive with the next Connect release',
            }))

    # -- long-poll fallback ----------------------------------------------

    def _poll_session(self, cfg, ws_retry_at) -> str:
        """Long-poll loop ('limited mode'): each held GET is the heartbeat.

        Returns 'stopped', 'revoked', or 'retry_ws' when it's time to try the
        WebSocket again.
        """
        self.transport = 'poll'
        self._set_state('degraded', 'relay_unreachable', transport='poll')
        logger.info('Connect relay: using long-poll fallback (degraded)')
        fail_attempt = 0
        while self.running:
            if time.monotonic() >= ws_retry_at:
                return 'retry_ws'
            try:
                self._poll_once(cfg)
                fail_attempt = 0
            except RelayRevoked:
                return 'revoked'
            except Exception as exc:
                fail_attempt += 1
                self.last_error = str(exc)
                logger.warning('Connect relay poll failed: %s', exc)
                self._sleep(min(30.0, backoff_delay(fail_attempt)))
        return 'stopped'

    def _poll_once(self, cfg):
        from app.utils.version import get_panel_version

        hello = build_hello(cfg['private_key'], cfg['device_id'],
                            get_panel_version())
        resp = requests.get(
            poll_url_for(cfg['relay_url']),
            headers=hello_headers(hello),
            timeout=POLL_TIMEOUT_S,
        )
        if resp.status_code == 200:
            return
        detail = _error_detail(resp)
        if resp.status_code == 403 and detail == 'revoked':
            raise RelayRevoked()
        raise ConnectError(f'poll failed ({resp.status_code}): {detail}')


# ---------- singleton management (mirrors linked_panel_agent) ----------

_relay_client = None


def get_client():
    return _relay_client


def start_relay_client(app=None):
    global _relay_client
    if _relay_client is not None:
        return _relay_client
    client = RelayClient(app)
    client.start()
    _relay_client = client
    return client


def stop_relay_client():
    global _relay_client
    if _relay_client is not None:
        _relay_client.stop()
        _relay_client = None


def start_client_if_paired(app):
    """App-startup hook: resume the relay connection when this panel is paired."""
    try:
        if app.config.get('ENV') == 'testing' or app.config.get('TESTING'):
            return None
        if not _read_connect_file().get('device_id'):
            return None
        return start_relay_client(app)
    except Exception as exc:  # never block boot on the relay
        logger.warning('Could not start connect relay client: %s', exc)
        return None


# ==================== Doctor ====================

# Hard checks fail the doctor run (exit 1); soft ones are warnings with a
# working fallback. (name, ok, hard, copy-on-failure, note-on-pass)


def _doctor_check(name, ok, hard, fail_copy, note=None):
    return {
        'name': name,
        'ok': bool(ok),
        'hard': bool(hard),
        'error': None if ok else fail_copy,
        'note': note if ok else None,
    }


def _key_file_ok(key_path: str):
    if not os.path.exists(key_path):
        return False
    if os.name != 'nt':
        import stat
        mode = stat.S_IMODE(os.stat(key_path).st_mode)
        return mode & 0o077 == 0
    return True


def run_doctor() -> list:
    """The connect check table: pairing, key, DNS, TCP, TLS, clock, panel, WS."""
    data = _read_connect_file()
    relay_url = data.get('relay_url') or DEFAULT_RELAY_URL
    parsed = urllib.parse.urlparse(relay_url)
    host = parsed.hostname or ''
    port = parsed.port or (443 if parsed.scheme == 'wss' else 80)
    use_tls = parsed.scheme == 'wss'

    checks = []

    # Pairing state (informational: doctor is also useful pre-pair).
    paired = bool(data.get('device_id'))
    checks.append(_doctor_check(
        'Paired with ServerKit Cloud', paired, hard=False,
        fail_copy='Not paired yet. Run `serverkit connect` first.',
        note=f'device {data.get("device_id")}' if paired else None))

    # Device key present and mode 0600.
    key_path = data.get(KEY_PATH_FIELD) or connect_keys.default_key_path()
    checks.append(_doctor_check(
        'Device key', _key_file_ok(key_path), hard=True,
        fail_copy=f'Device key missing or readable by others: {key_path}.',
        note=key_path))

    # DNS resolution of the relay host.
    try:
        socket.getaddrinfo(host, port)
        dns_ok = True
        checks.append(_doctor_check(f'DNS {host}', True, hard=True,
                                    fail_copy=None, note=host))
    except socket.gaierror:
        dns_ok = False
        checks.append(_doctor_check(
            f'DNS {host}', False, hard=True,
            fail_copy=f'Cannot resolve {host}. Check DNS or outbound filtering.'))

    # TCP egress to the relay port (443 for wss).
    if dns_ok:
        try:
            with socket.create_connection((host, port), timeout=5):
                pass
            checks.append(_doctor_check(f'TCP {host}:{port}', True, hard=True,
                                        fail_copy=None))
        except OSError:
            checks.append(_doctor_check(
                f'TCP {host}:{port}', False, hard=True,
                fail_copy='Outbound HTTPS to the relay is blocked.'))
    else:
        checks.append(_doctor_check(f'TCP {host}:{port}', False, hard=True,
                                    fail_copy='Skipped: DNS failed.'))

    # TLS chain (plain ws:// relays have none to check).
    if not use_tls:
        checks.append(_doctor_check(f'TLS {host}', True, hard=True,
                                    fail_copy=None,
                                    note='not applicable (plain ws:// relay)'))
    elif dns_ok:
        import ssl
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=host):
                    pass
            checks.append(_doctor_check(f'TLS {host}', True, hard=True,
                                        fail_copy=None))
        except Exception as exc:
            checks.append(_doctor_check(
                f'TLS {host}', False, hard=True,
                fail_copy=f'TLS to the relay failed: {exc}. '
                          'Corporate proxies that inspect TLS are not supported.'))
    else:
        checks.append(_doctor_check(f'TLS {host}', False, hard=True,
                                    fail_copy='Skipped: DNS failed.'))

    # Clock skew: the relay/ServerKit Cloud Date header vs local time (limit 60 s).
    if dns_ok:
        import email.utils
        try:
            resp = requests.get(relay_http_base(relay_url) + '/', timeout=10)
            remote = email.utils.parsedate_to_datetime(resp.headers['Date'])
            skew = abs(time.time() - remote.timestamp())
            checks.append(_doctor_check(
                'Clock skew', skew <= 60, hard=True,
                fail_copy=f'System clock is {int(skew)}s off. Enable NTP; the '
                          'relay rejects signatures more than 60 s off.',
                note=f'{skew:.1f}s off UTC'))
        except Exception as exc:
            checks.append(_doctor_check(
                'Clock skew', False, hard=True,
                fail_copy=f'Could not read the relay clock: {exc}.'))
    else:
        checks.append(_doctor_check('Clock skew', False, hard=True,
                                    fail_copy='Skipped: DNS failed.'))

    # Loopback panel reachable (the relay will proxy browser traffic to it).
    from app.services.cli_api_client import resolve_port
    panel_port = resolve_port()
    try:
        with socket.create_connection(('127.0.0.1', panel_port), timeout=3):
            pass
        checks.append(_doctor_check('Panel loopback', True, hard=True,
                                    fail_copy=None,
                                    note=f'127.0.0.1:{panel_port}'))
    except OSError:
        checks.append(_doctor_check(
            'Panel loopback', False, hard=True,
            fail_copy=f'Panel not reachable at 127.0.0.1:{panel_port}.'))

    # WS upgrade attempt (soft: the long-poll fallback keeps limited mode).
    if dns_ok:
        try:
            from websockets.sync.client import connect as ws_connect
            ws = ws_connect(relay_url, open_timeout=10, close_timeout=2,
                            ping_interval=None)
            try:
                ws.close()
            finally:
                pass
            checks.append(_doctor_check('WebSocket upgrade', True, hard=False,
                                        fail_copy=None))
        except Exception:
            checks.append(_doctor_check(
                'WebSocket upgrade', False, hard=False,
                fail_copy='WebSocket upgrade refused; will use limited mode.'))
    else:
        checks.append(_doctor_check('WebSocket upgrade', False, hard=False,
                                    fail_copy='Skipped: DNS failed.'))

    return checks


def doctor_ok(checks) -> bool:
    """True when no HARD check failed (soft checks are warnings)."""
    return not any(c['hard'] and not c['ok'] for c in checks)
