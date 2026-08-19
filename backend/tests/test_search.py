"""Tests for the unified entity omnisearch endpoint (plan 41, Phase 4).

Proves the /api/v1/search contract: response shape, the 2-char minimum, the
per-type cap, authz-aware fan-out (a member can't see another user's app; cron
is admin-only), and that vault rows never leak secret values.
"""
import pytest
from werkzeug.security import generate_password_hash
from flask_jwt_extended import create_access_token


def _mk_user(db, username, role='developer'):
    from app.models import User
    u = User(email=f'{username}@t.local', username=username,
             password_hash=generate_password_hash('x'), role=role, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def _headers(user_id):
    return {'Authorization': f'Bearer {create_access_token(identity=user_id)}'}


@pytest.fixture
def personas(app):
    """An admin, a developer 'owner', and a foreign developer, plus one app the
    owner owns."""
    from types import SimpleNamespace
    from app import db
    from app.models.application import Application

    admin = _mk_user(db, 'srch_admin', role='admin')
    owner = _mk_user(db, 'srch_owner')
    foreign = _mk_user(db, 'srch_foreign')

    a = Application(name='SecretProjectOne', app_type='php', user_id=owner.id,
                    root_path='/srv/secretprojectone')
    db.session.add(a)
    db.session.commit()

    return SimpleNamespace(
        admin=_headers(admin.id),
        owner=_headers(owner.id),
        foreign=_headers(foreign.id),
        app_id=a.id,
    )


def test_shape(client, personas):
    """Response has a canonical list envelope plus the compatibility field."""
    r = client.get('/api/v1/search?q=SecretProject', headers=personas.owner)
    assert r.status_code == 200
    body = r.get_json()
    assert body['data'] == body['results']
    assert body['meta']['total'] == len(body['data'])
    assert 'results' in body and isinstance(body['results'], list)
    assert len(body['results']) >= 1
    for row in body['results']:
        assert set(['type', 'label', 'sublabel', 'path']).issubset(row.keys())

    svc = [row for row in body['results'] if row['type'] == 'service']
    assert any(row['label'] == 'SecretProjectOne' for row in svc)
    assert svc[0]['path'] == f'/services/{personas.app_id}'


def test_min_length_returns_empty(client, personas):
    """A term shorter than 2 chars returns an empty result set (200)."""
    r = client.get('/api/v1/search?q=a', headers=personas.owner)
    assert r.status_code == 200
    assert r.get_json() == {'data': [], 'meta': {'total': 0}, 'results': []}

    # Missing q behaves the same.
    r2 = client.get('/api/v1/search', headers=personas.owner)
    assert r2.status_code == 200
    assert r2.get_json() == {'data': [], 'meta': {'total': 0}, 'results': []}


def test_unknown_query_parameter_uses_typed_validation_error(client, personas):
    response = client.get(
        '/api/v1/search?q=valid&surprise=true',
        headers={**personas.owner, 'X-Request-ID': 'search-query-contract'},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        'error': 'Invalid query parameters',
        'status': 400,
        'code': 'invalid_query',
        'details': {'fields': {'surprise': ['Unknown field.']}},
        'request_id': 'search-query-contract',
    }


def test_per_type_cap(client, personas):
    """More than 5 matching apps yields at most 5 service rows."""
    from app import db
    from app.models import User
    from app.models.application import Application

    # Reuse the admin as owner so an admin search sees all 7 matches.
    admin = User.query.filter_by(username='srch_admin').first()
    for i in range(7):
        db.session.add(Application(name=f'CapApp{i}', app_type='php',
                                   user_id=admin.id, root_path=f'/srv/capapp{i}'))
    db.session.commit()

    r = client.get('/api/v1/search?q=CapApp', headers=personas.admin)
    assert r.status_code == 200
    service_rows = [row for row in r.get_json()['results'] if row['type'] == 'service']
    assert len(service_rows) == 5


def test_member_cannot_see_foreign_app_but_admin_can(client, personas):
    """A non-owner developer does NOT see another user's app; an admin does."""
    # Foreign developer: no ownership, no grant -> no service row.
    r_foreign = client.get('/api/v1/search?q=SecretProject', headers=personas.foreign)
    assert r_foreign.status_code == 200
    foreign_services = [row for row in r_foreign.get_json()['results']
                        if row['type'] == 'service']
    assert foreign_services == []

    # Admin bypasses ownership -> sees it.
    r_admin = client.get('/api/v1/search?q=SecretProject', headers=personas.admin)
    admin_services = [row for row in r_admin.get_json()['results']
                      if row['type'] == 'service']
    assert any(row['label'] == 'SecretProjectOne' for row in admin_services)


def test_cron_admin_only(client, personas, monkeypatch):
    """Cron rows appear for admins but never for members."""
    from app.services import cron_service

    monkeypatch.setattr(
        cron_service.CronService, 'list_jobs',
        classmethod(lambda cls: {'jobs': [{
            'name': 'NightlyBackupTask',
            'description': 'runs a NightlyBackupTask',
            'command': '/usr/bin/backup.sh',
            'schedule': '0 3 * * *',
        }]}),
    )

    r_admin = client.get('/api/v1/search?q=NightlyBackup', headers=personas.admin)
    admin_cron = [row for row in r_admin.get_json()['results'] if row['type'] == 'cron']
    assert len(admin_cron) == 1
    assert admin_cron[0]['label'] == 'NightlyBackupTask'
    assert admin_cron[0]['sublabel'] == '0 3 * * *'

    r_member = client.get('/api/v1/search?q=NightlyBackup', headers=personas.owner)
    member_cron = [row for row in r_member.get_json()['results'] if row['type'] == 'cron']
    assert member_cron == []


def test_vault_names_only_never_leaks_secret(client, personas):
    """A vault row exposes only name/slug/description-derived fields — never the
    stored secret value."""
    from app import db
    from app.models.secret_vault import SecretVault, Secret
    from app.utils.crypto import encrypt_secret

    vault = SecretVault(name='ProdVaultAlpha', slug='prod-vault-alpha',
                        description='production secrets')
    db.session.add(vault)
    db.session.commit()

    leak_marker = 'SUPERSECRETVALUE-DO-NOT-LEAK-12345'
    secret = Secret(vault_id=vault.id, name='API_KEY',
                    encrypted_value=encrypt_secret(leak_marker))
    db.session.add(secret)
    db.session.commit()

    r = client.get('/api/v1/search?q=ProdVaultAlpha', headers=personas.admin)
    assert r.status_code == 200
    body = r.get_json()

    vault_rows = [row for row in body['results'] if row['type'] == 'vault']
    assert len(vault_rows) == 1
    assert vault_rows[0]['label'] == 'ProdVaultAlpha'

    # The secret value must not appear anywhere in the serialized response.
    import json
    assert leak_marker not in json.dumps(body)
