"""Registry of backup target types contributed outside the core.

``BackupPolicyService`` dispatches on ``policy.target_type`` through four
hardcoded switches — resolve, execute, restore, and the validator that gates
every API route. An extension therefore could not say "here is a thing of mine
worth backing up", and had to hand-roll its own backups with no policy, no
schedule, no retention, no restore and no place in the Protection panel.

A registered kind inherits all of it: the policy row and its cron mirror, the
BackupRun history, retention (count/days, incremental-chain aware), offsite
copy, verification, the restore flow and the panel UI — which is already
generic over ``target_type`` and needs no frontend change.

A kind supplies:

``resolve(policy) -> dict``
    Describes the live target. Must include ``name``; ``target_type`` is filled
    in for you. Raise if the thing no longer exists.
``execute(policy, target, kind) -> (storage_path, size_bytes, meta)``
    Produces the artifact. ``kind`` is ``'full'`` or ``'incremental'``;
    contributed kinds are always asked for ``'full'`` unless they opt in.
``restore(policy, target, run, options)`` — optional
    Puts a run back. **Without it a restore is refused**, rather than falling
    through to core's application restore, which would unpack a plugin's
    archive over an app directory.
"""

import logging

logger = logging.getLogger(__name__)

# target_type -> {'resolve': fn, 'execute': fn, 'restore': fn|None,
#                 'label': str|None, 'restore_scopes': list|None,
#                 'source': str|None  # registrant extension slug (audit F5)
#                 }
_KINDS = {}


def core_kinds():
    """The target types core owns (imported lazily to avoid a model import)."""
    from app.models.backup_policy import VALID_TARGET_TYPES
    return VALID_TARGET_TYPES


def register(target_type: str, resolve, execute, restore=None, replace: bool = False,
             label: str = None, restore_scopes=None, source: str = None):
    """Register a backup target type.

    Namespace it after your plugin (``minecraft.world``); the bare words core
    uses are reserved. ('wordpress_site' is the WordPress extension's kind —
    it left the core set under plan 52 D4.)

    ``label`` / ``restore_scopes`` are optional UI metadata surfaced by
    ``GET /api/v1/backups/target-types`` so the Protection panel/restore
    drawer can render the kind without hardcoding its name client-side.

    ``source`` is the registrant extension's slug. It is what lets
    disable/uninstall tear down exactly that extension's kinds
    (:func:`unregister`, audit F1) — and it makes ``replace=True``
    defense-in-depth: a kind owned by a DIFFERENT registrant can never be
    shadowed (audit F5).
    """
    if not target_type:
        raise ValueError('a backup kind needs a target type')
    if not callable(resolve) or not callable(execute):
        raise ValueError('a backup kind needs callable resolve and execute functions')
    if restore is not None and not callable(restore):
        raise ValueError('a backup restore must be callable')
    if target_type in core_kinds():
        raise ValueError(f'"{target_type}" is a core backup target type and cannot be overridden')
    existing = _KINDS.get(target_type)
    if existing is not None:
        existing_source = existing.get('source')
        if replace and existing_source and source and existing_source != source:
            raise ValueError(
                f'backup kind "{target_type}" is registered by '
                f'"{existing_source}" and cannot be replaced by "{source}"')
        if not replace:
            raise ValueError(f'backup kind "{target_type}" is already registered')
    _KINDS[target_type] = {
        'resolve': resolve, 'execute': execute, 'restore': restore,
        'label': label, 'restore_scopes': list(restore_scopes) if restore_scopes else None,
        'source': source,
    }
    logger.info('Registered backup kind: %s', target_type)
    return _KINDS[target_type]


def unregister(source: str):
    """Drop every kind registered by ``source`` (disable/uninstall teardown,
    audit F1). Returns the number of kinds removed."""
    if not source:
        return 0
    doomed = [t for t, entry in _KINDS.items() if entry.get('source') == source]
    for t in doomed:
        del _KINDS[t]
    if doomed:
        logger.info('Unregistered %d backup kind(s) from %s', len(doomed), source)
    return len(doomed)


def get(target_type: str):
    """The registration for *target_type*, or None."""
    return _KINDS.get(target_type)


def kinds():
    """All registered non-core target types."""
    return sorted(_KINDS)


def catalog():
    """Registered kinds as UI-facing descriptors (newest API consumers).

    ``[{target_type, label, restore_scopes, supports_restore, source}]`` —
    merged with the core types by the ``/backups/target-types`` endpoint.
    """
    return [{
        'target_type': t,
        'label': (entry.get('label') or t),
        'restore_scopes': entry.get('restore_scopes'),
        'supports_restore': bool(entry.get('restore')),
        'source': 'extension',
    } for t, entry in sorted(_KINDS.items())]


def clear():
    """Drop every registration. Tests only."""
    _KINDS.clear()


def resolve(policy):
    """Resolve a contributed target, normalising what the plugin returns."""
    entry = _require(policy.target_type)
    target = entry['resolve'](policy)
    if not isinstance(target, dict):
        raise ValueError(
            f'backup kind "{policy.target_type}" resolve() must return a dict')
    target.setdefault('name', f'{policy.target_type}:{policy.target_id}')
    # Forced, not defaulted: every downstream branch keys off this, and a kind
    # that claimed to be 'application' would be restored as one.
    target['target_type'] = policy.target_type
    target.setdefault('root_path', None)
    target.setdefault('app', None)
    return target


def execute(policy, target, kind):
    """Run a contributed backup, normalising its return value."""
    entry = _require(policy.target_type)
    result = entry['execute'](policy, target, kind)
    try:
        storage_path, size, meta = result
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'backup kind "{policy.target_type}" execute() must return '
            '(storage_path, size, meta)') from exc
    if not storage_path:
        raise ValueError(
            f'backup kind "{policy.target_type}" execute() returned no storage path')
    meta = dict(meta or {})
    meta.setdefault('engine', policy.target_type)
    # Contributed kinds are asked for 'full' and retention protects incremental
    # chains by ancestry, so record what actually happened rather than assuming.
    meta.setdefault('kind', kind or 'full')
    meta.setdefault('incremental', meta['kind'] == 'incremental')
    return storage_path, int(size or 0), meta


def restore(policy, target, run, options):
    """Restore a contributed run, or refuse if the kind can't."""
    entry = _require(policy.target_type)
    handler = entry.get('restore')
    if handler is None:
        raise ValueError(
            f'backup kind "{policy.target_type}" does not support restore')
    return handler(policy, target, run, options or {})


def supports_restore(target_type: str) -> bool:
    """True if *target_type* is registered and can restore."""
    entry = _KINDS.get(target_type)
    return bool(entry and entry.get('restore'))


def _require(target_type):
    entry = _KINDS.get(target_type)
    if entry is None:
        raise ValueError(f'No backup kind registered for "{target_type}"')
    return entry
