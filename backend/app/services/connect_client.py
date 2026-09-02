"""ServerKit Cloud connect pairing — panel side.

M1 scope is pairing ONLY: enroll with ServerKit Cloud, print the pairing code +
fingerprint, poll with an Ed25519 proof-of-possession until the user approves
in the browser, then write ``connect.json`` next to the panel config. No
WebSocket transport, no reconnect loop — those are later milestones.

ServerKit Cloud endpoints (no session auth on the panel side):
  POST /api/pair/enroll   -> enrollment_id, enrollment_secret (shown once), code
  POST /api/pair/poll     -> 202 pending / 200 claimed (signed proof-of-possession)
  POST /api/pair/rotate   -> new code + expires_at

The enrollment_secret is kept in memory for the pairing session only — it is
never written to disk or logged.
"""
import json
import logging
import os
import socket
import time
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
    """Connection state as the UI/CLI should show it (reads connect.json + key)."""
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
    state = 'paired_offline' if key_present else 'degraded'
    return {
        'state': state,
        # No transport yet in M1 — a paired panel has never been online.
        'state_reason': 'never_connected' if key_present else 'device_key_missing',
        'paired': True,
        'cloud_url': data.get('cloud_url') or resolve_cloud_url(),
        'device_id': data.get('device_id'),
        'org_slug': data.get('org_slug'),
        'name': data.get('name'),
        'relay_url': data.get('relay_url'),
        'scopes': data.get('scopes') or [],
        'fingerprint': data.get('fingerprint'),
        'fingerprint_grouped': connect_keys.format_fingerprint(data['fingerprint'])
        if data.get('fingerprint') else None,
        'paired_at': data.get('paired_at'),
        'key_present': key_present,
        'key_path': key_path,
    }


def disconnect(remove_key: bool = False) -> dict:
    """Forget the pairing locally. Does NOT revoke anything on ServerKit Cloud."""
    removed = []
    path = connect_file_path()
    if os.path.exists(path):
        os.unlink(path)
        removed.append(path)
    if remove_key:
        key_path = connect_keys.default_key_path()
        if os.path.exists(key_path):
            os.unlink(key_path)
            removed.append(key_path)
    return {'success': True, 'removed': removed, 'state': 'unpaired'}
