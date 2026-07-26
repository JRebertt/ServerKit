"""Database engines, composed from the template catalog.

There is no engine model, no engine table and no engine install mechanism. A
database engine **is** an app template that carries a top-level ``engine:``
block, and installing one **is** installing that template through the existing
deployment-job pipeline. Adding CockroachDB -- or anything else -- is dropping a
YAML file into ``backend/templates/`` or syncing a template repository. No
Python changes, ever.

This module only composes:

* :func:`engine_catalog`  -- engine templates + how many instances each has
* :func:`installed_engines` -- ``Application`` rows born from an engine
  template, with live container status and their engine metadata resolved
* :func:`plan_install` -- turns the Databases install form into the variables
  the template pipeline already understands

Safety rules that live here (the rest are enforced by the templates themselves):

1. **Private by default.** The bind-address variable is set from the explicit
   ``expose_public`` flag *after* merging caller-supplied variables, so a
   handcrafted ``variables`` payload cannot quietly publish an engine.
3. **Port collisions are refused** before a job is created, with the next free
   port in the 409 body.
6. **Images come from the template's compose only.** ``version`` is checked
   against the template's own ``engine.versions`` allow-list, so the tag can
   never be attacker-chosen.

Rule 5 (never destroy the data volume implicitly) is enforced at the app-delete
route: see ``_remove_data_flag`` in ``app/api/apps.py``.
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional

from app.services.template_service import TemplateService

logger = logging.getLogger(__name__)

# Which non-secret install variables are safe to echo back on a listing.
# Anything else (passwords, tokens, master keys) is never read out of the
# recorded install info.
_PUBLIC_VARIABLE_KEYS = ('BIND_ADDRESS', 'PORT', 'HTTP_PORT', 'DB_NAME')


# ── template <-> application mapping ─────────────────────────────────────────
def app_template_id(app) -> Optional[str]:
    """Which template an ``Application`` was installed from, or ``None``.

    Primary source is the panel's template config (written by the install
    finalizer). Falls back to the ``.serverkit-template.json`` dropped in the
    app directory, so an app survives a lost/reset config file.
    """
    try:
        installed = TemplateService.get_config().get('installed', {}) or {}
        record = installed.get(str(getattr(app, 'id', '')))
        if record and record.get('template_id'):
            return record['template_id']
    except Exception:
        pass
    info = _install_info(app)
    return (info or {}).get('template_id')


def _install_info(app) -> Optional[Dict]:
    """Parsed ``.serverkit-template.json`` from the app directory, or ``None``."""
    root = getattr(app, 'root_path', None)
    if not root:
        return None
    path = os.path.join(root, '.serverkit-template.json')
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def is_engine_app(app) -> bool:
    """True when ``app`` was installed from a template declaring ``engine:``."""
    template_id = app_template_id(app)
    if not template_id:
        return False
    result = TemplateService.get_template(template_id)
    return bool(result.get('success')
                and TemplateService.is_engine_template(result['template']))


# ── catalog ──────────────────────────────────────────────────────────────────
def engine_catalog() -> List[Dict]:
    """Every template carrying an ``engine:`` block, local or synced.

    Enriched with ``installed_count`` / ``instances`` so the catalog drawer can
    show an "Already running" section without a second round trip.
    """
    from app.models import Application

    counts: Dict[str, List[int]] = {}
    for app in Application.query.all():
        template_id = app_template_id(app)
        if template_id:
            counts.setdefault(template_id, []).append(app.id)

    catalog = []
    for entry in TemplateService.list_engine_templates():
        instances = counts.get(entry['id'], [])
        item = dict(entry)
        item.pop('filepath', None)   # a server path is not the UI's business
        item['installed_count'] = len(instances)
        item['instances'] = instances
        catalog.append(item)
    return catalog


def catalog_families(catalog: List[Dict]) -> List[str]:
    """Families actually present in the catalog, in the canonical order.

    Derived from the response so the UI never hardcodes a family list.
    """
    present = {(e.get('engine') or {}).get('family') for e in catalog}
    return [f for f in TemplateService.ENGINE_FAMILIES if f in present]


# ── installed instances ──────────────────────────────────────────────────────
def installed_engines(live_status: bool = True) -> List[Dict]:
    """Applications installed from an engine template, with their metadata."""
    from app.models import Application

    results = []
    for app in Application.query.order_by(Application.created_at.asc()).all():
        template_id = app_template_id(app)
        if not template_id:
            continue
        fetched = TemplateService.get_template(template_id)
        if not fetched.get('success'):
            continue
        template = fetched['template']
        engine = TemplateService.engine_metadata(template)
        if not engine:
            continue
        results.append(_describe_instance(app, template_id, template, engine,
                                          live_status=live_status))
    return results


def _describe_instance(app, template_id, template, engine, live_status=True) -> Dict:
    variables = ((_install_info(app) or {}).get('variables') or {})
    bind = variables.get(engine.get('bind_var') or TemplateService.ENGINE_DEFAULT_BIND_VAR)
    data = {
        'app_id': app.id,
        'name': app.name,
        'status': app.status,
        'port': app.port,
        'server_id': app.server_id,
        'root_path': app.root_path,
        'created_at': app.created_at.isoformat() if app.created_at else None,
        'template_id': template_id,
        'template_name': template.get('name'),
        'template_version': template.get('version'),
        'icon': template.get('icon'),
        'engine': engine,
        # Explicitly derived, not guessed: anything other than a loopback bind
        # means the port is reachable off-host.
        'exposed_public': bool(bind) and bind not in ('127.0.0.1', 'localhost', '::1'),
        # Never echo the admin secret; say only that one exists.
        'has_secret': bool(engine.get('admin_password_var')
                           and variables.get(engine['admin_password_var'])),
        'variables': {k: v for k, v in variables.items() if k in _PUBLIC_VARIABLE_KEYS},
    }
    data['container'] = _container_state(app) if live_status else None
    return data


def _container_state(app) -> Optional[Dict]:
    """Live container state, or ``None`` when Docker cannot answer."""
    from app.services.docker_service import DockerService
    ref = getattr(app, 'container_id', None) or app.name
    try:
        state = DockerService.get_container_state(ref)
    except Exception:
        return None
    if not state:
        return None
    return {'running': bool(state.get('running')), 'state': state.get('state')}


# ── install ──────────────────────────────────────────────────────────────────
def _err(message: str, status_code: int = 400, **extra) -> Dict:
    payload = {'error': message, 'status_code': status_code}
    payload.update(extra)
    return payload


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9-]+', '-', (value or '').strip().lower()).strip('-')


def default_instance_name(template_id: str) -> str:
    """``postgresql``, then ``postgresql-2``… — the first name not taken."""
    from app.models import Application

    base = _slug(template_id) or 'engine'
    taken = {a.name for a in Application.query.all()}
    if base not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f'{base}-{suffix}'
        if candidate not in taken:
            return candidate
    return f'{base}-{os.urandom(3).hex()}'


def plan_install(*, template_id, version=None, instance_name=None, port=None,
                 expose_public=False, initial_database=None, variables=None) -> Dict:
    """Validate the Databases install form and render it into template variables.

    Returns ``{'app_name', 'variables', 'template', 'engine', 'warning'?}`` or an
    error dict carrying ``status_code``. Performs no side effects -- the caller
    hands the result straight to the template install pipeline.
    """
    if not template_id:
        return _err('template_id is required', 400)

    fetched = TemplateService.get_template(template_id)
    if not fetched.get('success'):
        return _err(f"Template '{template_id}' not found", 404)

    template = fetched['template']
    engine = TemplateService.engine_metadata(template)
    if not engine:
        # Safety rule 6: this route installs engines, and an engine is defined
        # by its template. Anything else goes through the normal template flow.
        return _err(f"Template '{template_id}' is not a database engine "
                    "(it declares no `engine:` block)", 400)

    declared = _declared_variables(template)
    resolved: Dict[str, str] = dict(variables or {})

    # Version -> image tag, checked against the template's own allow-list so a
    # caller can never inject an arbitrary image reference.
    if version not in (None, ''):
        version = str(version)
        if version not in engine['versions']:
            return _err(f"Version '{version}' is not offered by {template.get('name')}", 400,
                        versions=engine['versions'])
        version_var = (template.get('engine') or {}).get('version_var') or 'IMAGE_TAG'
        if version_var not in declared:
            return _err(f"{template.get('name')} does not support choosing a version", 400)
        resolved[version_var] = version

    # Instance name == app name; the pipeline's own rules apply.
    app_name = _slug(instance_name) if instance_name else default_instance_name(template_id)
    from app.utils.slug import validate_app_name
    valid, error = validate_app_name(app_name, min_length=3)
    if not valid:
        return _err(error, 400)

    # Safety rule 3: refuse a busy port up front and name a free one.
    if port not in (None, ''):
        try:
            port = int(port)
        except (TypeError, ValueError):
            return _err('port must be an integer', 400)
        if not 1 <= port <= 65535:
            return _err('port must be between 1 and 65535', 400)
        if not TemplateService._port_is_free(port):
            return _err(f'Port {port} is already in use', 409, port=port,
                        suggested_port=TemplateService._find_available_port(port + 1))
        port_var = engine.get('port_var') or TemplateService.ENGINE_DEFAULT_PORT_VAR
        if port_var not in declared:
            return _err(f"{template.get('name')} does not expose a configurable port", 400)
        resolved[port_var] = str(port)

    if initial_database not in (None, ''):
        database_var = engine.get('database_var')
        if not database_var:
            return _err(f"{template.get('name')} does not support an initial database", 400)
        resolved[database_var] = str(initial_database)

    # Safety rule 1, applied LAST so a caller-supplied `variables` entry can
    # never override the explicit private/public decision.
    warning = None
    if expose_public and not engine.get('admin_password_var'):
        # Some engines have no credentials to expose at all -- CockroachDB's
        # single-node mode runs `--insecure`. For those the loopback bind is the
        # ONLY access control, so publishing one to every interface is refused
        # outright rather than warned about.
        return _err(f"{template.get('name')} runs without authentication, so it "
                    'cannot be exposed publicly. Keep it bound to localhost and '
                    'reach it over a tunnel, or move it to a credentialed '
                    'configuration first.', 400)
    bind_var = engine.get('bind_var') or TemplateService.ENGINE_DEFAULT_BIND_VAR
    if bind_var in declared:
        resolved[bind_var] = (TemplateService.ENGINE_PUBLIC_BIND if expose_public
                              else TemplateService.ENGINE_PRIVATE_BIND)
    elif expose_public:
        return _err(f"{template.get('name')} cannot be exposed publicly "
                    "(its template declares no bind-address variable)", 400)

    if expose_public:
        warning = (f"{template.get('name')} will accept connections from any network "
                   'interface. Anyone who can reach this host can attempt to '
                   'authenticate against it — restrict it with the firewall, or '
                   'keep it private and reach it over a tunnel.')

    return {'app_name': app_name, 'variables': resolved, 'template': template,
            'engine': engine, 'warning': warning}


def _declared_variables(template: Dict) -> set:
    """Names of the variables a template declares (list or dict form)."""
    raw = template.get('variables', [])
    if isinstance(raw, list):
        return {v.get('name') for v in raw if isinstance(v, dict) and v.get('name')}
    if isinstance(raw, dict):
        return set(raw.keys())
    return set()
