"""Extension permission model + capability gate (#25).

A manifest's declared ``permissions`` become enforceable capability checks. A
plugin calls ``require(slug, capability)`` (or the SDK re-export
``require_permission``) before doing something privileged; if the plugin did not
declare that permission, it raises ``PermissionDenied``.

This is **in-process, declaration-based** enforcement. Combined with install-time
consent (the install dialog surfaces requested permissions from the manifest) and
the curated registry, it's the accepted risk posture (decision D6). It does NOT
sandbox a plugin that reaches for a raw host import without going through the gate
— true out-of-process isolation is deliberately out of scope (plan #42). The gate
makes honest plugins verifiable and gives the host a single choke point to tighten
later.
"""
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# Canonical host capabilities a manifest may request. Agent-command permissions
# use the namespaced form ``agent.command:<action>`` and are matched verbatim.
KNOWN_PERMISSIONS = {'docker', 'filesystem', 'shell', 'network', 'db'}

# Which declared permissions the panel can actually *observe* being used.
#
# This distinction is the whole honesty story (D2), so it is data rather than
# prose. A permission is observable only when every use of the capability has
# to pass through a gate this module owns. Today exactly one does:
# ``agent.command:<action>``, gated in ``plugins_sdk/agents_sdk.py`` — the SDK
# is the only way to run a command on an agent.
#
# The five KNOWN_PERMISSIONS are NOT observable. The SDK exposes no shell,
# docker, filesystem or network helper at all, and ``db`` is handed out as raw
# SQLAlchemy, so an extension that wants any of them imports the host module
# directly and no in-process gate ever sees it. Declaring them is a consent
# signal to the operator, not an enforced boundary — and the UI must not imply
# otherwise by showing "never used" for something it simply cannot watch.
OBSERVABLE_PREFIXES = ('agent.command:',)


def is_observable(permission):
    """True when a use of *permission* necessarily passes through our gate."""
    return str(permission or '').startswith(OBSERVABLE_PREFIXES)


class PermissionDenied(PermissionError):
    """Raised when a plugin uses a capability it did not declare."""


# ---------------------------------------------------------------------------
# Usage observation (plan 55 task 7)
#
# In-memory and per-process on purpose: this answers "what has this extension
# actually done since the panel started", which is a live-process question. It
# is deliberately not persisted — a durable claim would outlive the evidence and
# start reading like an audit trail, which this is not.
# ---------------------------------------------------------------------------
_observations = {}
_observations_lock = threading.Lock()


def record_use(slug, capability, allowed=True):
    """Note that *slug* reached for *capability*; first use per process is logged.

    Called from the gate itself, so both the allowed and the denied paths are
    recorded — a denial is the more interesting of the two.
    """
    slug = str(slug or '')
    capability = str(capability or '')
    if not slug or not capability:
        return
    key = (slug, capability)
    with _observations_lock:
        entry = _observations.get(key)
        first = entry is None
        if first:
            entry = {'slug': slug, 'permission': capability, 'uses': 0,
                     'denied': 0, 'first_used_at': datetime.utcnow().isoformat(),
                     'last_used_at': None}
            _observations[key] = entry
        entry['uses'] += 1
        if not allowed:
            entry['denied'] += 1
        entry['last_used_at'] = datetime.utcnow().isoformat()
    if first:
        logger.info('extension=%s permission=%s first-use allowed=%s',
                    slug, capability, allowed)


def observed_permissions(slug):
    """Everything *slug* has reached for this process, newest field values."""
    with _observations_lock:
        return [dict(v) for k, v in _observations.items() if k[0] == str(slug or '')]


def reset_observations():
    """Drop all recorded usage (tests)."""
    with _observations_lock:
        _observations.clear()


def usage_report(slug):
    """Declared vs observed for one extension, honest about what it can see.

    Every declared permission gets a row. ``observable`` says whether absence
    of use means anything at all: for a declaration-only capability it does
    not, and the row says so instead of implying the extension is over-asking.
    Anything observed but never declared is reported too — it cannot happen
    through the gate, which refuses it, but a denial is exactly what an
    operator wants to see.
    """
    declared = sorted(declared_permissions(slug))
    observed = {o['permission']: o for o in observed_permissions(slug)}

    rows = []
    for perm in declared:
        seen = observed.get(perm)
        rows.append({
            'permission': perm,
            'declared': True,
            'observable': is_observable(perm),
            'used': bool(seen and seen['uses'] > seen['denied']),
            'uses': seen['uses'] if seen else 0,
            'first_used_at': seen['first_used_at'] if seen else None,
            'last_used_at': seen['last_used_at'] if seen else None,
        })
    for perm, seen in sorted(observed.items()):
        if perm in declared:
            continue
        rows.append({
            'permission': perm,
            'declared': False,
            'observable': is_observable(perm),
            'used': False,          # refused at the gate — it never happened
            'uses': seen['uses'],
            'denied': seen['denied'],
            'first_used_at': seen['first_used_at'],
            'last_used_at': seen['last_used_at'],
        })

    observable_declared = [r for r in rows if r['declared'] and r['observable']]
    return {
        'slug': slug,
        'permissions': rows,
        # Only meaningful for observable rows; stated separately so the UI does
        # not have to re-derive the caveat.
        'unused_observable': sorted(r['permission'] for r in observable_declared
                                    if not r['used']),
        'undeclared_attempts': sorted(r['permission'] for r in rows
                                      if not r['declared']),
        'observable_count': len(observable_declared),
        'declaration_only_count': len([r for r in rows
                                       if r['declared'] and not r['observable']]),
    }


def declared_permissions(slug):
    """The set of permissions the installed plugin `slug` declared (empty if the
    plugin is unknown)."""
    from app.models.plugin import InstalledPlugin
    p = InstalledPlugin.query.filter_by(slug=slug).first()
    if not p:
        return set()
    perms = (p.manifest or {}).get('permissions') or []
    if not isinstance(perms, list):
        return set()
    return {str(x) for x in perms}


def has(slug, capability):
    """True if plugin `slug` declared `capability`."""
    return capability in declared_permissions(slug)


def require(slug, capability):
    """Assert plugin `slug` declared `capability`, else raise PermissionDenied.

    Every call through this gate is recorded — including the refusals, which
    are the ones worth surfacing — so the extension detail page can show what a
    plugin has actually reached for rather than only what it claimed.
    """
    allowed = has(slug, capability)
    record_use(slug, capability, allowed=allowed)
    if not allowed:
        raise PermissionDenied(
            f"Plugin '{slug}' has not declared the '{capability}' permission. "
            f"Add it to the plugin.json \"permissions\" array."
        )
    return True


def unknown_permissions(permissions):
    """Return declared permissions that aren't recognized host capabilities
    (agent-command permissions are always accepted). Useful for review/consent UI."""
    out = []
    for p in permissions or []:
        p = str(p)
        if p in KNOWN_PERMISSIONS or p.startswith('agent.command:'):
            continue
        out.append(p)
    return out
