"""Proving tests for the inline guards added in the round-3 authz audit.

The two sweep tests can only see so much: ``test_route_authz_static.py`` proves
a route *reaches* an authorization primitive, and
``test_route_authz_sweep.py`` proves a viewer does not get a 2xx. Neither can
tell whether the guard admits the right callers, and neither looks below the
API layer at all. These are the behavioural checks for the three fixes in that
round whose shape the sweeps cannot express:

* ``api_keys.update_key`` — the *only* key route with no role bar, so a viewer
  demoted after minting a key could still widen its scopes to ``['*']``.
  Invisible to the sweep because the dummy key id 404s first.
* ``deployment_jobs.simulate_deployment`` — gated only by the demo flag, and
  ``DEMO_DEPLOYS_ENABLED`` is on in testing, so a viewer could create real
  ``DeploymentJob`` rows.
* ``nginx_advanced_service.preview_diff`` — a body-supplied ``domain`` joined
  straight onto ``SITES_AVAILABLE``. The API layer now admits only admins, but
  the traversal guard belongs in the service, where every future caller
  inherits it.
"""
import pytest

from factories import make_user, headers_for


# --------------------------------------------------------- API-key metadata

def _key_for(db, user):
    from app.services.api_key_service import ApiKeyService
    api_key, _raw = ApiKeyService.create_key(user.id, name='round3', scopes=['read'])
    return api_key


def test_viewer_cannot_widen_the_scopes_of_their_own_api_key(client, db_session):
    """Ownership is not the question — capability is.

    ``ApiKeyService.update_key`` already filters by ``user_id``, so this was
    never an IDOR; the hole was that a viewer could take a key they legally own
    and hand it ``scopes=['*']``, which every API-key-authenticated route then
    honours.
    """
    viewer = make_user(db_session, role='viewer')
    key = _key_for(db_session, viewer)

    resp = client.put(f'/api/v1/api-keys/{key.id}',
                      json={'scopes': ['*'], 'tier': 'unlimited'},
                      headers=headers_for(viewer))

    assert resp.status_code == 403
    db_session.session.refresh(key)
    assert key.get_scopes() == ['read'], 'the viewer widened their key anyway'


def test_developer_can_still_update_their_own_api_key(client, db_session):
    """Non-vacuity: the gate is a role bar, not a freeze on the route."""
    dev = make_user(db_session, role='developer')
    key = _key_for(db_session, dev)

    resp = client.put(f'/api/v1/api-keys/{key.id}',
                      json={'name': 'renamed'},
                      headers=headers_for(dev))

    assert resp.status_code == 200
    assert resp.get_json()['name'] == 'renamed'


# ------------------------------------------------------ demo deployment jobs

def test_viewer_cannot_start_a_simulated_deployment(app, client, db_session):
    """``DEMO_DEPLOYS_ENABLED`` is a *visibility* flag, not an authorization
    one — with it on, job creation still has to be a developer capability."""
    from app.models.deployment_job import DeploymentJob

    app.config['DEMO_DEPLOYS_ENABLED'] = True
    before = DeploymentJob.query.count()

    resp = client.post('/api/v1/deployment-jobs/simulate?wait=true',
                       json={'scenario': 'success', 'speed': 'instant'},
                       headers=headers_for(make_user(db_session, role='viewer')))

    assert resp.status_code == 403
    assert DeploymentJob.query.count() == before, 'a viewer created a job row'


# --------------------------------------------- nginx vhost path containment

@pytest.mark.parametrize('domain', [
    '../../../../etc/passwd',
    '..',
    '.',
    'sub/dir/example.com',
    '',
    None,
])
def test_preview_diff_refuses_anything_that_is_not_a_plain_filename(app, domain):
    """``domain`` is joined onto ``/etc/nginx/sites-available``; a traversing
    value turns a config preview into an arbitrary file read, since the diff
    body carries the current file's contents verbatim."""
    from app.services.nginx_advanced_service import NginxAdvancedService

    result = NginxAdvancedService.preview_diff(domain, 'new config')

    assert result == {'error': 'invalid domain'}


def test_preview_diff_still_diffs_a_plain_domain(app, tmp_path, monkeypatch):
    """Non-vacuity: a normal vhost name is accepted and really is diffed."""
    from app.services.nginx_advanced_service import NginxAdvancedService

    monkeypatch.setattr(NginxAdvancedService, 'SITES_AVAILABLE', str(tmp_path))
    (tmp_path / 'example.com').write_text('server { listen 80; }\n', encoding='utf-8')

    result = NginxAdvancedService.preview_diff('example.com', 'server { listen 443; }\n')

    assert 'error' not in result
    assert result['has_changes'] is True
    assert 'listen 443' in result['diff']


def test_preview_diff_route_reports_the_refusal_as_a_400(client, db_session):
    """The API must not hand the service's error dict back as a 200 success."""
    resp = client.post('/api/v1/nginx/advanced/diff',
                       json={'domain': '../../etc/passwd', 'config': 'x'},
                       headers=headers_for(make_user(db_session, role='admin')))

    assert resp.status_code == 400
    assert resp.get_json() == {'error': 'invalid domain'}
