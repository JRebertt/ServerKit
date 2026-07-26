"""Registry of doctor checks contributed outside the core.

``DoctorService.run`` is a fixed sequence of core producers, so an extension had
nowhere to say "the thing I manage is unhealthy, and here is what to do about
it" — the panel's own diagnostics page simply didn't know it existed. A
registered provider is swept with the rest, and the doctor panel renders
whatever it receives (its status pill, repair button and diff toggle all key off
fields, not off a known list of check ids), so a contributed check needs no
frontend work.

Two things this registry does that core's own producers do not:

* **Isolation.** ``run()`` calls its producers bare — each one carries its own
  try/except by hand, and anything that escapes 500s the whole sweep. A
  third-party provider gets a real boundary here: raise, and you become one
  ``warn`` check attributed to your plugin, with the sweep unharmed.
* **A time budget.** Nothing bounds a core producer today, so a hung one hangs
  ``POST /doctor/run`` for whoever asked. A provider that overruns is reported
  as a ``warn`` and the sweep moves on.

Providers run in a worker thread with the app context carried across, so they
can use the database as normal.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

logger = logging.getLogger(__name__)

# namespace -> {'provider': fn, 'repair': fn|None, 'timeout': float}
_PROVIDERS = {}

#: Seconds one provider may take before the sweep gives up on it.
DEFAULT_TIMEOUT = 10.0

#: The statuses the panel knows how to render. Anything else is reported as a
#: warning rather than passed through as an unrenderable pill.
VALID_STATUSES = ('ok', 'warn', 'fail')

# Prefixes core owns. A contributed check is prefixed with its own namespace, so
# these are unreachable by construction — the guard is here to catch a
# namespace that would collide before it can shadow a core check.
CORE_NAMESPACES = ('drift', 'service', 'dns', 'certs', 'disk', 'db',
                   'setup', 'backup_drill_stale', 'backup_unverified')


def register(namespace: str, provider, repair=None, timeout: float = DEFAULT_TIMEOUT,
             replace: bool = False):
    """Register ``provider() -> check | [check, ...]`` under *namespace*.

    Each check is ``{'key', 'title', 'status', 'detail'}`` with optional
    ``repairable``/``repair_ref``; keys are prefixed with the namespace so they
    cannot collide with another plugin's or with core's.

    Pass *repair* — ``fn(ref) -> {'success': bool, ...}`` — to make checks
    repairable. Without it, a check claiming ``repairable`` is demoted: the
    panel would otherwise show a button that dispatches nowhere.
    """
    if not namespace or not callable(provider):
        raise ValueError('a doctor check needs a namespace and a callable provider')
    if namespace in CORE_NAMESPACES:
        raise ValueError(f'"{namespace}" is a core doctor namespace and cannot be overridden')
    if repair is not None and not callable(repair):
        raise ValueError('a doctor repair must be callable')
    if namespace in _PROVIDERS and not replace:
        raise ValueError(f'doctor checks for "{namespace}" are already registered')
    _PROVIDERS[namespace] = {'provider': provider, 'repair': repair,
                             'timeout': float(timeout)}
    logger.info('Registered doctor checks: %s', namespace)
    return provider


def get(namespace: str):
    """The registration for *namespace*, or None."""
    return _PROVIDERS.get(namespace)


def namespaces():
    """All registered namespaces."""
    return sorted(_PROVIDERS)


def clear():
    """Drop every registration. Tests only."""
    _PROVIDERS.clear()


def collect():
    """Run every registered provider and return normalised checks."""
    checks = []
    for namespace in sorted(_PROVIDERS):
        checks.extend(_collect_one(namespace, _PROVIDERS[namespace]))
    return checks


def repair(namespace: str, ref):
    """Dispatch a repair to *namespace*'s handler."""
    entry = _PROVIDERS.get(namespace)
    if not entry or not entry.get('repair'):
        return {'success': False,
                'error': f'No doctor repair registered for "{namespace}"'}
    try:
        result = entry['repair'](ref) or {}
    except Exception as exc:  # noqa: BLE001 — third-party code
        logger.exception('doctor repair for %s raised', namespace)
        return {'success': False, 'error': str(exc)}
    if not isinstance(result, dict):
        return {'success': bool(result)}
    result.setdefault('success', False)
    return result


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _collect_one(namespace, entry):
    try:
        raw = _call_with_timeout(entry['provider'], entry['timeout'])
    except FutureTimeout:
        # The thread may still be running — we cannot kill it, but the sweep
        # must not wait on it. Say so rather than reporting a false 'ok'.
        logger.warning('doctor checks for %s exceeded %.1fs', namespace, entry['timeout'])
        return [_warn(namespace, 'timeout',
                      f'{namespace} checks timed out',
                      f'The check did not finish within {entry["timeout"]:.1f}s '
                      'and was abandoned.')]
    except Exception as exc:  # noqa: BLE001 — third-party code
        logger.exception('doctor checks for %s raised', namespace)
        return [_warn(namespace, 'error', f'{namespace} checks failed',
                      f'The check raised: {exc}')]

    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []

    checks = []
    for item in raw:
        cleaned = _clean(namespace, item, repairable=bool(entry.get('repair')))
        if cleaned:
            checks.append(cleaned)
    return checks


def _call_with_timeout(provider, timeout):
    """Run *provider* under a wall-clock cap, carrying the app context over."""
    try:
        from flask import current_app
        app = current_app._get_current_object()
    except Exception:
        app = None

    def _invoke():
        if app is None:
            return provider()
        with app.app_context():
            return provider()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(_invoke).result(timeout=timeout)
    finally:
        # wait=False, deliberately: an overrunning provider is still running and
        # cannot be killed from here, but the sweep must not block on it —
        # which is what the executor's own context manager would do on exit,
        # making the timeout above worthless.
        pool.shutdown(wait=False)


def _clean(namespace, item, repairable):
    """Normalise one contributed check, or None if it isn't usable."""
    if not isinstance(item, dict):
        return None
    key = str(item.get('key') or '').strip()
    title = str(item.get('title') or '').strip()
    if not key or not title:
        return None

    status = item.get('status')
    if status not in VALID_STATUSES:
        # An unrenderable status would show as a blank pill; a plugin bug
        # should be visible, not invisible.
        status = 'warn'

    check = {
        'key': key if key.startswith(f'{namespace}.') else f'{namespace}.{key}',
        'title': title,
        'detail': str(item.get('detail') or ''),
        'status': status,
        'repairable': False,
        'repair_ref': None,
        'plugin': namespace,
    }

    if item.get('repairable') and item.get('repair_ref') is not None:
        if repairable:
            # Wrapped, so DoctorService.repair can route it back here without
            # letting a plugin ref impersonate a core repair kind.
            check['repairable'] = True
            check['repair_ref'] = {'kind': 'extension', 'namespace': namespace,
                                   'ref': item['repair_ref']}
        else:
            logger.warning('doctor: %s marked a check repairable but registered '
                           'no repair handler', namespace)
    return check


def _warn(namespace, suffix, title, detail):
    return {'key': f'{namespace}.{suffix}', 'title': title, 'status': 'warn',
            'detail': detail, 'repairable': False, 'repair_ref': None,
            'plugin': namespace}
