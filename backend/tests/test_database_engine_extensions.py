"""Database engine extensions — installed INTO a running engine, not beside it.

Sibling of ``test_database_engines.py``: engines are app templates, extensions
are not (they get no container), so they get their own file rather than a
section of that one.

Two tests carry the design:

* ``test_dropping_a_new_extension_yaml_lists_it`` — the same zero-code-change
  property the engine catalog has, for extensions.
* ``TestTheImageProblem`` — ``CREATE EXTENSION vector`` is a *correct*
  statement that fails on stock ``postgres:16``. Nothing here may reach the
  engine without first establishing that the image can load the extension.

No Docker: every executor is stubbed, and the stubs record exactly which
statements would have been run so "it never executed the statement" is a real
assertion rather than a hope.
"""
import json
import os

import pytest
import yaml

from app import db
from app.models import Application, User
from app.services import database_engine_extension_service as ext
from app.services.template_service import TemplateService

EXTENSIONS_DIR = os.path.join(TemplateService.LOCAL_TEMPLATES_DIR,
                              TemplateService.EXTENSIONS_SUBDIR)
TEMPLATES_DIR = TemplateService.LOCAL_TEMPLATES_DIR

# A complete extension, written into backend/templates/extensions/ by a fixture.
NEW_EXTENSION_YAML = """\
id: probe_ext
name: ProbeExt
version: "3.1"
description: An extension that exists only for this test
extension:
  protocol: postgresql
  statement: CREATE EXTENSION IF NOT EXISTS probe_ext;
  available_query: SELECT 1 FROM pg_available_extensions WHERE name = 'probe_ext';
  installed_query: SELECT extversion FROM pg_extension WHERE extname = 'probe_ext';
  images:
    - probe/postgres-probe
  image_hint: probe/postgres-probe:pg{version}
  size: 1 MB
  unit: probes
  versions:
    - "3.1"
    - "3.0"
"""

# An engine template whose image ships the extension above — proving the
# "install this instead" remedy is discovered, not hardcoded.
CAPABLE_ENGINE_YAML = """\
id: probe-capable-pg
name: Probe-capable PostgreSQL
version: "16"
description: PostgreSQL on an image that ships ProbeExt
icon: https://serverkit.ai/imgs/template-icons/postgresql.svg
categories:
  - database
engine:
  family: Relational
  protocol: postgresql
  default_port: 55432
  admin_user: postgres
  admin_password_var: DB_PASSWORD
  port_var: PORT
  bind_var: BIND_ADDRESS
  unit: tables
  client: psql
  data_path: /var/lib/postgresql/data
  extensions: true
  version_var: IMAGE_TAG
  versions:
    - "16"
variables:
  - name: IMAGE_TAG
    type: string
    default: "16"
    hidden: true
  - name: PORT
    type: port
    default: "55432"
  - name: BIND_ADDRESS
    type: string
    default: 127.0.0.1
    hidden: true
  - name: DB_PASSWORD
    type: password
    length: 28
compose:
  services:
    app:
      image: probe/postgres-probe:pg${IMAGE_TAG}
      container_name: ${APP_NAME}
      restart: unless-stopped
      ports:
        - "${BIND_ADDRESS}:${PORT}:5432"
      environment:
        POSTGRES_PASSWORD: "${DB_PASSWORD}"
        POSTGRES_USER: postgres
      volumes:
        - probe-capable-data:/var/lib/postgresql/data
  volumes:
    probe-capable-data:
"""


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def offline_templates(monkeypatch):
    """Hermetic: no remote repos, no `docker ps`, no `docker inspect`."""
    monkeypatch.setattr(TemplateService, 'get_config',
                        classmethod(lambda cls: {'repos': [], 'installed': {}}))
    monkeypatch.setattr(TemplateService, '_get_docker_used_ports',
                        classmethod(lambda cls: set()))
    monkeypatch.setattr(TemplateService, '_managed_app_base_port',
                        classmethod(lambda cls: 0))


@pytest.fixture
def new_extension_yaml():
    """Drop a brand-new extension into the extensions directory, then remove it.

    No registration, no import, no code change — the whole design.
    """
    path = os.path.join(EXTENSIONS_DIR, 'probe_ext.yaml')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(NEW_EXTENSION_YAML)
    try:
        yield 'probe_ext'
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture
def capable_engine_yaml():
    """An engine template whose image ships ProbeExt."""
    path = os.path.join(TEMPLATES_DIR, 'probe-capable-pg.yaml')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(CAPABLE_ENGINE_YAML)
    try:
        yield 'probe-capable-pg'
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture
def viewer_headers(app):
    """A logged-in NON-admin, for the admin-only checks."""
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    user = User(email='extviewer@test.local', username='extviewer',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_DEVELOPER, is_active=True)
    db.session.add(user)
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


def _install_engine(tmp_path, monkeypatch, *, template_id='postgresql',
                    name='pg-main', image='postgres:16-alpine', variables=None):
    """An Application that looks exactly like a finished engine install.

    The rendered compose is written for real, because that file is where the
    image an instance runs is read from.
    """
    root = tmp_path / name
    root.mkdir()
    (root / '.serverkit-template.json').write_text(json.dumps({
        'template_id': template_id,
        'template_version': '16',
        'variables': variables or {'PORT': '5433', 'BIND_ADDRESS': '127.0.0.1',
                                   'IMAGE_TAG': '16', 'DB_NAME': 'shop',
                                   'DB_PASSWORD': 'sup3rs3cret-do-not-leak'},
    }), encoding='utf-8')
    if image:
        (root / 'docker-compose.yml').write_text(yaml.safe_dump({
            'services': {'app': {'image': image, 'container_name': name}},
        }), encoding='utf-8')

    application = Application(name=name, app_type='docker', status='running',
                              user_id=1, port=5433, root_path=str(root))
    db.session.add(application)
    db.session.commit()
    monkeypatch.setattr(TemplateService, 'get_config', classmethod(
        lambda cls: {'repos': [], 'installed': {
            str(application.id): {'template_id': template_id}}}))
    return application


class FakeEngine:
    """Records every statement, answers the ones a test declares.

    Defaults to "the extension is not available", which is what a stock
    postgres image really says.
    """

    def __init__(self, *, available=False, installed_version='', fail=None):
        self.available = available
        self.installed_version = installed_version
        self.fail = fail
        self.statements = []

    def __call__(self, context, sql, database):
        self.statements.append((sql, database))
        if self.fail is not None:
            return {'success': False, 'error': self.fail}
        if 'pg_available_extensions' in sql:
            return {'success': True, 'output': '1\n' if self.available else '\n'}
        if 'pg_extension' in sql:
            return {'success': True, 'output': self.installed_version}
        return {'success': True, 'output': ''}

    @property
    def ran_create(self):
        return any(s.upper().startswith('CREATE EXTENSION') for s, _ in self.statements)


@pytest.fixture
def engine_client(monkeypatch):
    """Install a FakeEngine as the postgresql executor and hand it back."""
    def _install(**kwargs):
        fake = FakeEngine(**kwargs)
        monkeypatch.setitem(ext.EXECUTORS, 'postgresql', fake)
        return fake
    return _install


def _post(client, headers, app_id, **body):
    return client.post(f'/api/v1/databases/engines/{app_id}/extensions',
                       json=body, headers=headers)


# ── the design proof ─────────────────────────────────────────────────────────
class TestZeroCodeChangeCatalog:

    def test_dropping_a_new_extension_yaml_lists_it(self, client, auth_headers,
                                                    new_extension_yaml):
        """A new extension YAML appears in the catalog with NO code change."""
        response = client.get('/api/v1/databases/engines/extensions',
                              headers=auth_headers)
        assert response.status_code == 200

        entry = next((e for e in response.get_json()['extensions']
                      if e['id'] == 'probe_ext'), None)
        assert entry is not None, 'a new extension file must appear with no code change'
        assert entry['name'] == 'ProbeExt'
        assert entry['statement'] == 'CREATE EXTENSION IF NOT EXISTS probe_ext;'
        assert entry['protocol'] == 'postgresql'
        assert entry['images'] == ['probe/postgres-probe']
        assert entry['versions'] == ['3.1', '3.0']
        assert entry['family'] == 'Extension'

    def test_extension_removed_when_yaml_is_removed(self, client, auth_headers):
        """The catalog is derived, not cached: no YAML, no entry."""
        data = client.get('/api/v1/databases/engines/extensions',
                          headers=auth_headers).get_json()
        assert 'probe_ext' not in {e['id'] for e in data['extensions']}

    def test_a_new_extension_is_immediately_installable(
            self, client, auth_headers, tmp_path, monkeypatch,
            new_extension_yaml, engine_client):
        """...and installing it needs no code either."""
        fake = engine_client(available=True, installed_version='3.1')
        application = _install_engine(tmp_path, monkeypatch,
                                      image='probe/postgres-probe:pg16')
        response = _post(client, auth_headers, application.id,
                         extension_id='probe_ext', database='shop')
        assert response.status_code == 201, response.get_json()
        assert fake.ran_create
        assert response.get_json()['extension']['version'] == '3.1'

    def test_a_new_engine_yaml_becomes_a_host_with_no_code_change(
            self, client, auth_headers, new_extension_yaml, capable_engine_yaml):
        """Compatibility is matched on the engine's OWN protocol.

        Neither file names the other, so an engine template dropped in later is
        offered as a host — and as the remedy, because its image ships it.
        """
        data = client.get('/api/v1/databases/engines/extensions',
                          headers=auth_headers).get_json()
        entry = next(e for e in data['extensions'] if e['id'] == 'probe_ext')
        hosts = {h['template_id'] for h in entry['hosts']}
        assert 'postgresql' in hosts          # protocol match, image does not ship it
        assert 'probe-capable-pg' in hosts
        assert entry['provided_by'] == ['probe-capable-pg']

    def test_bundled_extensions_are_the_ones_shipped(self, client, auth_headers):
        data = client.get('/api/v1/databases/engines/extensions',
                          headers=auth_headers).get_json()
        assert {'pgvector', 'timescaledb'} <= {e['id'] for e in data['extensions']}

    def test_extensions_are_not_app_templates(self, app):
        """They have no container, so they must never reach the app catalog."""
        ids = {t['id'] for t in TemplateService.list_all_templates()}
        assert 'pgvector' not in ids
        assert 'timescaledb' not in ids


# ── the extension block: loader + validator ──────────────────────────────────
class TestExtensionBlockPlumbing:

    def test_shipped_extensions_all_validate(self, app):
        for filename in os.listdir(EXTENSIONS_DIR):
            if not filename.endswith(('.yaml', '.yml')):
                continue
            with open(os.path.join(EXTENSIONS_DIR, filename), encoding='utf-8') as fh:
                document = yaml.safe_load(fh)
            result = TemplateService.validate_extension(document)
            assert result['valid'], (filename, result['errors'])
            assert document['id'] == filename.rsplit('.', 1)[0], filename

    def test_statement_is_required(self, app):
        result = TemplateService.validate_extension({
            'name': 'x', 'version': '1', 'description': 'd',
            'extension': {'protocol': 'postgresql'}})
        assert not result['valid']
        assert any('statement' in e for e in result['errors'])

    def test_protocol_must_be_a_known_one(self, app):
        result = TemplateService.validate_extension({
            'name': 'x', 'version': '1', 'description': 'd',
            'extension': {'protocol': 'telepathy', 'statement': 'SELECT 1;'}})
        assert not result['valid']
        assert any('telepathy' in e for e in result['errors'])

    def test_protocol_none_cannot_host_an_extension(self, app):
        """`protocol: none` is legitimate for an ENGINE and meaningless here."""
        result = TemplateService.validate_extension({
            'name': 'x', 'version': '1', 'description': 'd',
            'extension': {'protocol': 'none', 'statement': 'SELECT 1;'}})
        assert not result['valid']

    def test_an_extension_may_not_declare_a_container(self, app):
        """The distinction from an engine, enforced rather than documented."""
        result = TemplateService.validate_extension({
            'name': 'x', 'version': '1', 'description': 'd',
            'extension': {'protocol': 'postgresql', 'statement': 'SELECT 1;'},
            'compose': {'services': {'app': {'image': 'x'}}}})
        assert not result['valid']
        assert any('compose' in e for e in result['errors'])

    def test_a_broken_file_is_skipped_not_fatal(self, app):
        """One malformed extension must not take the catalog down with it."""
        path = os.path.join(EXTENSIONS_DIR, 'broken_ext.yaml')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('name: Broken\nextension: not-a-mapping\n')
        try:
            ids = {e['id'] for e in TemplateService.list_extension_templates()}
            assert 'broken_ext' not in ids
            assert 'pgvector' in ids
        finally:
            os.remove(path)

    def test_catalog_schema_documents_the_extension_block(self, client, auth_headers):
        schema = client.get('/api/v1/templates/catalog/schema',
                            headers=auth_headers).get_json()
        block = schema['extension_block']
        assert block['family'] == 'Extension'
        assert 'none' not in block['protocols']
        fields = {f['field'] for f in block['fields']}
        assert {'protocol', 'statement', 'images', 'available_query'} <= fields


# ── compatibility ────────────────────────────────────────────────────────────
class TestCompatibility:

    def test_extension_is_only_offered_for_engines_that_can_host_it(
            self, client, auth_headers):
        """pgvector is a PostgreSQL extension; MongoDB may not be offered it."""
        data = client.get('/api/v1/databases/engines/extensions',
                          headers=auth_headers).get_json()
        entry = next(e for e in data['extensions'] if e['id'] == 'pgvector')
        hosts = {h['template_id'] for h in entry['hosts']}
        assert 'postgresql' in hosts
        assert 'postgresql-pgvector' in hosts
        assert 'mongodb' not in hosts
        assert 'mysql' not in hosts
        assert 'redis' not in hosts

    def test_speaking_the_protocol_is_not_enough(self, client, auth_headers):
        """CockroachDB answers on the PostgreSQL wire and has no extensions.

        Offering pgvector for it would send an operator to an image that cannot
        exist, so an engine has to declare `engine.extensions: true` -- which
        keeps CockroachDB out without anything in Python naming it.
        """
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        cockroach = next(e for e in data['catalog'] if e['id'] == 'cockroachdb')
        assert cockroach['engine']['protocol'] == 'postgresql'
        assert cockroach['engine']['supports_extensions'] is False

        entry = next(e for e in data['extensions'] if e['id'] == 'pgvector')
        assert 'cockroachdb' not in {h['template_id'] for h in entry['hosts']}

    def test_installing_into_an_engine_without_extension_support_is_refused(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        fake = engine_client(available=True)
        application = _install_engine(tmp_path, monkeypatch, template_id='cockroachdb',
                                      name='crdb', image='cockroachdb/cockroach:latest-v24.1')
        response = _post(client, auth_headers, application.id, extension_id='pgvector')
        assert response.status_code == 400
        assert 'does not support database extensions' in response.get_json()['error']
        assert not fake.statements

    def test_installing_into_the_wrong_engine_is_refused(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        fake = engine_client(available=True)
        application = _install_engine(tmp_path, monkeypatch, template_id='mongodb',
                                      name='mongo-main', image='mongo:7.0')
        response = _post(client, auth_headers, application.id, extension_id='pgvector')
        assert response.status_code == 400
        body = response.get_json()
        assert 'postgresql' in body['error']
        assert 'postgresql' in body['hosts']
        assert not fake.statements, 'a wrong-engine install must not reach any engine'

    def test_a_compatible_instance_is_listed_as_such(
            self, client, auth_headers, tmp_path, monkeypatch):
        _install_engine(tmp_path, monkeypatch, template_id='postgresql-pgvector',
                        name='pgv', image='pgvector/pgvector:pg16')
        data = client.get('/api/v1/databases/engines/extensions',
                          headers=auth_headers).get_json()
        entry = next(e for e in data['extensions'] if e['id'] == 'pgvector')
        assert entry['compatible_instances']
        assert not entry['incompatible_instances']

    def test_instance_listing_judges_every_extension(
            self, client, auth_headers, tmp_path, monkeypatch):
        application = _install_engine(tmp_path, monkeypatch)
        data = client.get(f'/api/v1/databases/engines/{application.id}/extensions',
                          headers=auth_headers).get_json()
        by_id = {e['id']: e for e in data['extensions']}
        assert by_id['pgvector']['status'] == ext.STATUS_IMAGE_UNSUPPORTED
        assert data['instance']['protocol'] == 'postgresql'
        assert data['probed'] is False
        # The secret never leaves the install record.
        assert 'sup3rs3cret-do-not-leak' not in json.dumps(data)

    def test_instance_listing_404s_for_a_non_engine_app(
            self, client, auth_headers, tmp_path, monkeypatch):
        application = _install_engine(tmp_path, monkeypatch, template_id='gitea',
                                      name='git', image='gitea/gitea:1')
        response = client.get(f'/api/v1/databases/engines/{application.id}/extensions',
                              headers=auth_headers)
        assert response.status_code == 404

    def test_unknown_instance_is_404(self, client, auth_headers):
        assert client.get('/api/v1/databases/engines/9999/extensions',
                          headers=auth_headers).status_code == 404


# ── THE image problem ────────────────────────────────────────────────────────
class TestTheImageProblem:
    """`CREATE EXTENSION vector` is correct SQL that fails on stock postgres.

    Every test here exists so that failure can never be silent:

        ERROR:  could not open extension control file
                "/usr/share/postgresql/16/extension/vector.control"
    """

    def test_stock_postgres_is_marked_incompatible_before_anything_is_clicked(
            self, client, auth_headers, tmp_path, monkeypatch):
        application = _install_engine(tmp_path, monkeypatch, image='postgres:16-alpine')
        data = client.get(f'/api/v1/databases/engines/{application.id}/extensions',
                          headers=auth_headers).get_json()
        entry = next(e for e in data['extensions'] if e['id'] == 'pgvector')
        assert entry['status'] == ext.STATUS_IMAGE_UNSUPPORTED
        assert 'postgres:16-alpine' in entry['reason']
        assert entry['remedy']['suggested_image'] == 'pgvector/pgvector:pg16'
        assert entry['remedy']['required_images'] == ['pgvector/pgvector']

    def test_the_remedy_names_an_engine_template_that_can_host_it(
            self, client, auth_headers, tmp_path, monkeypatch):
        """Discovered by matching images, not by naming a template in Python."""
        application = _install_engine(tmp_path, monkeypatch, image='postgres:16-alpine')
        data = client.get(f'/api/v1/databases/engines/{application.id}/extensions',
                          headers=auth_headers).get_json()
        remedy = next(e for e in data['extensions'] if e['id'] == 'pgvector')['remedy']
        assert 'postgresql-pgvector' in {h['template_id'] for h in remedy['install_instead']}

    def test_install_refuses_and_never_runs_the_statement(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        """The engine says it cannot load it, so CREATE EXTENSION is not sent."""
        fake = engine_client(available=False)
        application = _install_engine(tmp_path, monkeypatch, image='postgres:16-alpine')
        response = _post(client, auth_headers, application.id,
                         extension_id='pgvector', database='shop')
        assert response.status_code == 409
        body = response.get_json()
        assert 'does not ship the extension' in body['error']
        assert body['remedy']['suggested_image'] == 'pgvector/pgvector:pg16'
        assert body['remedy']['install_instead'][0]['image'] == 'pgvector/pgvector'
        # The transport code is the status, not part of the body.
        assert 'status_code' not in body
        assert not fake.ran_create, 'refused installs must not execute the statement'

    def test_a_capable_image_installs(self, client, auth_headers, tmp_path,
                                      monkeypatch, engine_client):
        fake = engine_client(available=True, installed_version='0.8.0')
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        response = _post(client, auth_headers, application.id,
                         extension_id='pgvector', database='shop')
        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        assert body['status'] == ext.STATUS_INSTALLED
        assert body['statement'] == 'CREATE EXTENSION IF NOT EXISTS vector;'
        assert body['database'] == 'shop'
        assert body['extension']['version'] == '0.8.0'
        assert fake.ran_create

    def test_the_engine_overrules_the_image_name_when_it_says_yes(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        """An operator's own build is not punished for an unfamiliar name.

        The probe is authoritative in both directions; this is the direction
        that keeps the image list from becoming a false blocker.
        """
        fake = engine_client(available=True, installed_version='0.8.0')
        application = _install_engine(tmp_path, monkeypatch,
                                      image='registry.internal/ops/pg-with-vector:16')
        response = _post(client, auth_headers, application.id, extension_id='pgvector')
        assert response.status_code == 201, response.get_json()
        assert fake.ran_create

    def test_the_engine_overrules_the_image_name_when_it_says_no(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        """...and a matching name is not a licence to skip the check.

        A ``pgvector/pgvector`` tag that predates the extension, or a mangled
        image, must still be refused rather than trusted by its name.
        """
        fake = engine_client(available=False)
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        response = _post(client, auth_headers, application.id, extension_id='pgvector')
        assert response.status_code == 409
        assert not fake.ran_create

    def test_an_unreachable_engine_does_not_downgrade_a_known_no(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        """A stopped container must not turn "cannot" into "maybe"."""
        engine_client(fail='Error: No such container: pg-main')
        application = _install_engine(tmp_path, monkeypatch, image='postgres:16-alpine')
        response = _post(client, auth_headers, application.id, extension_id='pgvector')
        assert response.status_code == 409
        assert response.get_json()['status'] == ext.STATUS_IMAGE_UNSUPPORTED

    def test_an_unreachable_capable_engine_is_reported_as_unreachable(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        """Not a 409 with a remedy: the image is fine, the engine is down."""
        fake = engine_client(fail='Error: No such container: pgv')
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        response = _post(client, auth_headers, application.id, extension_id='pgvector')
        assert response.status_code == 502
        assert 'Could not reach' in response.get_json()['error']
        assert not fake.ran_create

    def test_a_rejected_statement_surfaces_the_engines_own_error(
            self, client, auth_headers, tmp_path, monkeypatch, monkeypatch_free=None):
        """If it fails anyway, the operator sees why — not a generic failure."""
        control_file_error = ('ERROR:  could not open extension control file '
                              '"/usr/share/postgresql/16/extension/vector.control"')

        def executor(context, sql, database):
            if 'pg_available_extensions' in sql:
                return {'success': True, 'output': '1\n'}
            return {'success': False, 'error': control_file_error}

        monkeypatch.setitem(ext.EXECUTORS, 'postgresql', executor)
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        response = _post(client, auth_headers, application.id, extension_id='pgvector')
        assert response.status_code == 400
        assert 'control file' in response.get_json()['error']

    def test_timescaledb_has_no_bundled_host_and_says_so(self, client, auth_headers,
                                                         tmp_path, monkeypatch):
        """We ship no timescale image, and the catalog is honest about it."""
        _install_engine(tmp_path, monkeypatch, image='postgres:16-alpine')
        data = client.get('/api/v1/databases/engines/extensions',
                          headers=auth_headers).get_json()
        entry = next(e for e in data['extensions'] if e['id'] == 'timescaledb')
        assert entry['hosts'], 'postgres engines can still host it in principle'
        assert entry['provided_by'] == [], 'no bundled engine ships timescaledb'
        assert entry['compatible_instances'] == []


class TestImageReferenceMatching:
    """The image comparison itself — five spellings of the same image."""

    @pytest.mark.parametrize('image', [
        'pgvector/pgvector:pg16',
        'pgvector/pgvector',
        'docker.io/pgvector/pgvector:pg16',
        'pgvector/pgvector@sha256:' + 'a' * 64,
        'registry.example.com:5000/pgvector/pgvector:pg16',
    ])
    def test_equivalent_references_match(self, image):
        assert ext._image_provides(image, ['pgvector/pgvector']) is True

    @pytest.mark.parametrize('image', ['postgres:16-alpine', 'postgres', 'mysql:8'])
    def test_unrelated_images_do_not_match(self, image):
        assert ext._image_provides(image, ['pgvector/pgvector']) is False

    def test_an_unresolvable_image_is_not_a_no(self):
        """Unknown is a third answer, so we never claim an image cannot host it."""
        assert ext._image_provides(None, ['pgvector/pgvector']) is None

    def test_no_declared_images_means_no_image_claim(self):
        assert ext._image_provides('anything:1', []) is True

    def test_image_is_read_from_the_rendered_compose(self, app, tmp_path, monkeypatch):
        application = _install_engine(tmp_path, monkeypatch, image='postgres:15-alpine')
        assert ext.instance_image(application) == 'postgres:15-alpine'


# ── rejection paths ──────────────────────────────────────────────────────────
class TestRejections:

    def test_unknown_extension_is_404(self, client, auth_headers, tmp_path,
                                      monkeypatch, engine_client):
        fake = engine_client(available=True)
        application = _install_engine(tmp_path, monkeypatch)
        response = _post(client, auth_headers, application.id,
                         extension_id='definitely-not-an-extension')
        assert response.status_code == 404
        body = response.get_json()
        assert 'Unknown extension' in body['error']
        assert 'pgvector' in body['available']
        assert not fake.statements

    def test_extension_id_is_required(self, client, auth_headers, tmp_path, monkeypatch):
        application = _install_engine(tmp_path, monkeypatch)
        assert _post(client, auth_headers, application.id).status_code == 404

    def test_unknown_instance_is_404(self, client, auth_headers):
        assert _post(client, auth_headers, 4242, extension_id='pgvector').status_code == 404

    def test_a_bad_database_name_is_refused(self, client, auth_headers, tmp_path,
                                            monkeypatch, engine_client):
        fake = engine_client(available=True)
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        response = _post(client, auth_headers, application.id,
                         extension_id='pgvector', database='shop; DROP DATABASE x')
        assert response.status_code == 400
        assert not fake.statements

    def test_the_statement_comes_from_the_yaml_not_the_request(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        """A caller cannot smuggle SQL through this route."""
        fake = engine_client(available=True, installed_version='0.8.0')
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        response = client.post(
            f'/api/v1/databases/engines/{application.id}/extensions',
            json={'extension_id': 'pgvector', 'statement': 'DROP DATABASE shop;'},
            headers=auth_headers)
        assert response.status_code == 201
        assert not any('DROP DATABASE' in sql for sql, _ in fake.statements)


class TestAdminOnly:
    """Mutations are admin-only, matching the engine install route."""

    def test_install_rejects_a_non_admin(self, client, viewer_headers, tmp_path,
                                         monkeypatch, engine_client):
        fake = engine_client(available=True)
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        response = _post(client, viewer_headers, application.id, extension_id='pgvector')
        assert response.status_code == 403
        assert not fake.statements

    def test_install_rejects_anonymous(self, client, tmp_path, monkeypatch):
        application = _install_engine(tmp_path, monkeypatch)
        assert _post(client, {}, application.id, extension_id='pgvector').status_code == 401

    def test_reading_the_catalog_requires_auth(self, client):
        assert client.get('/api/v1/databases/engines/extensions').status_code == 401

    def test_reading_the_catalog_does_not_require_admin(self, client, viewer_headers):
        assert client.get('/api/v1/databases/engines/extensions',
                          headers=viewer_headers).status_code == 200


# ── the engine listing carries them too ──────────────────────────────────────
class TestEngineListingIncludesExtensions:

    def test_the_engine_catalog_response_carries_extensions(self, client, auth_headers):
        """One round trip for the drawer, which renders both."""
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert {'pgvector', 'timescaledb'} <= {e['id'] for e in data['extensions']}
        assert data['extension_family'] == 'Extension'

    def test_extensions_do_not_pollute_the_engine_family_filter(self, client, auth_headers):
        """`families` stays what it was: the families engines actually have."""
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert 'Extension' not in data['families']

    def test_extensions_are_not_in_the_engine_catalog(self, client, auth_headers):
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert 'pgvector' not in {e['id'] for e in data['catalog']}


# ── probing ──────────────────────────────────────────────────────────────────
class TestProbing:

    def test_probe_reports_what_is_already_installed(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        engine_client(available=True, installed_version='0.8.0')
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        data = client.get(
            f'/api/v1/databases/engines/{application.id}/extensions?probe=true',
            headers=auth_headers).get_json()
        entry = next(e for e in data['extensions'] if e['id'] == 'pgvector')
        assert data['probed'] is True
        assert entry['status'] == ext.STATUS_INSTALLED
        assert entry['installed_version'] == '0.8.0'

    def test_probe_reports_ready_when_available_but_absent(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        engine_client(available=True, installed_version='')
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        data = client.get(
            f'/api/v1/databases/engines/{application.id}/extensions?probe=true',
            headers=auth_headers).get_json()
        entry = next(e for e in data['extensions'] if e['id'] == 'pgvector')
        assert entry['status'] == ext.STATUS_READY
        assert entry['installed_version'] is None

    def test_not_probing_costs_no_engine_calls(
            self, client, auth_headers, tmp_path, monkeypatch, engine_client):
        fake = engine_client(available=True)
        application = _install_engine(tmp_path, monkeypatch,
                                      template_id='postgresql-pgvector', name='pgv',
                                      image='pgvector/pgvector:pg16')
        client.get(f'/api/v1/databases/engines/{application.id}/extensions',
                   headers=auth_headers)
        assert not fake.statements
