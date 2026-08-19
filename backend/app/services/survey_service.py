"""Server survey service — read-only "flights" over a paired agent (plan 27).

Observe mode's heart is a *read-only survey*: the agent flies a declarative
probe catalog against a paired Linux box and returns a structured payload; the
panel normalizes it into a stable **Server Map** and stores it as an immutable
snapshot (``ServerSurvey``). Any two flights of the same server are diffable
("what changed since last flight").

This module is stateless — it loads the shipped probe catalog, dispatches the
``survey:read`` command through the agent registry (which enforces the
``survey:read`` permission scope), normalizes the returned payload, and persists
snapshots. See ``docs/AGENT_SURVEY_SPEC.md`` for the panel↔agent contract and
``app/data/survey_probe_catalog.yaml`` for the catalog itself.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app import db
from app.models.server_survey import ServerSurvey


class SurveyError(Exception):
    """Raised when the probe catalog is missing or malformed."""


# ── Catalog ──────────────────────────────────────────────────────────────────

# The shipped, versioned probe catalog. This is the honest, operator-facing
# answer to "what will you look at on my server?" — shown verbatim in the UI.
CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'survey_probe_catalog.yaml'
)

# Cached parsed catalog (parse once, it never changes at runtime).
_catalog_cache: Optional[Dict[str, Any]] = None

# Fields that must be present on every probe entry for the catalog to lint.
_REQUIRED_PROBE_FIELDS = ('id', 'kind', 'title', 'reads')

# Probe ids whose detection maps to a running *service* row. Marker/inventory
# probes (foreign-panel, crontabs, certs, listeners) are surfaced elsewhere in
# the map and must NOT appear as service rows even when "detected".
_SERVICE_PROBE_IDS = frozenset({'nginx', 'apache', 'php-fpm', 'docker', 'databases', 'mail'})

# Web-server probes whose vhosts become site rows, mapped to their stack label.
_WEB_PROBES = {'nginx': 'nginx', 'apache': 'apache'}


def load_catalog(force: bool = False) -> Dict[str, Any]:
    """Load and cache the probe catalog from disk.

    Raises SurveyError if the file is missing or is not valid YAML mapping.
    """
    global _catalog_cache
    if _catalog_cache is not None and not force:
        return _catalog_cache

    if not os.path.exists(CATALOG_PATH):
        raise SurveyError(f'Probe catalog not found at {CATALOG_PATH}')
    try:
        with open(CATALOG_PATH, 'r', encoding='utf-8') as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise SurveyError(f'Probe catalog is not valid YAML: {exc}') from exc

    if not isinstance(data, dict):
        raise SurveyError('Probe catalog must be a mapping')

    _catalog_cache = data
    return data


def lint_catalog(catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Strictly validate a probe catalog, returning it unchanged on success.

    A malformed catalog is a bug we want to surface loudly (the survey command
    and the operator-facing index both depend on it), so this raises
    SurveyError rather than silently degrading.
    """
    if not isinstance(catalog, dict):
        raise SurveyError('catalog must be a mapping')

    version = catalog.get('version')
    if not isinstance(version, int) or isinstance(version, bool):
        raise SurveyError('catalog "version" must be an integer')

    probes = catalog.get('probes')
    if not isinstance(probes, list) or not probes:
        raise SurveyError('catalog "probes" must be a non-empty list')

    seen_ids = set()
    for probe in probes:
        if not isinstance(probe, dict):
            raise SurveyError('each probe must be a mapping')
        for field in _REQUIRED_PROBE_FIELDS:
            if not probe.get(field):
                raise SurveyError(f'probe is missing required field "{field}": {probe!r}')
        pid = probe['id']
        if not isinstance(pid, str):
            raise SurveyError(f'probe "id" must be a string: {pid!r}')
        if pid in seen_ids:
            raise SurveyError(f'duplicate probe id: {pid}')
        seen_ids.add(pid)
        # A probe must know how to detect itself; the catch-all "listeners"
        # probe is allowed an empty (but present) detect block.
        if 'detect' not in probe:
            raise SurveyError(f'probe "{pid}" is missing a "detect" block')

    return catalog


def probe_index() -> Dict[str, Any]:
    """The operator-facing probe index — exactly what the survey reads.

    Returns a JSON-serializable, secret-free summary of the catalog (version +
    one entry per probe with the human-readable ``title``/``reads`` copy). Shown
    verbatim in the UI. Raises SurveyError if the catalog is malformed.
    """
    catalog = lint_catalog(load_catalog())
    probes = [
        {
            'id': p['id'],
            'kind': p.get('kind'),
            'title': p.get('title'),
            'reads': p.get('reads'),
        }
        for p in catalog['probes']
    ]
    return {'version': catalog['version'], 'probes': probes}


def catalog_version() -> int:
    """Current probe-catalog version (defaults to 1 if unreadable)."""
    try:
        return int(load_catalog().get('version') or 1)
    except SurveyError:
        return 1


# ── Normalization ────────────────────────────────────────────────────────────

def normalize_map(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse a raw per-probe agent payload into the canonical Server Map.

    Defensive by contract: a partial or empty payload (or ``None``) still yields
    a valid, sparse map — the agent may be partially implemented and every
    probe field is optional (see docs/AGENT_SURVEY_SPEC.md).
    """
    payload = payload if isinstance(payload, dict) else {}
    probes = payload.get('probes') if isinstance(payload.get('probes'), dict) else {}

    # Foreign-panel detection is computed first — it decides whether sites are
    # labelled as managed by another panel vs. by their own stack.
    foreign_entry = probes.get('foreign-panel') or {}
    foreign_detected = bool(foreign_entry.get('detected'))
    foreign_panels = [
        {'marker': marker}
        for marker in (foreign_entry.get('markers') or [])
        if isinstance(marker, str)
    ]

    services: List[Dict[str, Any]] = []
    for pid, entry in probes.items():
        if not isinstance(entry, dict):
            continue
        if pid not in _SERVICE_PROBE_IDS:
            continue
        if not entry.get('detected'):
            continue
        svc = entry.get('service') or {}
        services.append({
            'id': pid,
            'active': bool(svc.get('active')) if svc else None,
            'ports': svc.get('ports') or [],
        })

    sites: List[Dict[str, Any]] = []
    for pid, stack in _WEB_PROBES.items():
        entry = probes.get(pid)
        if not isinstance(entry, dict):
            continue
        for vhost in (entry.get('vhosts') or []):
            if not isinstance(vhost, dict):
                continue
            domain = vhost.get('server_name')
            if not domain:
                continue
            upstream = vhost.get('upstream') or vhost.get('proxy_pass')
            sites.append({
                'domain': domain,
                'stack': stack,
                'doc_root': vhost.get('root'),
                'upstream': upstream,
                'managed_by': 'other-panel' if foreign_detected else stack,
            })

    db_entry = probes.get('databases') or {}
    databases = []
    for eng in (db_entry.get('engines') or []):
        if not isinstance(eng, dict):
            continue
        databases.append({
            'engine': eng.get('name'),
            'active': bool(eng.get('active')) if 'active' in eng else None,
            'port': eng.get('port'),
        })

    cert_entry = probes.get('certs') or {}
    certs = [
        {'domain': c.get('domain'), 'expires_at': c.get('expires_at')}
        for c in (cert_entry.get('certs') or [])
        if isinstance(c, dict) and c.get('domain')
    ]

    cron_entry = probes.get('crontabs') or {}
    cron = [
        {'user': c.get('user'), 'lines': c.get('lines') or []}
        for c in (cron_entry.get('crontabs') or [])
        if isinstance(c, dict)
    ]

    listener_entry = probes.get('listeners') or {}
    listeners = [
        {'port': l.get('port'), 'proto': l.get('proto'), 'process': l.get('process')}
        for l in (listener_entry.get('listeners') or [])
        if isinstance(l, dict)
    ]

    return {
        'catalog_version': payload.get('catalog_version', 1),
        'services': services,
        'sites': sites,
        'databases': databases,
        'certs': certs,
        'cron': cron,
        'listeners': listeners,
        'foreign_panel_detected': foreign_detected,
        'foreign_panels': foreign_panels,
        'probes_run': list(probes.keys()),
    }


# ── Diff ─────────────────────────────────────────────────────────────────────

def _index_by(items: Optional[List[Dict[str, Any]]], key: str) -> Dict[Any, Dict[str, Any]]:
    out: Dict[Any, Dict[str, Any]] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        k = item.get(key)
        if k is not None:
            out[k] = item
    return out


def _diff_collection(
    old_items: Optional[List[Dict[str, Any]]],
    new_items: Optional[List[Dict[str, Any]]],
    key: str,
    compare_fields: Tuple[str, ...],
) -> Dict[str, List[Dict[str, Any]]]:
    """Diff two lists of dicts by an identity ``key``.

    Returns ``{added, removed, changed}`` where ``changed`` entries carry the
    identity ``key`` plus ``from``/``to`` snapshots of the row.
    """
    old = _index_by(old_items, key)
    new = _index_by(new_items, key)

    added = [new[k] for k in new if k not in old]
    removed = [old[k] for k in old if k not in new]
    changed = []
    for k in new:
        if k not in old:
            continue
        o, n = old[k], new[k]
        if any(o.get(f) != n.get(f) for f in compare_fields):
            changed.append({'key': k, 'from': o, 'to': n})
    return {'added': added, 'removed': removed, 'changed': changed}


def diff_maps(old_map: Optional[Dict[str, Any]], new_map: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Diff two normalized Server Maps ("what changed between two flights")."""
    old_map = old_map if isinstance(old_map, dict) else {}
    new_map = new_map if isinstance(new_map, dict) else {}

    return {
        'catalog_changed': old_map.get('catalog_version') != new_map.get('catalog_version'),
        'services': _diff_collection(
            old_map.get('services'), new_map.get('services'), 'id', ('active', 'ports')),
        'sites': _diff_collection(
            old_map.get('sites'), new_map.get('sites'), 'domain',
            ('doc_root', 'upstream', 'stack', 'managed_by')),
        'databases': _diff_collection(
            old_map.get('databases'), new_map.get('databases'), 'engine', ('active', 'port')),
        'certs': _diff_collection(
            old_map.get('certs'), new_map.get('certs'), 'domain', ('expires_at',)),
        'cron': _diff_collection(
            old_map.get('cron'), new_map.get('cron'), 'user', ('lines',)),
        'listeners': _diff_collection(
            old_map.get('listeners'), new_map.get('listeners'), 'port', ('proto', 'process')),
        'foreign_panel_changed':
            bool(old_map.get('foreign_panel_detected')) != bool(new_map.get('foreign_panel_detected')),
    }


# ── Snapshot storage ─────────────────────────────────────────────────────────

def record_survey(server_id: str, server_map: Dict[str, Any]) -> ServerSurvey:
    """Persist a normalized Server Map as a new immutable snapshot row."""
    version = 1
    if isinstance(server_map, dict):
        try:
            version = int(server_map.get('catalog_version') or 1)
        except (TypeError, ValueError):
            version = 1

    survey = ServerSurvey(server_id=server_id, catalog_version=version)
    survey.set_map(server_map)
    db.session.add(survey)
    db.session.commit()
    return survey


def list_surveys(server_id: str) -> List[ServerSurvey]:
    """All survey snapshots for a server, newest first.

    Ties on ``taken_at`` (two flights recorded in the same clock tick) are
    broken by descending id so ordering is deterministic.
    """
    return (
        ServerSurvey.query
        .filter_by(server_id=server_id)
        .order_by(ServerSurvey.taken_at.desc(), ServerSurvey.id.desc())
        .all()
    )


def latest_survey(server_id: str) -> Optional[ServerSurvey]:
    """The most recent survey snapshot for a server, or None."""
    return (
        ServerSurvey.query
        .filter_by(server_id=server_id)
        .order_by(ServerSurvey.taken_at.desc(), ServerSurvey.id.desc())
        .first()
    )


# ── Dispatch ─────────────────────────────────────────────────────────────────

def run_survey(server_id: str, user_id: Optional[int] = None) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Fly a read-only survey against the server's agent and store the map.

    Returns ``(survey_dict, None)`` on success or ``(None, error)`` where error
    is ``{'error', 'code', 'status'}``. Degrades cleanly: an offline agent →
    503, an agent that doesn't advertise the ``survey`` capability → 409, and a
    failed/timed-out command → an appropriate error — never a crash.
    """
    from app.services.agent_registry import agent_registry
    from app.services.remote_command_dispatcher import dispatch_agent_command

    if not agent_registry.is_agent_connected(server_id):
        return None, {
            'error': 'Agent is not connected',
            'code': 'AGENT_OFFLINE',
            'status': 503,
        }

    # Capability gate: older agents that never advertise `survey` degrade to
    # "unsupported" rather than erroring (AGENT_SURVEY_SPEC rollout rule).
    caps = agent_registry.get_capabilities(server_id)
    if not (caps or {}).get('survey'):
        return None, {
            'error': 'This agent does not support surveys (update the agent to enable Observe/survey)',
            'code': 'SURVEY_UNSUPPORTED',
            'status': 409,
        }

    try:
        catalog = lint_catalog(load_catalog())
    except SurveyError as exc:
        return None, {
            'error': f'Invalid probe catalog: {exc}',
            'code': 'CATALOG_INVALID',
            'status': 500,
        }

    result = dispatch_agent_command(
        server_id,
        'survey:read',
        {'catalog': catalog},
        user_id=user_id,
    )

    if not result.get('success'):
        code = result.get('code') or 'SURVEY_FAILED'
        if code in ('AGENT_OFFLINE', 'AGENT_RECONNECTED', 'TIMEOUT'):
            status = 503
        elif code == 'PERMISSION_DENIED':
            status = 403
        else:
            status = 502
        return None, {
            'error': result.get('error') or 'Survey failed',
            'code': code,
            'status': status,
        }

    server_map = normalize_map(result.get('data') or {})
    survey = record_survey(server_id, server_map)
    return survey.to_dict(), None
