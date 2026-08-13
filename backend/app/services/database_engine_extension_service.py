"""Database engine extensions — installed INTO a running engine, not beside it.

An engine is an app template because an engine gets a container. An extension
gets nothing: installing pgvector is executing ``CREATE EXTENSION IF NOT EXISTS
vector;`` against a database on a PostgreSQL that is already up. So an extension
is a small YAML in ``<templates>/extensions/`` and everything below is composed
from those files -- dropping one in makes the extension appear, with no Python
change, exactly as dropping an engine YAML does.

Three things this module is responsible for:

1. **Discovery.** :func:`extension_catalog` — what exists, which engine
   templates can host each one, and which installed instances can.
2. **Compatibility.** Matching is on the engine template's *own*
   ``engine.protocol``, so a new PostgreSQL-speaking engine template becomes a
   host automatically and neither side names the other.
3. **The image problem, which is the whole difficulty.**

   ``CREATE EXTENSION vector`` is a correct statement that fails on stock
   ``postgres:16``::

       ERROR:  could not open extension control file
               "/usr/share/postgresql/16/extension/vector.control"

   The image simply does not carry the shared library, and no statement can
   conjure it. ServerKit never recreates a container behind the operator's back,
   so instead:

   * the extension declares ``images:`` — the repositories that ship it — and a
     listing marks an instance ``image_unsupported`` **before** anything is
     clicked, naming the image that would work;
   * an install *always* asks the engine first (``available_query`` against
     ``pg_available_extensions``) and refuses with that same remedy if the
     answer is empty. The probe is authoritative: an operator who built their
     own capable image is allowed even though its name is unknown to us, and an
     image whose name matches but whose library is missing is still refused.

   The remedy points at real, installable engine templates, found by matching
   the extension's ``images`` against each engine template's own compose image
   — so shipping a capable engine is, again, adding a YAML file.
"""
import logging
import os
import re
from typing import Dict, List, Optional

import yaml

from app.services import database_engine_service as engines
from app.services.database_service import DatabaseService
from app.services.template_service import TemplateService

logger = logging.getLogger(__name__)

# Per-instance compatibility verdicts. The UI renders these; it does not
# recompute them.
STATUS_INSTALLED = 'installed'            # already present in the database
STATUS_READY = 'ready'                    # can be installed right now
STATUS_IMAGE_UNSUPPORTED = 'image_unsupported'   # engine image does not ship it
STATUS_INCOMPATIBLE = 'incompatible'      # wrong engine entirely
STATUS_UNKNOWN = 'unknown'                # not probed / engine unreachable

# Which client can execute a statement against which engine protocol. This is a
# property of ServerKit's clients, not of any extension: adding an EXTENSION
# needs no entry here, only adding a whole new engine PROTOCOL would -- and the
# protocol list is already a closed enum in TemplateService.
_DATABASE_NAME_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_\-]{0,62}$')


def _postgres_exec(context: Dict, sql: str, database: Optional[str]) -> Dict:
    return DatabaseService.docker_pg_execute(
        context['container'], sql,
        database=database or context.get('default_database') or 'postgres',
        user=context.get('admin_user') or 'postgres',
        password=context.get('password'))


def _mysql_exec(context: Dict, sql: str, database: Optional[str]) -> Dict:
    return DatabaseService.docker_mysql_execute(
        context['container'], sql,
        database=database or context.get('default_database'),
        user=context.get('admin_user') or 'root',
        password=context.get('password'))


EXECUTORS = {
    'postgresql': _postgres_exec,
    'mysql': _mysql_exec,
}


def _err(message: str, status_code: int = 400, **extra) -> Dict:
    payload = {'error': message, 'status_code': status_code}
    payload.update(extra)
    return payload


# ── image identity ───────────────────────────────────────────────────────────
def _repository(image: str) -> str:
    """``pgvector/pgvector:pg16`` -> ``pgvector/pgvector``.

    Strips a digest and a tag (a colon in the last path segment), then a
    registry host, then Docker Hub's implicit ``library/`` namespace, so the
    same image written five ways compares equal.
    """
    ref = str(image or '').strip().split('@')[0]
    head, sep, tail = ref.rpartition(':')
    if sep and '/' not in tail:
        ref = head
    parts = ref.split('/')
    if len(parts) > 1 and ('.' in parts[0] or ':' in parts[0] or parts[0] == 'localhost'):
        parts = parts[1:]
    if len(parts) == 2 and parts[0] == 'library':
        parts = parts[1:]
    return '/'.join(parts)


def _image_provides(image: Optional[str], declared: List[str]) -> Optional[bool]:
    """Does ``image`` look like one of the repositories that ship the extension?

    ``None`` when there is nothing to decide from (no image resolved), so a
    caller can tell "no" apart from "don't know".
    """
    if not declared:
        return True          # the extension makes no image claim
    if not image:
        return None
    repository = _repository(image)
    return any(repository == _repository(want) for want in declared)


def _compose_images(template: Dict) -> List[str]:
    """Image references a template's compose declares."""
    services = ((template or {}).get('compose') or {}).get('services') or {}
    return [str(svc['image']) for svc in services.values()
            if isinstance(svc, dict) and svc.get('image')]


def instance_image(app) -> Optional[str]:
    """The image an installed engine actually runs.

    Read from the rendered compose in the app directory first -- it is on disk,
    it is what was installed, and it needs no Docker. Falls back to inspecting
    the live container.
    """
    root = getattr(app, 'root_path', None)
    if root:
        for filename in ('docker-compose.yml', 'docker-compose.yaml'):
            path = os.path.join(root, filename)
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    compose = yaml.safe_load(fh) or {}
            except Exception:
                continue
            services = compose.get('services') or {}
            service = services.get('app') or next(iter(services.values()), None)
            if isinstance(service, dict) and service.get('image'):
                return str(service['image'])
    try:
        from app.services.docker_service import DockerService
        info = DockerService.get_container(getattr(app, 'container_id', None) or app.name)
    except Exception:
        return None
    return ((info or {}).get('Config') or {}).get('Image')


# ── catalog ──────────────────────────────────────────────────────────────────
def get_extension(extension_id: str) -> Optional[Dict]:
    """One extension by id, straight off the YAML."""
    return TemplateService.get_extension_template(extension_id)


def _hosts_for(extension: Dict, engine_templates: List[Dict]) -> List[Dict]:
    """Engine templates that can host ``extension``, and whether each ships it.

    ``provides`` is what makes the remedy actionable: an operator told their
    PostgreSQL cannot host pgvector is also told which engine template can.
    """
    hosts = []
    for entry in engine_templates:
        engine = entry.get('engine') or {}
        # Both halves matter. Speaking the protocol is not enough -- CockroachDB
        # answers on the PostgreSQL wire and cannot load a single extension --
        # so the engine has to have declared `engine.extensions: true`.
        if not engine.get('supports_extensions'):
            continue
        if engine.get('protocol') != extension['protocol']:
            continue
        if extension['templates'] and entry['id'] not in extension['templates']:
            continue
        fetched = TemplateService.get_template(entry['id'])
        images = _compose_images(fetched['template']) if fetched.get('success') else []
        provides = any(_image_provides(image, extension['images']) for image in images)
        hosts.append({
            'template_id': entry['id'],
            'name': entry.get('name'),
            # The repository, not the compose string: a template's image still
            # carries an unresolved ${IMAGE_TAG} at this point.
            'image': _repository(images[0]) if images else None,
            'provides': bool(provides),
        })
    return hosts


def extension_catalog() -> List[Dict]:
    """Every declared extension, with who can host it and where it is installed.

    One round trip is enough for the drawer: which engine templates host it,
    which of those actually ship it, and the id of every installed instance
    that is compatible today.
    """
    engine_templates = TemplateService.list_engine_templates()
    instances = engine_instances()

    catalog = []
    for extension in TemplateService.list_extension_templates():
        hosts = _hosts_for(extension, engine_templates)
        host_ids = {h['template_id'] for h in hosts}

        # "Compatible" means *not known to be incompatible*: an instance whose
        # image could not be read stays offered, because the install itself
        # still asks the engine before it writes anything.
        compatible, needs_image = [], []
        for instance in instances:
            if instance['template_id'] not in host_ids:
                continue
            (needs_image
             if _instance_verdict(instance, extension)[0] == STATUS_IMAGE_UNSUPPORTED
             else compatible).append(instance['app_id'])

        item = dict(extension)
        item['hosts'] = hosts
        item['provided_by'] = [h['template_id'] for h in hosts if h['provides']]
        item['compatible_instances'] = compatible
        item['incompatible_instances'] = needs_image
        catalog.append(item)
    return catalog


# ── per-instance compatibility ───────────────────────────────────────────────
def _instance_verdict(instance: Dict, extension: Dict) -> tuple:
    """Static verdict for one instance/extension pair: ``(status, reason)``.

    Static because it costs nothing -- no Docker, no exec. It is enough to grey
    a card out in the catalog; :func:`install_extension` still asks the engine
    itself before it writes anything.
    """
    engine = instance.get('engine') or {}
    protocol = engine.get('protocol')
    if protocol != extension['protocol']:
        return STATUS_INCOMPATIBLE, (
            f"{instance['name']} speaks {protocol or 'no known protocol'}; "
            f"{extension['name']} needs {extension['protocol']}")
    if not engine.get('supports_extensions'):
        return STATUS_INCOMPATIBLE, (
            f"{instance['template_name'] or instance['name']} does not support "
            'database extensions, even though it speaks the same protocol')
    if extension['templates'] and instance['template_id'] not in extension['templates']:
        return STATUS_INCOMPATIBLE, (
            f"{extension['name']} is only offered for "
            f"{', '.join(extension['templates'])}")
    provides = _image_provides(instance.get('image'), extension['images'])
    if provides is False:
        return STATUS_IMAGE_UNSUPPORTED, (
            f"{instance['name']} runs {instance.get('image')}, which does not ship "
            f"{extension['name']}. Enabling it there would fail with "
            '"could not open extension control file".')
    if provides is None:
        return STATUS_UNKNOWN, 'Could not determine which image this engine runs'
    return STATUS_READY, None


def _remedy(extension: Dict, instance: Dict, engine_templates=None) -> Dict:
    """What the operator can actually do about an image that cannot host it."""
    version = instance.get('engine_version')
    hint = extension.get('image_hint')
    suggested = None
    if hint:
        suggested = hint.replace('{version}', str(version)) if version else hint
    elif extension['images']:
        suggested = extension['images'][0]
    hosts = _hosts_for(extension, engine_templates
                       if engine_templates is not None
                       else TemplateService.list_engine_templates())
    return {
        'kind': 'image',
        'current_image': instance.get('image'),
        'required_images': extension['images'],
        'suggested_image': suggested,
        # Engine templates whose own image ships it -- installable today.
        'install_instead': [h for h in hosts if h['provides']],
        'action': (
            'This engine runs an image without the extension, and no statement can '
            'add it. Install an engine whose image ships it and point the app at '
            f"that instance{', for example ' + suggested if suggested else ''}. "
            'ServerKit will not silently recreate this container: doing so would '
            'restart every connection to it.'),
    }


def instance_extensions(app_id: int, probe: bool = False) -> Dict:
    """Every extension, judged against ONE installed engine.

    ``probe=True`` replaces the static image verdict with the engine's own
    answer, which is slower (a docker exec per extension) but authoritative.
    """
    instance = _find_instance(app_id)
    if instance is None:
        return _err(f'No installed database engine with id {app_id}', 404)

    engine_templates = TemplateService.list_engine_templates()
    results = []
    for extension in TemplateService.list_extension_templates():
        status, reason = _instance_verdict(instance, extension)
        item = dict(extension)
        item['installed_version'] = None

        if probe and status in (STATUS_READY, STATUS_IMAGE_UNSUPPORTED, STATUS_UNKNOWN):
            status, reason, item['installed_version'] = _probe(instance, extension,
                                                               status, reason)

        item['status'] = status
        item['reason'] = reason
        item['remedy'] = (_remedy(extension, instance, engine_templates)
                          if status == STATUS_IMAGE_UNSUPPORTED else None)
        results.append(item)

    return {'instance': _public_instance(instance), 'extensions': results,
            'probed': bool(probe)}


def _probe(instance: Dict, extension: Dict, status: str, reason: Optional[str]) -> tuple:
    """Ask the running engine what it can load, and what it already has."""
    executor = EXECUTORS.get(extension['protocol'])
    if executor is None or not extension.get('available_query'):
        return status, reason, None

    context = _execution_context(instance)
    result = executor(context, extension['available_query'], None)
    if not result.get('success'):
        # Falling back to the static verdict is deliberate: a stopped container
        # must not turn "your image cannot host this" into "maybe".
        if status == STATUS_IMAGE_UNSUPPORTED:
            return status, reason, None
        return STATUS_UNKNOWN, (result.get('error') or '').strip() or \
            'Could not reach the engine', None
    if not (result.get('output') or '').strip():
        return STATUS_IMAGE_UNSUPPORTED, (
            f"{instance['name']} cannot load {extension['name']}: the running image "
            'does not ship it.'), None

    version = None
    if extension.get('installed_query'):
        installed = executor(context, extension['installed_query'], None)
        version = (installed.get('output') or '').strip() or None
    return (STATUS_INSTALLED if version else STATUS_READY), None, version


# ── install ──────────────────────────────────────────────────────────────────
def install_extension(app_id: int, extension_id: str, database: str = None) -> Dict:
    """Run an extension's statement against one database on one instance.

    Never executes the statement without first confirming the engine can load
    it, so the failure mode is a 409 naming the image to use, not a raw
    ``could not open extension control file`` surfaced as a generic error.
    """
    extension = get_extension(extension_id)
    if extension is None:
        return _err(f"Unknown extension '{extension_id}'", 404,
                    available=[e['id'] for e in TemplateService.list_extension_templates()])

    instance = _find_instance(app_id)
    if instance is None:
        return _err(f'No installed database engine with id {app_id}', 404)

    status, reason = _instance_verdict(instance, extension)
    if status == STATUS_INCOMPATIBLE:
        return _err(reason, 400,
                    hosts=[h['template_id']
                           for h in _hosts_for(extension, TemplateService.list_engine_templates())])

    executor = EXECUTORS.get(extension['protocol'])
    if executor is None:
        return _err(f"ServerKit has no client for {extension['protocol']}, so it "
                    'cannot install extensions into it', 400)

    database = (database or instance.get('default_database') or '').strip() or None
    if database and not _DATABASE_NAME_RE.match(database):
        return _err(f"'{database}' is not a valid database name", 400)

    context = _execution_context(instance)

    # 1. Ask the engine itself. This is the check that matters: it is the only
    #    one that knows whether the running image carries the control file.
    if extension.get('available_query'):
        probe = executor(context, extension['available_query'], database)
        if not probe.get('success'):
            if status == STATUS_IMAGE_UNSUPPORTED:
                return _err(reason, 409, status=STATUS_IMAGE_UNSUPPORTED,
                            remedy=_remedy(extension, instance))
            return _err(
                f"Could not reach {instance['name']} to check whether it can load "
                f"{extension['name']}: {(probe.get('error') or '').strip() or 'no answer'}",
                502, status=STATUS_UNKNOWN)
        if not (probe.get('output') or '').strip():
            return _err(
                f"{instance['name']} cannot load {extension['name']}: its image "
                f"({instance.get('image') or 'unknown'}) does not ship the extension. "
                'Installing it would fail with "could not open extension control file".',
                409, status=STATUS_IMAGE_UNSUPPORTED,
                remedy=_remedy(extension, instance))
    elif status == STATUS_IMAGE_UNSUPPORTED:
        # No probe to fall back on -- the declared image requirement is all we
        # have, and it says no.
        return _err(reason, 409, status=STATUS_IMAGE_UNSUPPORTED,
                    remedy=_remedy(extension, instance))

    # 2. The statement comes from the extension's YAML, never from the request.
    result = executor(context, extension['statement'], database)
    if not result.get('success'):
        return _err(
            f"{extension['name']} could not be installed into "
            f"{database or instance['name']}: "
            f"{(result.get('error') or '').strip() or 'the engine rejected the statement'}",
            400, status=STATUS_UNKNOWN)

    version = None
    if extension.get('installed_query'):
        installed = executor(context, extension['installed_query'], database)
        version = (installed.get('output') or '').strip() or None

    return {
        'success': True,
        'status': STATUS_INSTALLED,
        'extension': {'id': extension['id'], 'name': extension['name'],
                      'version': version or extension['version']},
        'instance': _public_instance(instance),
        'database': database,
        'statement': extension['statement'],
    }


# ── instance plumbing ────────────────────────────────────────────────────────
def engine_instances() -> List[Dict]:
    """Every installed engine, described for extension purposes."""
    from app.models import Application

    described = []
    for app in Application.query_active().order_by(Application.created_at.asc()).all():
        record = _describe(app)
        if record:
            described.append(record)
    return described


def _find_instance(app_id: int) -> Optional[Dict]:
    """One installed engine by app id, or ``None`` when it is not an engine."""
    from app.models import Application

    app = Application.query_active().filter_by(id=app_id).first()
    return _describe(app) if app is not None else None


def _describe(app) -> Optional[Dict]:
    """An installed engine, enriched with the bits extensions need.

    Engine-ness is decided by ``database_engine_service`` (a template carrying
    an ``engine:`` block), so "what counts as an installed engine" is still
    answered in exactly one place.
    """
    template_id = engines.app_template_id(app)
    if not template_id:
        return None
    fetched = TemplateService.get_template(template_id)
    if not fetched.get('success'):
        return None
    template = fetched['template']
    # No `engine:` block, no engine -- an ordinary app cannot host an extension.
    engine = TemplateService.engine_metadata(template)
    if not engine:
        return None
    variables = ((engines._install_info(app) or {}).get('variables') or {})
    version_var = (template.get('engine') or {}).get('version_var') or 'IMAGE_TAG'

    return {
        'app_id': app.id,
        'name': app.name,
        'status': app.status,
        'container': getattr(app, 'container_id', None) or app.name,
        'template_id': template_id,
        'template_name': template.get('name'),
        'engine': engine,
        'engine_version': variables.get(version_var) or template.get('version'),
        'image': instance_image(app),
        'default_database': variables.get(engine.get('database_var') or ''),
        'admin_user': engine.get('admin_user'),
        'password': variables.get(engine.get('admin_password_var') or ''),
    }


def _execution_context(instance: Dict) -> Dict:
    return {
        'container': instance['container'],
        'admin_user': instance.get('admin_user'),
        'password': instance.get('password'),
        'default_database': instance.get('default_database'),
    }


def _public_instance(instance: Dict) -> Dict:
    """The instance as the API may describe it — never the admin secret."""
    return {
        'app_id': instance['app_id'],
        'name': instance['name'],
        'status': instance['status'],
        'template_id': instance['template_id'],
        'template_name': instance['template_name'],
        'protocol': (instance.get('engine') or {}).get('protocol'),
        'engine_version': instance.get('engine_version'),
        'image': instance.get('image'),
        'default_database': instance.get('default_database'),
    }
