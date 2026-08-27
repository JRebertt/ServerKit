"""Survey API + permission/capability gating (plan 27 Phase 2, #5/#6).

Covers the honest-degrade path (offline / old agent), the happy path (snapshot
stored + returned), the catalog index, and the model-level permission scope that
gates dispatch.

Reconstructed for plan 42 Phase 1 from the fragmented ``test_survey_api`` pyc +
the surviving ``survey_service`` / ``app/api/survey.py``.

Post-loss recovery status: the survey blueprint registration came back via
core_blueprints, and the Observed-mode surface (``Server.management_mode`` /
``allow_agent_update_observed`` / ``MANAGEMENT_MODES`` / ``is_managed`` /
``agent_registry.observed_blocked_count``) was restored by plan 82 §D after
the migration↔model drift gate exposed it — see the section at the bottom.
The dispatch-level Observe guard remains hollow (plan 82 §H).
"""
import pytest

from app.services import survey_service


def _mk_server(db, name='observed-box'):
    from app.models.server import Server
    s = Server(name=name)
    db.session.add(s)
    db.session.commit()
    return s


def _patch_agent(monkeypatch, *, connected=True, capable=True, result=None):
    """Point survey_service's agent_registry at a fake connected/capable agent."""
    from app.services import agent_registry as reg_mod
    reg = reg_mod.agent_registry
    monkeypatch.setattr(reg, 'is_agent_connected', lambda sid: connected)
    monkeypatch.setattr(reg, 'get_capabilities', lambda sid: {'survey': capable})
    monkeypatch.setattr(
        reg, 'send_command',
        lambda server_id, action, params=None, user_id=None, timeout=None: (
            result if result is not None else {'success': True, 'data': {}}))


# --- model-level permission scope (survives) -------------------------------- #

def test_survey_read_scope_gates_dispatch(app):
    """A server granted the ``survey:read`` scope passes has_permission; one
    without it does not — the scope that gates survey dispatch."""
    from app.models.server import Server
    granted = Server(name='granted', permissions=['survey:read'])
    denied = Server(name='denied', permissions=['docker:container:read'])
    assert granted.has_permission('survey:read') is True
    assert denied.has_permission('survey:read') is False


# --- catalog index (service surface behind the endpoint) -------------------- #

def test_probe_index_catalog(app):
    body = survey_service.probe_index()
    assert body['version'] == survey_service.catalog_version()
    ids = {p['id'] for p in body['probes']}
    assert 'nginx' in ids and 'foreign-panel' in ids


# --- honest-degrade path ---------------------------------------------------- #

def test_run_survey_degrades_when_agent_offline(app, db_session):
    server = _mk_server(db_session)
    result, error = survey_service.run_survey(server.id)
    assert result is None
    assert error['code'] == 'AGENT_OFFLINE' and error['status'] == 503


def test_run_survey_degrades_when_agent_uncapable(app, db_session, monkeypatch):
    server = _mk_server(db_session)
    _patch_agent(monkeypatch, connected=True, capable=False)
    result, error = survey_service.run_survey(server.id)
    assert result is None
    assert error['code'] == 'SURVEY_UNSUPPORTED' and error['status'] == 409


# --- happy path (snapshot stored + returned) -------------------------------- #

def test_run_survey_stores_and_returns_snapshot(app, db_session, monkeypatch):
    server = _mk_server(db_session)
    payload = {
        'catalog_version': 1,
        'probes': {
            'nginx': {'detected': True, 'service': {'active': True, 'ports': [80]},
                      'vhosts': [{'server_name': 'example.com', 'root': '/var/www/example'}]},
            'foreign-panel': {'detected': True, 'markers': ['/usr/local/cpanel']},
        },
    }
    _patch_agent(monkeypatch, result={'success': True, 'data': payload})
    result, error = survey_service.run_survey(server.id)
    assert error is None and result is not None

    stored = survey_service.list_surveys(server.id)
    assert len(stored) == 1
    latest = survey_service.latest_survey(server.id).get_map()
    assert latest['catalog_version'] == 1
    assert any(s['id'] == 'nginx' for s in latest['services'])
    assert latest['foreign_panel_detected'] is True


# --- diff (service surface behind /surveys/diff) ---------------------------- #

def test_diff_maps_reports_removed_service(app):
    old = {'catalog_version': 1, 'services': [{'id': 'nginx', 'active': True, 'ports': [80]}]}
    new = {'catalog_version': 1, 'services': []}
    diff = survey_service.diff_maps(old, new)
    removed = {row['id'] for row in diff['services']['removed']}
    assert 'nginx' in removed


# --- Observed-mode surface (restored by plan 82 §D) ------------------------- #
# The migration↔model drift gate (test_migration_schema_drift) surfaced that
# migrations 065/068 carried servers.management_mode /
# allow_agent_update_observed while the model fields, MANAGEMENT_MODES,
# is_managed and the registry counter were lost in the recovery rebuild —
# leaving these routes raising AttributeError. The model surface is back;
# NOTE the dispatch-level Observe guard is still hollow (plan 82 §H), so
# observed_blocked_count only counts explicitly recorded blocks.


def test_is_managed_property(app):
    from app import db
    s = _mk_server(db)
    assert s.management_mode == 'managed'
    assert s.is_managed is True
    s.management_mode = 'observed'
    assert s.is_managed is False


def test_switch_management_mode(app, client):
    from app import db
    from app.models.server import Server
    from factories import make_user, headers_for
    with app.app_context():
        server_id = _mk_server(db).id
        admin_headers = headers_for(make_user(db, role='admin'))

    res = client.post(f'/api/v1/servers/{server_id}/management-mode',
                      json={'mode': 'observed',
                            'allow_agent_update_observed': True},
                      headers=admin_headers)
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body['management_mode'] == 'observed'
    assert body['allow_agent_update_observed'] is True
    assert body['observed_blocked_count'] == 0

    # The flip must PERSIST — before the columns were restored, the
    # assignment landed on a transient Python attribute and evaporated.
    with app.app_context():
        db.session.expire_all()
        stored = Server.query.get(server_id)
        assert stored.management_mode == 'observed'
        assert stored.allow_agent_update_observed is True

    res = client.get(f'/api/v1/servers/{server_id}/observed-status',
                     headers=admin_headers)
    assert res.status_code == 200
    assert res.get_json()['management_mode'] == 'observed'


def test_switch_management_mode_rejects_bad_value(app, client):
    from app import db
    from factories import make_user, headers_for
    with app.app_context():
        server_id = _mk_server(db).id
        admin_headers = headers_for(make_user(db, role='admin'))

    res = client.post(f'/api/v1/servers/{server_id}/management-mode',
                      json={'mode': 'yolo'}, headers=admin_headers)
    assert res.status_code == 400
    assert 'mode must be one of' in res.get_json()['error']


def test_server_to_dict_includes_mode(app):
    from app import db
    s = _mk_server(db)
    d = s.to_dict()
    assert d['management_mode'] == 'managed'
    assert d['allow_agent_update_observed'] is False
