"""Proving tests for the v1 serverkit manifest spec (Phase 0)."""

import json
from pathlib import Path

import pytest

from app.services.manifest_spec_service import (
    ManifestSpecService,
    ManifestError,
    MANIFEST_SCHEMA,
    FROM_SERVICE_PROPERTIES,
)
from app.services.repository_manifest_service import RepositoryManifestService


VALID = {
    'version': 1,
    'server': 'vps-frankfurt',
    'services': [
        {
            'name': 'api',
            'type': 'web',
            'runtime': 'python',
            'buildCommand': 'pip install -r requirements.txt',
            'startCommand': 'gunicorn app:app',
            'port': 8000,
            'healthCheckPath': '/health',
            'autoDeploy': True,
            'envVars': [
                {'key': 'DATABASE_URL', 'fromService': {'name': 'db', 'property': 'connectionString'}},
                {'key': 'STRIPE_KEY', 'fromSecret': 'stripe_prod'},
                {'key': 'SESSION_SECRET', 'generate': True},
                {'key': 'LOG_LEVEL', 'value': 'info'},
            ],
            'disks': [
                {'name': 'uploads', 'mountPath': '/data/uploads',
                 'backup': {'schedule': 'daily', 'retain': 7}},
            ],
        },
        {'name': 'db', 'type': 'postgres', 'version': '16',
         'disk': {'size': '10GB', 'backup': {'schedule': 'daily', 'retain': 7}}},
    ],
    'domains': [{'host': 'api.example.com', 'service': 'api', 'ssl': 'auto'}],
}


def test_valid_manifest_normalizes():
    n = ManifestSpecService.normalize(VALID)
    assert n['version'] == 1
    assert n['server'] == 'vps-frankfurt'
    assert len(n['services']) == 2
    api = n['services'][0]
    assert api['kind'] == 'app'
    assert api['app_type'] == 'docker'
    assert api['build_command'] == 'pip install -r requirements.txt'
    assert api['auto_deploy'] is True
    db = n['services'][1]
    assert db['kind'] == 'database'
    assert db['db_engine'] == 'postgresql'
    assert db['engine_version'] == '16'
    assert db['disks'][0]['size'] == '10GB'


def test_env_var_sources_classified():
    n = ManifestSpecService.normalize(VALID)
    env = {v['key']: v for v in n['services'][0]['env_vars']}
    assert env['DATABASE_URL']['source'] == 'service'
    assert env['DATABASE_URL']['service_ref'] == {'name': 'db', 'property': 'connectionString'}
    assert env['STRIPE_KEY']['source'] == 'secret'
    assert env['STRIPE_KEY']['secret_name'] == 'stripe_prod'
    assert env['SESSION_SECRET']['source'] == 'generate'
    assert env['LOG_LEVEL']['source'] == 'value'
    assert env['LOG_LEVEL']['value'] == 'info'


def test_snake_case_aliases_accepted():
    data = {
        'version': 1,
        'services': [{
            'name': 'api', 'type': 'web',
            'build_command': 'make', 'start_command': 'run',
            'healthcheck_path': '/up', 'auto_deploy': True,
            'envVars': [{'key': 'X', 'from_secret': 's'}],
        }],
    }
    n = ManifestSpecService.normalize(data)
    svc = n['services'][0]
    assert svc['build_command'] == 'make'
    assert svc['start_command'] == 'run'
    assert svc['healthcheck_path'] == '/up'
    assert svc['auto_deploy'] is True
    assert svc['env_vars'][0]['source'] == 'secret'


def test_missing_version_rejected():
    with pytest.raises(ManifestError):
        ManifestSpecService.normalize({'services': []})


def test_unknown_service_type_rejected():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize({'version': 1, 'services': [{'name': 'x', 'type': 'quantum'}]})
    assert any('type' in e for e in exc.value.errors)


def test_duplicate_service_name_rejected():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize({
            'version': 1,
            'services': [{'name': 'a', 'type': 'web'}, {'name': 'a', 'type': 'worker'}],
        })
    assert any('duplicate' in e for e in exc.value.errors)


def test_from_service_unknown_sibling_rejected():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize({
            'version': 1,
            'services': [{
                'name': 'api', 'type': 'web',
                'envVars': [{'key': 'U', 'fromService': {'name': 'ghost', 'property': 'url'}}],
            }],
        })
    assert any('ghost' in e for e in exc.value.errors)


def test_domain_unknown_service_rejected():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize({
            'version': 1,
            'services': [{'name': 'api', 'type': 'web'}],
            'domains': [{'host': 'x.example.com', 'service': 'nope'}],
        })
    assert any('nope' in e for e in exc.value.errors)


def test_multiple_env_sources_rejected():
    with pytest.raises(ManifestError):
        ManifestSpecService.normalize({
            'version': 1,
            'services': [{'name': 'api', 'type': 'web',
                          'envVars': [{'key': 'X', 'value': 'a', 'fromSecret': 'b'}]}],
        })


def test_summarize():
    n = ManifestSpecService.normalize(VALID)
    s = ManifestSpecService.summarize(n)
    assert s['service_count'] == 2
    assert s['databases'] == ['db']
    assert s['domains'][0]['host'] == 'api.example.com'
    # STRIPE_KEY (secret) shows as required env
    keys = {e['key'] for e in s['env_required']}
    assert 'STRIPE_KEY' in keys


def test_embedded_schema_matches_docs_copy():
    """The shipped editor schema must byte-match the embedded constant."""
    docs = Path(__file__).resolve().parents[2] / 'docs' / 'serverkit-yaml.schema.json'
    on_disk = json.loads(docs.read_text(encoding='utf-8'))
    # compare validation-relevant surface (docs copy also carries descriptions)
    assert on_disk['properties']['version']['const'] == \
        MANIFEST_SCHEMA['properties']['version']['const']
    assert set(on_disk['definitions']['envVar']['properties']['fromService']['properties']
               ['property']['enum']) == set(FROM_SERVICE_PROPERTIES)
    assert set(on_disk['definitions']['service']['properties']['type']['enum']) == \
        set(MANIFEST_SCHEMA['definitions']['service']['properties']['type']['enum'])


def test_recipe_blocks_normalize_and_summarize():
    manifest = {
        'version': 1,
        'project': 'Media server',
        'capabilities': [
            'probe:render-group', 'handoff:token', 'apply:configure-media',
            'verify:hardware-transcode',
        ],
        'requires': {
            'cpuCores': 4, 'memoryMB': 4096, 'diskGB': 100,
            'igpu': 'preferred',
        },
        'configure': [
            {'id': 'render', 'type': 'probe', 'kind': 'render-group'},
            {
                'id': 'claim', 'type': 'handoff', 'kind': 'token',
                'dependsOn': ['render'], 'ttlSeconds': 240,
                'input': {'key': 'PLEX_CLAIM', 'label': 'Plex claim token',
                          'url': 'https://plex.tv/claim'},
            },
            {'id': 'configure', 'type': 'apply', 'kind': 'configure-media',
             'dependsOn': ['claim']},
        ],
        'verify': [
            {'id': 'transcode', 'kind': 'hardware-transcode',
             'dependsOn': ['configure']},
        ],
    }
    normalized = ManifestSpecService.normalize(manifest)
    assert normalized['requires']['igpu'] == 'preferred'
    assert normalized['configure'][1]['ttl_seconds'] == 240
    assert normalized['verify'][0]['type'] == 'verify'
    assert normalized['verify'][0]['capability'] == 'verify:hardware-transcode'
    summary = ManifestSpecService.summarize(normalized)['recipe']
    assert summary['configure_steps'] == 3
    assert summary['verify_steps'] == 1
    assert summary['handoffs'][0]['ttl_seconds'] == 240


def test_recipe_requires_declared_capabilities_and_ordered_dependencies():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize({
            'version': 1,
            'capabilities': [],
            'configure': [
                {'id': 'later', 'type': 'apply', 'kind': 'demo',
                 'dependsOn': ['missing']},
            ],
        })
    assert any('not declared' in error for error in exc.value.errors)
    assert any('earlier recipe step' in error for error in exc.value.errors)


# -- RepositoryManifestService integration ---------------------------------

def test_repo_service_detects_v1(tmp_path):
    import yaml
    (tmp_path / 'serverkit.yaml').write_text(yaml.safe_dump(VALID), encoding='utf-8')
    result = RepositoryManifestService.analyze_path(str(tmp_path))
    assert result['strategy'] == 'serverkit'
    assert 'manifest_v1' in result
    assert result['manifest_v1']['service_count'] == 2
    # first app service seeded recommended
    assert result['recommended']['port'] == 8000
    assert result['recommended']['healthcheck_path'] == '/health'


def test_repo_service_legacy_flat_file_unchanged(tmp_path):
    """A v0 (no version) serverkit.yaml keeps the legacy code path."""
    legacy = {'app_type': 'flask', 'deploy': {'port': 5000, 'healthcheck_path': '/legacy'},
              'build': {'command': 'pip install .'}}
    import yaml
    (tmp_path / 'serverkit.yaml').write_text(yaml.safe_dump(legacy), encoding='utf-8')
    result = RepositoryManifestService.analyze_path(str(tmp_path))
    assert result['strategy'] == 'serverkit'
    assert 'manifest_v1' not in result  # legacy path, no v1 summary
    assert result['recommended']['app_type'] == 'flask'
    assert result['recommended']['port'] == 5000
    assert result['recommended']['healthcheck_path'] == '/legacy'


def test_repo_service_v1_errors_surface(tmp_path):
    import yaml
    bad = {'version': 1, 'services': [{'name': 'a', 'type': 'nope'}]}
    (tmp_path / 'serverkit.yaml').write_text(yaml.safe_dump(bad), encoding='utf-8')
    result = RepositoryManifestService.analyze_path(str(tmp_path))
    assert 'manifest_v1_errors' in result
    assert any('nope' in w for w in result['warnings'])


# -- scaffold (#3) ----------------------------------------------------------

def _make_app():
    from app import db
    from app.models import Application, User
    user = User.query.filter_by(username='testadmin').first()
    app_row = Application(name='myapp', app_type='docker', port=8080,
                          user_id=user.id, status='running')
    db.session.add(app_row)
    db.session.commit()
    return app_row


def test_scaffold_endpoint_roundtrips(client, auth_headers, app):
    app_row = _make_app()
    resp = client.get(f'/api/v1/manifests/scaffold?app_id={app_row.id}', headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    manifest = resp.get_json()['manifest']
    assert manifest['version'] == 1
    assert manifest['services'][0]['name'] == 'myapp'
    assert manifest['services'][0]['type'] == 'docker'
    assert manifest['services'][0]['port'] == 8080
    # the scaffold must itself be a valid v1 manifest
    normalized = ManifestSpecService.normalize(manifest)
    assert normalized['services'][0]['app_type'] == 'docker'


def test_scaffold_requires_admin(client, app):
    resp = client.get('/api/v1/manifests/scaffold?app_id=1')
    assert resp.status_code in (401, 422)


def test_validate_endpoint(client, auth_headers, app):
    resp = client.post('/api/v1/manifests/validate', headers=auth_headers,
                       json={'manifest': VALID})
    assert resp.status_code == 200
    assert resp.get_json()['valid'] is True


# -- Dockerfile builds ------------------------------------------------------

def _dockerfile_manifest(**svc_extra):
    svc = {'name': 'api', 'type': 'worker'}
    svc.update(svc_extra)
    return {'version': 1, 'services': [svc]}


def test_dockerfile_path_normalizes():
    n = ManifestSpecService.normalize(
        _dockerfile_manifest(dockerfilePath='services/api/Dockerfile'))
    assert n['services'][0]['dockerfile_path'] == 'services/api/Dockerfile'


def test_dockerfile_path_snake_alias():
    n = ManifestSpecService.normalize(
        _dockerfile_manifest(dockerfile_path='Dockerfile.api'))
    assert n['services'][0]['dockerfile_path'] == 'Dockerfile.api'


def test_dockerfile_path_exclusive_with_image():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize(
            _dockerfile_manifest(dockerfilePath='Dockerfile', image='nginx:1'))
    assert any('mutually exclusive' in e for e in exc.value.errors)


def test_dockerfile_path_exclusive_with_containers():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize(_dockerfile_manifest(
            dockerfilePath='Dockerfile',
            containers={'main': {'image': 'nginx:1'}}))
    assert any('containers' in e for e in exc.value.errors)


def test_dockerfile_path_rejects_unsafe_paths():
    for bad in ('../evil/Dockerfile', '/abs/Dockerfile', 'C:\evil\Dockerfile',
                'services/../../evil'):
        with pytest.raises(ManifestError):
            ManifestSpecService.normalize(_dockerfile_manifest(dockerfilePath=bad))


def test_dockerfile_path_not_for_databases():
    with pytest.raises(ManifestError) as exc:
        ManifestSpecService.normalize({
            'version': 1,
            'services': [{'name': 'db', 'type': 'postgres',
                          'dockerfilePath': 'Dockerfile'}]})
    assert any('database' in e for e in exc.value.errors)
