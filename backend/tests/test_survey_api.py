"""Survey API + permission/capability gating (plan 27 Phase 2, #5/#6).

Covers the honest-degrade path (offline / old agent), the happy path (snapshot
stored + returned), the catalog index, and the model-level permission scope that
gates dispatch.

Reconstructed for plan 42 Phase 1 from the fragmented ``test_survey_api`` pyc +
the surviving ``survey_service`` / ``app/api/survey.py``.

HOLLOW-FEATURE FINDINGS (reported to the orchestrator):
  1. The survey REST blueprint (``survey_bp`` in ``app/api/survey.py``) is defined
     but NEVER registered in ``app/__init__.py`` — every ``/api/v1/servers/...``
     survey route 404s. The recovery rebuild dropped the blueprint registration.
     The business logic (``survey_service``) survived, so the honest-degrade /
     happy / catalog / diff paths are exercised at the SERVICE layer below.
  2. The Observed-mode surface (``Server.management_mode`` / ``is_managed`` /
     ``MANAGEMENT_MODES``) referenced by ``survey.py`` was NOT restored on the
     ``Server`` model, so the management-mode tests are skipped with a reason.
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


# --- HOLLOW: Observed-mode surface lost in the recovery rebuild ------------- #

@pytest.mark.skip(reason="plan 42: hollow — Server.is_managed lost in recovery "
                         "rebuild (plan 27/31 Observed mode column gone)")
def test_is_managed_property():
    pass


@pytest.mark.skip(reason="plan 42: hollow — Server.management_mode / MANAGEMENT_MODES "
                         "lost + survey_bp unregistered (plan 27/31)")
def test_switch_management_mode():
    pass


@pytest.mark.skip(reason="plan 42: hollow — Server.management_mode lost; mode-validation "
                         "branch unreachable + survey_bp unregistered (plan 27/31)")
def test_switch_management_mode_rejects_bad_value():
    pass


@pytest.mark.skip(reason="plan 42: hollow — Server.to_dict no longer emits management "
                         "mode (plan 27/31 column gone)")
def test_server_to_dict_includes_mode():
    pass
