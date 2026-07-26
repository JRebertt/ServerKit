"""Database engines = app templates carrying an ``engine:`` block.

The load-bearing test in this file is ``test_dropping_a_new_engine_yaml_lists_it``:
a brand-new engine becomes installable by adding a YAML file, with no Python
change anywhere. Everything else guards the safety rules around that.

Nothing here pulls an image or starts a container: installs stop at the
deployment-job row (``wait=False``), and the docker port probes are stubbed.
"""
import json
import os
import re

import pytest
import yaml

from app import db
from app.models import Application, User
from app.services import database_engine_service as engines
from app.services.template_service import TemplateService

TEMPLATES_DIR = TemplateService.LOCAL_TEMPLATES_DIR

# A complete engine template, written to backend/templates/ by the fixture below.
NEW_ENGINE_YAML = """\
id: probedb
name: ProbeDB
version: "1.0"
description: A database that exists only for this test
categories:
  - database
engine:
  family: Document
  protocol: none
  default_port: 61234
  admin_user: root
  admin_password_var: DB_PASSWORD
  database_var: DB_NAME
  port_var: PORT
  bind_var: BIND_ADDRESS
  unit: collections
  client: probe-cli
  data_path: /probe/data
  version_var: IMAGE_TAG
  versions:
    - "1.0"
    - "0.9"
variables:
  - name: IMAGE_TAG
    type: string
    default: "1.0"
    hidden: true
  - name: PORT
    type: port
    default: "61234"
    hidden: false
  - name: BIND_ADDRESS
    type: string
    default: 127.0.0.1
    hidden: true
  - name: DB_PASSWORD
    type: password
    length: 28
  - name: DB_NAME
    type: string
    default: probe
compose:
  services:
    app:
      image: probe/probedb:${IMAGE_TAG}
      container_name: ${APP_NAME}
      restart: unless-stopped
      ports:
        - "${BIND_ADDRESS}:${PORT}:61234"
      environment:
        PROBE_PASSWORD: "${DB_PASSWORD}"
        PROBE_DB: "${DB_NAME}"
      volumes:
        - probedb-data:/probe/data
  volumes:
    probedb-data:
"""


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def offline_templates(monkeypatch):
    """Keep the suite hermetic and fast.

    ``list_all_templates`` fans out to every configured remote repo, and the
    port helpers shell out to ``docker ps``. Neither belongs in a unit test.
    """
    monkeypatch.setattr(TemplateService, 'get_config',
                        classmethod(lambda cls: {'repos': [], 'installed': {}}))
    monkeypatch.setattr(TemplateService, '_get_docker_used_ports',
                        classmethod(lambda cls: set()))
    monkeypatch.setattr(TemplateService, '_managed_app_base_port',
                        classmethod(lambda cls: 0))
    # No docker on the test host; never let a listing block on `docker inspect`.
    monkeypatch.setattr(engines, '_container_state', lambda app: None)


@pytest.fixture
def new_engine_yaml():
    """Drop a brand-new engine template into backend/templates/, then remove it.

    This is the whole design: no registration, no import, no code change.
    """
    path = os.path.join(TEMPLATES_DIR, 'probedb.yaml')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(NEW_ENGINE_YAML)
    try:
        yield 'probedb'
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture
def viewer_headers(app):
    """A logged-in NON-admin, for the admin-only checks."""
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    user = User(email='viewer@test.local', username='viewer',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_DEVELOPER, is_active=True)
    db.session.add(user)
    db.session.commit()
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


def _install(client, headers, **body):
    return client.post('/api/v1/databases/engines', json=body, headers=headers)


# ── the design proof ─────────────────────────────────────────────────────────
class TestZeroCodeChangeCatalog:

    def test_dropping_a_new_engine_yaml_lists_it(self, client, auth_headers, new_engine_yaml):
        """A new engine YAML appears in the catalog with NO code change."""
        response = client.get('/api/v1/databases/engines', headers=auth_headers)
        assert response.status_code == 200

        catalog = response.get_json()['catalog']
        entry = next((e for e in catalog if e['id'] == 'probedb'), None)
        assert entry is not None, 'a new engine template must appear with no code change'
        assert entry['name'] == 'ProbeDB'
        # Its engine metadata came through the loader intact.
        assert entry['engine']['family'] == 'Document'
        assert entry['engine']['unit'] == 'collections'
        assert entry['engine']['data_path'] == '/probe/data'
        assert entry['engine']['versions'] == ['1.0', '0.9']
        assert entry['installed_count'] == 0

    def test_new_engine_is_immediately_installable(self, client, auth_headers, new_engine_yaml):
        """...and installing it goes through the ordinary template pipeline."""
        response = _install(client, auth_headers, template_id='probedb',
                            instance_name='probedb-one')
        assert response.status_code == 202, response.get_json()
        assert response.get_json()['job_id']

    def test_engine_removed_when_yaml_is_removed(self, client, auth_headers):
        """The catalog is derived, not cached: no YAML, no entry."""
        response = client.get('/api/v1/databases/engines', headers=auth_headers)
        ids = [e['id'] for e in response.get_json()['catalog']]
        assert 'probedb' not in ids

    def test_non_engine_templates_are_excluded(self, client, auth_headers):
        """106 templates ship; only the ones declaring `engine:` are listed."""
        response = client.get('/api/v1/databases/engines', headers=auth_headers)
        catalog = response.get_json()['catalog']
        ids = {e['id'] for e in catalog}
        assert 'gitea' not in ids            # an app, not an engine
        assert 'redis-commander' not in ids  # an admin UI, not an engine
        assert 'postgresql' in ids
        assert 'cockroachdb' in ids
        assert all(isinstance(e.get('engine'), dict) for e in catalog)


# ── catalog shape ────────────────────────────────────────────────────────────
class TestCatalog:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/databases/engines').status_code == 401

    def test_ships_the_expected_engines(self, client, auth_headers):
        response = client.get('/api/v1/databases/engines', headers=auth_headers)
        assert response.status_code == 200
        ids = {e['id'] for e in response.get_json()['catalog']}
        expected = {'postgresql', 'mysql', 'mariadb', 'mongodb', 'redis', 'valkey',
                    'cockroachdb', 'clickhouse', 'influxdb', 'neo4j',
                    'meilisearch', 'couchdb'}
        assert expected <= ids

    def test_families_are_derived_from_the_response(self, client, auth_headers):
        """The UI must not need its own family list."""
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        families = set(data['families'])
        assert {'Relational', 'Document', 'Key-value', 'Search'} <= families
        # Only families actually present are offered as filters.
        present = {(e['engine'] or {}).get('family') for e in data['catalog']}
        assert families <= present

    def test_installed_is_empty_without_apps(self, client, auth_headers):
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert data['installed'] == []

    def test_catalog_does_not_leak_server_paths(self, client, auth_headers):
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert all('filepath' not in e for e in data['catalog'])


# ── loader / validator (the `engine:` block plumbing) ────────────────────────
class TestEngineBlockPlumbing:

    def test_loader_carries_engine_through_the_listing(self, app, new_engine_yaml):
        """`list_local_templates` used to project a fixed field set and drop it."""
        entry = next(t for t in TemplateService.list_local_templates()
                     if t['id'] == 'probedb')
        assert entry['engine']['protocol'] == 'none'

    def test_repo_index_carries_engine(self, app, new_engine_yaml):
        """A panel syncing this repo can list engines without fetching each YAML."""
        index = TemplateService.build_repo_index()
        entry = next(t for t in index['templates'] if t['id'] == 'probedb')
        assert entry['engine']['family'] == 'Document'

    def test_validator_accepts_a_template_without_an_engine_block(self, app):
        result = TemplateService.get_template('gitea')
        assert result['success']
        assert TemplateService.engine_metadata(result['template']) is None
        assert TemplateService.validate_template(result['template'])['valid']

    def test_validator_rejects_a_malformed_engine_block(self, app):
        bad = {'name': 'x', 'version': '1', 'description': 'd',
               'compose': {'services': {}},
               'engine': {'family': 'Nonsense', 'protocol': 'telepathy',
                          'default_port': 99999}}
        result = TemplateService.validate_template(bad)
        assert not result['valid']
        joined = ' '.join(result['errors'])
        assert 'engine.family' in joined
        assert 'engine.protocol' in joined
        assert 'engine.default_port' in joined

    def test_validator_rejects_a_non_mapping_engine_block(self, app):
        bad = {'name': 'x', 'version': '1', 'description': 'd',
               'compose': {'services': {}}, 'engine': 'yes please'}
        assert not TemplateService.validate_template(bad)['valid']

    def test_catalog_entry_warns_about_variables_that_do_not_exist(self, app):
        entry = {'id': 'x', 'name': 'x', 'version': '1', 'description': 'd',
                 'compose': {'services': {}},
                 'variables': [{'name': 'PORT', 'type': 'port'}],
                 'engine': {'family': 'Relational', 'admin_password_var': 'NOPE'}}
        result = TemplateService.validate_catalog_entry(entry)
        assert result['valid']  # a warning, not a hard failure
        assert any('NOPE' in w for w in result['warnings'])

    def test_catalog_schema_documents_the_engine_block(self, client, auth_headers):
        schema = client.get('/api/v1/templates/catalog/schema',
                            headers=auth_headers).get_json()
        assert schema['engine_block']['optional'] is True
        assert 'Relational' in schema['engine_block']['families']
        assert 'none' in schema['engine_block']['protocols']
        fields = {f['field'] for f in schema['engine_block']['fields']}
        assert {'family', 'protocol', 'admin_password_var', 'data_path'} <= fields

    def test_shipped_engine_templates_all_validate(self, app):
        """Every engine we ship parses, validates and declares what it promises."""
        for entry in TemplateService.list_local_templates():
            if not entry.get('engine'):
                continue
            fetched = TemplateService.get_template(entry['id'])
            assert fetched['success'], entry['id']
            template = fetched['template']
            assert TemplateService.validate_template(template)['valid'], entry['id']
            result = TemplateService.validate_catalog_entry(template)
            assert result['valid'], (entry['id'], result['errors'])
            assert not result['warnings'], (entry['id'], result['warnings'])


class TestShippedEngineTemplateSafety:
    """Safety rules 1 and 5 are properties of the template files themselves."""

    @staticmethod
    def _engine_templates():
        out = []
        for entry in TemplateService.list_local_templates():
            if entry.get('engine'):
                out.append((entry['id'], TemplateService.get_template(entry['id'])['template']))
        return out

    def test_every_published_port_binds_to_loopback(self, app):
        for template_id, template in self._engine_templates():
            for service in template['compose']['services'].values():
                for mapping in service.get('ports', []) or []:
                    assert str(mapping).startswith('${BIND_ADDRESS}:'), \
                        f'{template_id} publishes {mapping} without the private bind'

    def test_bind_address_defaults_to_loopback(self, app):
        for template_id, template in self._engine_templates():
            names = {v['name']: v for v in template['variables']}
            assert names['BIND_ADDRESS']['default'] == '127.0.0.1', template_id

    def test_every_engine_declares_a_named_data_volume(self, app):
        for template_id, template in self._engine_templates():
            assert template['compose'].get('volumes'), \
                f'{template_id} has no named volume; its data would not survive'

    def test_every_engine_restarts_unless_stopped(self, app):
        for template_id, template in self._engine_templates():
            for service in template['compose']['services'].values():
                assert service.get('restart') == 'unless-stopped', template_id

    def test_admin_secret_is_a_generated_variable(self, app):
        """The secret goes through the existing password path, not a literal."""
        for template_id, template in self._engine_templates():
            engine = TemplateService.engine_metadata(template)
            secret_var = engine.get('admin_password_var')
            if not secret_var:
                # CockroachDB single-node runs --insecure; it declares no secret.
                assert template_id == 'cockroachdb', template_id
                continue
            declared = {v['name']: v for v in template['variables']}
            assert declared[secret_var]['type'] in ('password', 'random'), template_id


# ── what running every engine for real taught us ─────────────────────────────
class TestShippedEngineTemplateWiring:
    """Invariants recovered by actually booting all twelve engines.

    Everything here is checkable from the YAML alone, and every one of these
    rules exists because getting it wrong produces an engine that *starts* and
    looks healthy while being unusable or -- worse -- wide open:

    * an admin secret that is generated but never handed to the image leaves
      MongoDB / ClickHouse / CouchDB booting with authentication DISABLED;
    * an ``engine.admin_user`` that disagrees with the user the compose block
      actually creates means the credential shown in the drawer cannot log in;
    * an ``engine.default_port`` that disagrees with the port variable makes
      the catalog advertise a port nothing listens on;
    * a ``version`` header that disagrees with the tag actually pulled makes
      the catalog advertise a release the operator does not get.
    """

    # Injected by the install pipeline rather than declared per template.
    PIPELINE_VARIABLES = {'APP_NAME'}

    @staticmethod
    def _engine_templates():
        return TestShippedEngineTemplateSafety._engine_templates()

    @staticmethod
    def _compose_text(template):
        """Everything an image can be configured by: compose + any ``files:``."""
        chunks = [yaml.safe_dump(template.get('compose', {}))]
        for file_def in template.get('files', []) or []:
            chunks.append(str(file_def.get('path', '')))
            chunks.append(str(file_def.get('content', '')))
        return '\n'.join(chunks)

    def test_admin_secret_reaches_the_image(self, app):
        """Declaring the secret is not enough -- the compose must USE it.

        MongoDB with only ``MONGO_INITDB_ROOT_PASSWORD``, ClickHouse without
        ``CLICKHOUSE_PASSWORD`` and CouchDB without ``COUCHDB_PASSWORD`` all
        start happily with auth switched off. A generated password that is
        never referenced is exactly that failure.
        """
        for template_id, template in self._engine_templates():
            secret_var = (TemplateService.engine_metadata(template)
                          .get('admin_password_var'))
            if not secret_var:
                continue
            assert '${%s}' % secret_var in self._compose_text(template), (
                f'{template_id} generates {secret_var} but never passes it to the '
                'image, so the engine would boot with authentication disabled'
            )

    def test_every_compose_variable_is_declared(self, app):
        """No ``${VAR}`` may reach docker compose without a declared value.

        An undeclared name survives substitution as the literal ``${VAR}`` and
        becomes, say, a password of ``${DB_PASSWD}`` -- which "works" until
        someone tries to connect.
        """
        pattern = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')
        for template_id, template in self._engine_templates():
            declared = {v['name'] for v in template.get('variables', [])}
            declared |= self.PIPELINE_VARIABLES
            used = set(pattern.findall(self._compose_text(template)))
            undeclared = used - declared
            assert not undeclared, \
                f'{template_id} uses undeclared variables: {sorted(undeclared)}'

    def test_no_published_port_binds_all_interfaces(self, app):
        """Rule 1 restated as a literal check, so a hardcoded bind cannot pass.

        ``test_every_published_port_binds_to_loopback`` asserts the prefix is
        the variable; this asserts nobody wrote the address inline.
        """
        for template_id, template in self._engine_templates():
            text = self._compose_text(template)
            for literal in ('0.0.0.0:', '::0:', '[::]:'):
                assert literal not in text, \
                    f'{template_id} publishes a port on {literal}'

    def test_engine_default_port_matches_the_port_variable(self, app):
        """The catalog's advertised port has to be the one that is published.

        Several engines deliberately sit off their upstream default (MariaDB on
        3307, MySQL on 3308, PostgreSQL on 5433, Valkey on 6380) to survive
        beside a host install; the two places that state it must agree.
        """
        for template_id, template in self._engine_templates():
            engine = TemplateService.engine_metadata(template)
            port_var = engine.get('port_var') or TemplateService.ENGINE_DEFAULT_PORT_VAR
            declared = {v['name']: v for v in template['variables']}
            assert port_var in declared, f'{template_id} declares no {port_var}'
            assert str(declared[port_var]['default']) == str(engine['default_port']), (
                f"{template_id}: engine.default_port={engine['default_port']} but "
                f"{port_var} defaults to {declared[port_var]['default']}"
            )

    def test_declared_version_is_the_tag_that_gets_installed(self, app):
        """``version:`` is what the catalog shows; the tag is what you get.

        Meilisearch advertised 1.0 while installing v1.12, and Valkey
        advertised 8.0 while installing the rolling ``8`` tag.
        """
        for template_id, template in self._engine_templates():
            engine = TemplateService.engine_metadata(template)
            version_var = (template.get('engine') or {}).get('version_var') or 'IMAGE_TAG'
            declared = {v['name']: v for v in template['variables']}
            assert version_var in declared, f'{template_id} declares no {version_var}'
            default_tag = str(declared[version_var]['default'])
            assert default_tag in [str(v) for v in engine['versions']], (
                f'{template_id}: default tag {default_tag} is not in engine.versions'
            )
            assert str(template['version']) == default_tag, (
                f"{template_id}: catalog says version {template['version']} but "
                f'the default install pulls tag {default_tag}'
            )

    def test_engine_admin_user_matches_the_user_the_compose_creates(self, app):
        """The username in the drawer must be the one the image is told to make.

        MongoDB (``MONGO_INITDB_ROOT_USERNAME``), CouchDB (``COUCHDB_USER``),
        ClickHouse (``CLICKHOUSE_USER``) and InfluxDB
        (``DOCKER_INFLUXDB_INIT_USERNAME``) each name their admin explicitly;
        a mismatch hands out a credential that cannot authenticate.
        """
        for template_id, template in self._engine_templates():
            admin_user = TemplateService.engine_metadata(template).get('admin_user')
            if not admin_user:
                continue
            for service in template['compose']['services'].values():
                for key, value in (service.get('environment') or {}).items():
                    if not key.endswith(('_USER', '_USERNAME')):
                        continue
                    if '${' in str(value):
                        continue  # operator-chosen, nothing to compare against
                    assert str(value) == admin_user, (
                        f'{template_id}: engine.admin_user is {admin_user!r} but '
                        f'compose sets {key}={value!r}'
                    )

    def test_engine_data_path_is_where_the_named_volume_is_mounted(self, app):
        """``engine.data_path`` is what the UI calls the engine's data.

        It has to be a *named volume* target: a bind mount or a stray path
        means a "managed" engine whose data the panel does not actually keep.
        """
        for template_id, template in self._engine_templates():
            data_path = TemplateService.engine_metadata(template).get('data_path')
            if not data_path:
                continue
            named = set((template['compose'].get('volumes') or {}).keys())
            targets = set()
            for service in template['compose']['services'].values():
                for mount in service.get('volumes', []) or []:
                    source, _, target = str(mount).partition(':')
                    if source in named:
                        targets.add(target.split(':')[0])
            assert data_path in targets, (
                f'{template_id}: engine.data_path {data_path} is not the mount '
                f'target of a named volume (named targets: {sorted(targets)})'
            )

    def test_config_files_never_shadow_the_data_volume(self, app):
        """A ``files:`` entry is bind-mounted; it must not land on the data dir.

        ``_apply_bind_mounts_to_compose`` drops any named volume mounted at the
        same directory as a rendered file, so a config file written into the
        data path would silently delete the engine's persistence.
        """
        for template_id, template in self._engine_templates():
            data_path = (TemplateService.engine_metadata(template)
                         .get('data_path') or '').rstrip('/')
            for file_def in template.get('files', []) or []:
                path = str(file_def.get('path', ''))
                if not path.startswith('/') or not data_path:
                    continue
                assert os.path.dirname(path).rstrip('/') != data_path, (
                    f'{template_id}: {path} would replace the data volume at '
                    f'{data_path}'
                )


class TestCouchDBSingleNode:
    """CouchDB will not create its own system databases unless told to.

    Booted for real, a node without ``[couchdb] single_node`` answers
    ``/_all_dbs`` with ``[]``, has no ``_users`` database (so no non-admin
    account can ever be created) and logs ``database_does_not_exist`` for
    ``_users`` on a loop. The image's entrypoint reads only COUCHDB_USER,
    COUCHDB_PASSWORD, COUCHDB_SECRET and COUCHDB_ERLANG_COOKIE -- there is no
    environment variable for this -- so the flag ships as a config snippet.
    """

    @staticmethod
    def _template():
        return TemplateService.get_template('couchdb')['template']

    def test_single_node_config_file_is_shipped(self, app):
        files = self._template().get('files') or []
        inis = [f for f in files if f['path'].startswith('/opt/couchdb/etc/local.d/')]
        assert inis, 'couchdb ships no local.d config; _users would never exist'
        content = '\n'.join(f['content'] for f in inis)
        assert '[couchdb]' in content
        assert re.search(r'single_node\s*=\s*true', content), content

    def test_the_snippet_is_bind_mounted_and_the_data_volume_survives(self, app):
        """Rendering it through the real installer, not a hand-written string."""
        rendered = TemplateService._render_compose_and_files(
            self._template(),
            {'APP_NAME': 'couch1', 'IMAGE_TAG': '3.3', 'PORT': '5984',
             'BIND_ADDRESS': '127.0.0.1', 'DB_PASSWORD': 'x' * 28},
            '/opt/serverkit/apps/couch1',
        )
        assert rendered['success'], rendered.get('error')
        compose = yaml.safe_load(rendered['compose_content'])
        volumes = compose['services']['app']['volumes']
        assert './single-node.ini:/opt/couchdb/etc/local.d/single-node.ini' in volumes
        # The config mount must not have displaced persistence.
        assert 'couchdb-data:/opt/couchdb/data' in volumes
        assert 'couchdb-data' in compose['volumes']


# ── install: validation + safety rules ───────────────────────────────────────
class TestInstallValidation:

    def test_unknown_template_is_404(self, client, auth_headers):
        response = _install(client, auth_headers, template_id='not-a-real-engine')
        assert response.status_code == 404
        assert 'error' in response.get_json()

    def test_template_id_is_required(self, client, auth_headers):
        response = _install(client, auth_headers)
        assert response.status_code == 400

    def test_non_engine_template_is_rejected(self, client, auth_headers):
        """Only templates declaring `engine:` install through this route."""
        response = _install(client, auth_headers, template_id='gitea',
                            instance_name='gitea-here')
        assert response.status_code == 400
        assert 'engine' in response.get_json()['error']

    def test_version_outside_the_template_allowlist_is_rejected(self, client, auth_headers):
        """Safety rule 6: the image tag can never be caller-chosen."""
        response = _install(client, auth_headers, template_id='postgresql',
                            instance_name='pg-evil', version='../../evil:latest')
        assert response.status_code == 400
        body = response.get_json()
        assert 'not offered' in body['error']
        assert body['versions'] == ['16', '15', '14']

    def test_declared_version_becomes_the_image_tag(self, app, new_engine_yaml):
        plan = engines.plan_install(template_id='probedb', version='0.9')
        assert plan['variables']['IMAGE_TAG'] == '0.9'

    def test_initial_database_is_rejected_when_unsupported(self, client, auth_headers):
        """Redis has no database_var; say so instead of silently dropping it."""
        response = _install(client, auth_headers, template_id='redis',
                            instance_name='redis-one', initial_database='shop')
        assert response.status_code == 400
        assert 'initial database' in response.get_json()['error']


class TestPortCollision:

    def test_busy_port_is_refused_with_a_suggestion(self, app, monkeypatch):
        """Safety rule 3: refuse, and name a port that would work."""
        monkeypatch.setattr(TemplateService, '_port_is_free',
                            classmethod(lambda cls, port: False))
        monkeypatch.setattr(TemplateService, '_find_available_port',
                            classmethod(lambda cls, start=8000, max_attempts=1000: 5599))
        result = engines.plan_install(template_id='postgresql', port=5433)
        assert result['status_code'] == 409
        assert result['port'] == 5433
        assert result['suggested_port'] == 5599

    def test_collision_surfaces_as_409_over_http(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(TemplateService, '_port_is_free',
                            classmethod(lambda cls, port: False))
        response = _install(client, auth_headers, template_id='postgresql',
                            instance_name='pg-clash', port=5433)
        assert response.status_code == 409
        assert 'already in use' in response.get_json()['error']

    def test_free_port_is_honored_not_reassigned(self, app, monkeypatch):
        """The documented `port` parameter has to be real, not advisory."""
        monkeypatch.setattr(TemplateService, '_port_is_free',
                            classmethod(lambda cls, port: True))
        plan = engines.plan_install(template_id='postgresql', port=15432)
        assert plan['variables']['PORT'] == '15432'
        prepared = TemplateService._prepare_install_variables(
            'postgresql', TemplateService.get_template('postgresql')['template'],
            'pg-fixed', plan['variables'])
        assert prepared['variables']['PORT'] == '15432'

    def test_out_of_range_port_is_rejected(self, app):
        assert engines.plan_install(
            template_id='postgresql', port=99999)['status_code'] == 400


class TestPrivateByDefault:

    def test_bind_is_loopback_without_expose_public(self, app):
        plan = engines.plan_install(template_id='postgresql')
        assert plan['variables']['BIND_ADDRESS'] == '127.0.0.1'
        assert plan.get('warning') is None

    def test_expose_public_binds_all_interfaces_and_warns(self, app):
        plan = engines.plan_install(template_id='postgresql', expose_public=True)
        assert plan['variables']['BIND_ADDRESS'] == '0.0.0.0'
        assert 'any network interface' in plan['warning']

    def test_caller_variables_cannot_override_the_private_bind(self, app):
        """The explicit flag wins over a handcrafted variables payload."""
        plan = engines.plan_install(template_id='postgresql',
                                    variables={'BIND_ADDRESS': '0.0.0.0'})
        assert plan['variables']['BIND_ADDRESS'] == '127.0.0.1'

    def test_warning_reaches_the_http_response(self, client, auth_headers):
        response = _install(client, auth_headers, template_id='postgresql',
                            instance_name='pg-public', expose_public=True)
        assert response.status_code == 202
        assert 'warning' in response.get_json()

    def test_passwordless_engine_cannot_be_exposed_publicly(self, app):
        """CockroachDB single-node runs `--insecure` — there is no auth to
        expose. For engines like it the loopback bind is the only control, so
        publishing one to every interface must be refused, not warned about."""
        plan = engines.plan_install(template_id='cockroachdb', expose_public=True)
        assert plan.get('error'), 'exposing an unauthenticated engine must fail'
        assert plan['status_code'] == 400
        assert 'without authentication' in plan['error']

    def test_passwordless_engine_still_installs_privately(self, app):
        plan = engines.plan_install(template_id='cockroachdb')
        assert not plan.get('error')
        assert plan['variables']['BIND_ADDRESS'] == '127.0.0.1'

    def test_shipped_passwordless_engines_are_known(self, app):
        """If a future template drops its admin_password_var, this test is the
        thing that makes the consequence visible instead of silent."""
        passwordless = sorted(
            e['id'] for e in engines.engine_catalog()
            if not (e.get('engine') or {}).get('admin_password_var')
        )
        assert passwordless == ['cockroachdb'], (
            f'unexpected engines without admin credentials: {passwordless}'
        )


class TestAdminOnly:
    """Safety rule 2 — every mutating route is admin-only."""

    def test_install_rejects_a_non_admin(self, client, viewer_headers):
        response = _install(client, viewer_headers, template_id='postgresql',
                            instance_name='pg-nope')
        assert response.status_code == 403
        assert Application.query.count() == 0

    def test_install_rejects_anonymous(self, client):
        assert _install(client, {}, template_id='postgresql').status_code == 401

    def test_reading_the_catalog_does_not_require_admin(self, client, viewer_headers):
        assert client.get('/api/v1/databases/engines',
                          headers=viewer_headers).status_code == 200


# ── install: happy path ──────────────────────────────────────────────────────
class TestInstallHappyPath:

    def test_install_returns_a_deployment_job(self, client, auth_headers):
        """Delegates to the template pipeline so the UI opens the deploy console."""
        response = _install(client, auth_headers, template_id='postgresql',
                            instance_name='pg-main')
        assert response.status_code == 202, response.get_json()
        body = response.get_json()
        assert body['success'] is True
        assert body['job_id']
        assert body['job']['kind'] == 'template_install'
        assert body['app_name'] == 'pg-main'
        assert body['engine']['protocol'] == 'postgresql'

    def test_install_plan_renders_the_engine_compose(self, app):
        from app.services.deployment_job_service import DeploymentJobService

        plan = engines.plan_install(template_id='mongodb', instance_name='mongo-main',
                                    initial_database='shop')
        built = TemplateService.build_install_plan(
            'mongodb', plan['app_name'], plan['variables'])
        assert built['success']
        compose = next(step for step in built['plan']['steps']
                       if step.get('path', '').endswith('docker-compose.yml'))['content']
        rendered = yaml.safe_load(compose)
        service = rendered['services']['app']
        assert service['image'] == 'mongo:7.0'
        assert service['environment']['MONGO_INITDB_ROOT_USERNAME'] == 'root'
        assert service['environment']['MONGO_INITDB_DATABASE'] == 'shop'
        assert service['ports'][0].startswith('127.0.0.1:')
        assert 'mongodb-data' in rendered['volumes']
        assert DeploymentJobService  # imported to prove the pipeline is the same one

    def test_instance_name_defaults_and_does_not_collide(self, app):
        db.session.add(Application(name='postgresql', app_type='docker',
                                   user_id=1, root_path='/tmp/postgresql'))
        db.session.commit()
        plan = engines.plan_install(template_id='postgresql')
        assert plan['app_name'] == 'postgresql-2'

    def test_generated_password_is_not_a_template_literal(self, app):
        """Safety rule 4: the secret comes from the existing password path."""
        template = TemplateService.get_template('postgresql')['template']
        prepared = TemplateService._prepare_install_variables(
            'postgresql', template, 'pg-secret', {})
        password = prepared['variables']['DB_PASSWORD']
        assert len(password) == 28
        assert password not in json.dumps(template)

    def test_password_shown_in_the_drawer_is_the_one_installed(self, app):
        """The install drawer generates/reveals the secret and sends it as a
        `variables` entry; the pipeline must use exactly that value, or the
        password the operator copied would not be the one that works."""
        template = TemplateService.get_template('postgresql')['template']
        prepared = TemplateService._prepare_install_variables(
            'postgresql', template, 'pg-chosen', {'DB_PASSWORD': 'chosen-by-the-drawer'})
        assert prepared['variables']['DB_PASSWORD'] == 'chosen-by-the-drawer'

    def test_install_response_does_not_echo_the_secret(self, client, auth_headers):
        """Surfaced once, at the moment of choosing it -- never read back."""
        secret = 'do-not-echo-this-secret'
        response = _install(client, auth_headers, template_id='postgresql',
                            instance_name='pg-quiet',
                            variables={'DB_PASSWORD': secret})
        assert response.status_code == 202
        assert secret not in response.get_data(as_text=True)


# ── installed instances ──────────────────────────────────────────────────────
def _make_installed_engine(tmp_path, monkeypatch, *, template_id='postgresql',
                           name='pg-main', bind='127.0.0.1'):
    """An Application that looks exactly like a finished engine install."""
    root = tmp_path / name
    root.mkdir()
    (root / '.serverkit-template.json').write_text(json.dumps({
        'template_id': template_id,
        'template_version': '16',
        'variables': {'PORT': '5433', 'BIND_ADDRESS': bind,
                      'DB_NAME': 'shop', 'DB_PASSWORD': 'sup3rs3cret-do-not-leak'},
    }), encoding='utf-8')

    application = Application(name=name, app_type='docker', status='running',
                              user_id=1, port=5433, root_path=str(root))
    db.session.add(application)
    db.session.commit()
    monkeypatch.setattr(TemplateService, 'get_config', classmethod(
        lambda cls: {'repos': [], 'installed': {
            str(application.id): {'template_id': template_id}}}))
    return application


class TestInstalledEngines:

    def test_installed_engine_is_listed_with_its_metadata(self, client, auth_headers,
                                                          tmp_path, monkeypatch):
        application = _make_installed_engine(tmp_path, monkeypatch)
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert len(data['installed']) == 1
        instance = data['installed'][0]
        assert instance['app_id'] == application.id
        assert instance['template_id'] == 'postgresql'
        assert instance['engine']['protocol'] == 'postgresql'
        assert instance['port'] == 5433
        assert instance['exposed_public'] is False

    def test_catalog_counts_the_instance(self, client, auth_headers, tmp_path, monkeypatch):
        application = _make_installed_engine(tmp_path, monkeypatch)
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        entry = next(e for e in data['catalog'] if e['id'] == 'postgresql')
        assert entry['installed_count'] == 1
        assert entry['instances'] == [application.id]

    def test_public_bind_is_reported(self, client, auth_headers, tmp_path, monkeypatch):
        _make_installed_engine(tmp_path, monkeypatch, bind='0.0.0.0')
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert data['installed'][0]['exposed_public'] is True

    def test_secret_is_never_serialized(self, client, auth_headers, tmp_path, monkeypatch):
        """Safety rule 4: the password crosses once, at install, and never again."""
        _make_installed_engine(tmp_path, monkeypatch)
        response = client.get('/api/v1/databases/engines', headers=auth_headers)
        assert 'sup3rs3cret-do-not-leak' not in response.get_data(as_text=True)
        instance = response.get_json()['installed'][0]
        assert instance['has_secret'] is True
        assert 'DB_PASSWORD' not in instance['variables']

    def test_non_engine_apps_are_not_listed_as_engines(self, client, auth_headers,
                                                       tmp_path, monkeypatch):
        _make_installed_engine(tmp_path, monkeypatch, template_id='gitea', name='git')
        data = client.get('/api/v1/databases/engines', headers=auth_headers).get_json()
        assert data['installed'] == []

    def test_is_engine_app_reads_the_app_directory_when_config_is_lost(
            self, app, tmp_path, monkeypatch):
        """A reset templates.json must not orphan an installed engine."""
        application = _make_installed_engine(tmp_path, monkeypatch)
        monkeypatch.setattr(TemplateService, 'get_config',
                            classmethod(lambda cls: {'repos': [], 'installed': {}}))
        assert engines.app_template_id(application) == 'postgresql'
        assert engines.is_engine_app(application) is True


# ── uninstall: the data volume ───────────────────────────────────────────────
class TestUninstallPreservesData:
    """Safety rule 5, enforced on the shared app-delete route."""

    @pytest.fixture
    def compose_down_calls(self, monkeypatch):
        from app.services.docker_service import DockerService
        calls = []

        def fake_down(project_path, volumes=False, remove_orphans=True, compose_file=None):
            calls.append({'volumes': volumes})
            return {'success': True}

        monkeypatch.setattr(DockerService, 'compose_down', classmethod(
            lambda cls, *a, **kw: fake_down(*a, **kw)))
        return calls

    def test_engine_delete_keeps_the_volume_by_default(self, client, auth_headers,
                                                       tmp_path, monkeypatch,
                                                       compose_down_calls):
        application = _make_installed_engine(tmp_path, monkeypatch)
        response = client.delete(f'/api/v1/apps/{application.id}', headers=auth_headers)
        assert response.status_code == 200
        assert compose_down_calls == [{'volumes': False}]

    def test_remove_data_true_removes_the_volume(self, client, auth_headers,
                                                 tmp_path, monkeypatch,
                                                 compose_down_calls):
        application = _make_installed_engine(tmp_path, monkeypatch)
        response = client.delete(f'/api/v1/apps/{application.id}?remove_data=true',
                                 headers=auth_headers)
        assert response.status_code == 200
        assert compose_down_calls == [{'volumes': True}]

    def test_ordinary_apps_keep_the_historic_behavior(self, client, auth_headers,
                                                      tmp_path, monkeypatch,
                                                      compose_down_calls):
        application = _make_installed_engine(tmp_path, monkeypatch,
                                             template_id='gitea', name='git')
        client.delete(f'/api/v1/apps/{application.id}', headers=auth_headers)
        assert compose_down_calls == [{'volumes': True}]
