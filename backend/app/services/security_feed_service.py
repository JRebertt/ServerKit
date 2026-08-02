"""Security-advisory feed check.

Once a day (builtin job `security-feed`) the panel pulls the normalized GHSA
feed from https://serverkit.ai/api/security-feed.json (a cached proxy of the
repo's published GitHub Security Advisories) and:

1. notifies admins when the RUNNING version falls inside an advisory's
   affected range ("you are vulnerable — update"), once per advisory;
2. after an upgrade crosses a fix boundary, fires a one-time post-fix
   reminder when the advisory declares follow-up actions (e.g. rotating
   JWT_SECRET_KEY after GHSA-rm3m-9mvw-68fh).

Dedupe + last-good feed + the previously-seen version live in SystemSettings,
so restarts never re-notify. Outbound failures are silent: a panel with no
internet access simply never notifies. Set the `security_feed.enabled`
setting to false to opt out of the outbound call entirely.
"""
import json
import logging
import urllib.request

from app import db
from app.models.system_settings import SystemSettings
from app.utils.version import compare_versions, get_panel_version

logger = logging.getLogger(__name__)

FEED_URL = 'https://serverkit.ai/api/security-feed.json'
FEED_TIMEOUT = 8  # seconds

ENABLED_KEY = 'security_feed.enabled'
NOTIFIED_KEY = 'security_feed.notified'      # json list of dedupe keys
LAST_VERSION_KEY = 'security_feed.last_version'
LAST_GOOD_KEY = 'security_feed.last_good'    # json {"advisories": [...]}

_OPERATORS = {
    '<': lambda c: c < 0,
    '<=': lambda c: c <= 0,
    '>': lambda c: c > 0,
    '>=': lambda c: c >= 0,
    '=': lambda c: c == 0,
    '==': lambda c: c == 0,
}


def version_in_range(version, range_str):
    """Evaluate a GHSA-style version range (e.g. '< 1.7.68', '>= 1.2.0, < 1.5')
    against `version`. Comma-separated clauses AND together. An empty or
    unparseable range matches nothing (fail closed — never cry wolf)."""
    if not version or not range_str:
        return False
    for clause in range_str.split(','):
        clause = clause.strip()
        if not clause:
            continue
        op, _, bound = clause.partition(' ')
        pred = _OPERATORS.get(op.strip())
        bound = bound.strip()
        if pred is None or not bound:
            return False
        if not pred(compare_versions(version, bound)):
            return False
    return True


def is_enabled():
    """Opt-out switch for the outbound feed call. Default on."""
    return SystemSettings.get(ENABLED_KEY, True) not in (False, 'false', '0')


def fetch_feed():
    """GET the advisory feed; fall back to the last-good copy on any failure.

    Returns a list of advisory dicts (possibly empty). Never raises."""
    try:
        req = urllib.request.Request(
            FEED_URL, headers={'User-Agent': 'ServerKit-SecurityFeed/1.0'})
        with urllib.request.urlopen(req, timeout=FEED_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        advisories = data.get('advisories') or []
        SystemSettings.set(LAST_GOOD_KEY, {'advisories': advisories}, 'json')
        db.session.commit()
        return advisories
    except Exception as e:
        logger.debug(f'Security feed fetch failed (using last-good): {e}')
        cached = SystemSettings.get(LAST_GOOD_KEY) or {}
        return cached.get('advisories') or []


def _notify(alert_type, message):
    from app.notifications.service import NotificationBusService
    NotificationBusService.send(
        'security.alert',
        to='admins',
        data={'alert_type': alert_type, 'message': message},
        action_path='/settings/system',
        action_label='Review update',
    )


def check_security_feed(current_version=None):
    """Daily job entry point. Returns a small result dict for the job log."""
    if not is_enabled():
        return {'skipped': 'disabled'}

    current = current_version or get_panel_version()
    advisories = fetch_feed()

    notified = set(SystemSettings.get(NOTIFIED_KEY, []) or [])
    alerts = 0

    # 1) Running version inside an affected range -> "update now" alert.
    for adv in advisories:
        ghsa = adv.get('ghsa')
        affected = adv.get('affected')
        if not ghsa or not affected:
            continue
        if f'{ghsa}:affected' in notified:
            continue
        if not version_in_range(current, affected):
            continue
        fixed = adv.get('fixed_in') or 'a newer release'
        _notify(
            f'Known vulnerability {ghsa}',
            f'{adv.get("summary", "Security advisory")} — this panel runs '
            f'{current}, which is in the affected range ({affected}). '
            f'Fixed in {fixed}. Update with: sudo serverkit update. '
            f'Details: {adv.get("url", "")}',
        )
        notified.add(f'{ghsa}:affected')
        alerts += 1

    # 2) Upgrade crossing: previously-seen version was affected, current is
    #    not -> one-time post-fix reminder (key rotation, etc.).
    previous = SystemSettings.get(LAST_VERSION_KEY)
    if previous and previous != current:
        for adv in advisories:
            ghsa = adv.get('ghsa')
            affected = adv.get('affected')
            post_fix = adv.get('post_fix_action')
            if not ghsa or not affected or not post_fix:
                continue
            if f'{ghsa}:postfix' in notified:
                continue
            if version_in_range(previous, affected) and not version_in_range(current, affected):
                _notify(
                    f'Post-update action required ({ghsa})',
                    f'This panel previously ran {previous}, which was affected '
                    f'by {ghsa} ({adv.get("summary", "security advisory")}). '
                    f'The update is installed — complete these follow-up steps: '
                    f'{post_fix}',
                )
                notified.add(f'{ghsa}:postfix')
                alerts += 1
    SystemSettings.set(LAST_VERSION_KEY, current)
    SystemSettings.set(NOTIFIED_KEY, sorted(notified), 'json')
    db.session.commit()

    return {'advisories': len(advisories), 'alerts': alerts}
