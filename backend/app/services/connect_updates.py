"""Keeping the ServerKit Cloud connect client current.

On every reconnect the client asks ServerKit Cloud what the current release is. The
answer is signed with ServerKit Cloud's Ed25519 key, and this module verifies it against
the JWKS the panel already trusts before believing a word of it: the artefact
lives on a CDN we do not control, and an unsigned feed would be a way to hand
a customer's server any version at all.

What happens when we are behind depends on what this install can do:

- an install the panel can update itself (the normal case) runs the panel's
  own update path, exactly as an operator pressing Update would;
- an install it cannot (Docker, non-root) records that and shows the
  operator what to run on the host. It is never guessed at.

Nothing here restarts anything on its own: the panel's updater owns that, and
the relay client reconnects when the process comes back.
"""
import json
import logging
import time

import requests

logger = logging.getLogger(__name__)

FEED_TIMEOUT_S = 10
# How often to ask, at most. A release is not urgent enough to poll harder.
CHECK_INTERVAL_S = 3600
COMPONENT = 'connect-client'


class UpdateCheck:
    """Remembers when it last asked and what it found."""

    def __init__(self):
        self.last_checked_at = 0.0
        self.available = None        # version string ServerKit Cloud published
        self.state = 'unknown'       # current | behind | updating | unsupported | error
        self.detail = None

    def to_dict(self) -> dict:
        return {
            'state': self.state,
            'available': self.available,
            'detail': self.detail,
            'last_checked_at': self.last_checked_at or None,
        }

    def due(self, now=None) -> bool:
        now = now if now is not None else time.monotonic()
        return now - self.last_checked_at >= CHECK_INTERVAL_S


# ==================== the signed feed ====================


def fetch_feed(cloud_url: str, component: str = COMPONENT, channel: str = 'stable') -> dict | None:
    try:
        res = requests.get(f'{cloud_url}/api/releases/{component}',
                           params={'channel': channel}, timeout=FEED_TIMEOUT_S)
        res.raise_for_status()
        return res.json()
    except Exception as exc:
        logger.debug('Connect updates: could not read the release feed: %s', exc)
        return None


def fetch_jwks(cloud_url: str) -> dict | None:
    try:
        res = requests.get(f'{cloud_url}/api/.well-known/jwks.json', timeout=FEED_TIMEOUT_S)
        res.raise_for_status()
        return res.json()
    except Exception as exc:
        logger.debug('Connect updates: could not read the JWKS: %s', exc)
        return None


def verify_feed(feed: dict, jwks: dict) -> dict | None:
    """Return the signed payload, or None if the signature does not hold.

    The signature covers the canonical JSON of the payload as ServerKit Cloud built it,
    so we rebuild exactly those bytes and compare rather than trusting the
    parsed object.
    """
    signature = (feed or {}).get('signature')
    if not signature or not jwks:
        return None
    try:
        import base64

        import jwt
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        header = jwt.get_unverified_header(signature)
        kid = header.get('kid')
        key = next((k for k in (jwks.get('keys') or []) if k.get('kid') == kid), None)
        if key is None or key.get('crv') != 'Ed25519':
            return None
        raw = base64.urlsafe_b64decode(key['x'] + '=' * (-len(key['x']) % 4))
        claims = jwt.decode(signature, Ed25519PublicKey.from_public_bytes(raw),
                            algorithms=['EdDSA'])
    except Exception as exc:
        logger.warning('Connect updates: release feed signature did not verify (%s)', exc)
        return None

    signed_body = claims.get('feed')
    if not signed_body:
        return None
    payload = {k: v for k, v in feed.items()
               if k in ('component', 'channel', 'current', 'generated_at')}
    rebuilt = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    if rebuilt != signed_body:
        logger.warning('Connect updates: the release feed does not match its signature')
        return None
    return payload


# ==================== deciding and acting ====================


def _version_tuple(value):
    import re
    return tuple(int(n) for n in re.findall(r'\d+', str(value or ''))[:4])


def is_behind(running: str, available: str) -> bool:
    if not available:
        return False
    if not running:
        return True
    return _version_tuple(running) < _version_tuple(available)


def check(cloud_url: str, running_version: str, state: UpdateCheck) -> UpdateCheck:
    """Ask, verify, and record. Does not act."""
    state.last_checked_at = time.monotonic()
    feed = fetch_feed(cloud_url)
    if feed is None:
        state.state = 'error'
        state.detail = 'Could not reach the release feed'
        return state
    payload = verify_feed(feed, fetch_jwks(cloud_url))
    if payload is None:
        state.state = 'error'
        state.detail = 'The release feed was not signed by ServerKit Cloud'
        return state
    current = payload.get('current') or {}
    state.available = current.get('version')
    if is_behind(running_version, state.available):
        state.state = 'behind'
        state.detail = f'{state.available} is available (running {running_version})'
    else:
        state.state = 'current'
        state.detail = None
    return state


def apply_if_behind(state: UpdateCheck) -> UpdateCheck:
    """Run the panel's own update path when we are behind and able.

    The connect client ships inside the panel, so updating it is updating the
    panel — the same code path an operator uses, with the same refusals.
    """
    if state.state != 'behind':
        return state
    try:
        from app.services import panel_update_service
    except Exception as exc:
        state.state = 'unsupported'
        state.detail = f'This install cannot update itself from here ({exc})'
        return state

    try:
        capability = panel_update_service.get_capability()
    except Exception as exc:
        state.state = 'error'
        state.detail = f'Could not check whether this install can update itself: {exc}'
        return state

    supported = capability.get('supported') if isinstance(capability, dict) else bool(capability)
    if not supported:
        reason = (capability.get('reason') if isinstance(capability, dict) else None) or 'unsupported install'
        state.state = 'unsupported'
        state.detail = (f'ServerKit Cloud has {state.available}, but this install cannot update '
                        f'itself ({reason}). Update it from the host and the connect client '
                        f'comes with it.')
        logger.info('Connect updates: %s', state.detail)
        return state

    logger.info('Connect updates: updating the panel to %s for the connect client', state.available)
    try:
        panel_update_service.start_update()
        state.state = 'updating'
        state.detail = f'Updating to {state.available}'
    except Exception as exc:
        state.state = 'error'
        state.detail = f'The update did not start: {exc}'
        logger.warning('Connect updates: %s', state.detail)
    return state


def check_and_apply(cloud_url: str, running_version: str, state: UpdateCheck) -> UpdateCheck:
    if not state.due():
        return state
    return apply_if_behind(check(cloud_url, running_version, state))
