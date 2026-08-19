"""Files API on the typed-error contract (plan 76, C envelopes reference).

The file manager is the reference conversion for milestone C's envelope
decision: **services raise typed errors; routes return data.** Before this,
``FileService`` returned ``{'success': False, 'error': <prose>}`` and
``files.py`` chose status codes by sniffing the prose
(``403 if 'denied' in error else 400``) — rephrasing a message silently
changed the status code.

These tests pin the visible consequences end to end through the real routes
and the global ``ApplicationError`` handler:

  * denials are 403 regardless of wording,
  * missing paths are 404 (previously a sniffed 400),
  * already-exists is 409 (previously 400),
  * bad input is 400 with the ``error`` key the frontend reads,
  * success bodies keep their compatibility ``success: True`` key.

Everything runs against monkeypatched tmp roots so it works on any OS.
"""
import pytest

from app.services.file_service import FileService


@pytest.fixture
def roots(tmp_path, monkeypatch):
    ro = tmp_path / 'ro'
    rw = tmp_path / 'rw'
    ro.mkdir()
    rw.mkdir()
    (ro / 'nginx.conf').write_text('server { }\n', encoding='utf-8')
    (rw / 'app.conf').write_text('x = 1\n', encoding='utf-8')
    monkeypatch.setattr(FileService, 'ALLOWED_ROOTS', [str(tmp_path)])
    monkeypatch.setattr(FileService, 'READ_ONLY_ROOTS', [str(ro)])
    return {'ro': ro, 'rw': rw, 'conf': ro / 'nginx.conf', 'file': rw / 'app.conf'}


def _get(client, auth_headers, url):
    return client.get(url, headers=auth_headers)


def _post(client, auth_headers, url, body):
    return client.post(url, json=body, headers=auth_headers)


# ---------------------------------------------------------------- statuses #

def test_denied_path_is_403_not_a_sniffed_400(client, auth_headers, tmp_path):
    """Outside every allowed root → PermissionDeniedError → 403."""
    resp = _get(client, auth_headers,
                f'/api/v1/files/read?path={tmp_path.parent / "elsewhere.txt"}')
    assert resp.status_code == 403
    body = resp.get_json()
    assert body['code'] == 'permission_denied'
    assert 'error' in body


def test_missing_file_is_404(client, auth_headers, roots):
    resp = _get(client, auth_headers,
                f'/api/v1/files/read?path={roots["rw"] / "nope.txt"}')
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'not_found'


def test_create_over_existing_file_is_409(client, auth_headers, roots):
    resp = _post(client, auth_headers, '/api/v1/files/create',
                 {'path': str(roots['file'])})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'conflict'


def test_write_into_readonly_root_is_403_and_writes_nothing(client, auth_headers, roots):
    resp = _post(client, auth_headers, '/api/v1/files/write',
                 {'path': str(roots['conf']), 'content': 'server { evil; }'})
    assert resp.status_code == 403
    assert 'read-only' in resp.get_json()['error']
    assert roots['conf'].read_text(encoding='utf-8') == 'server { }\n'


def test_missing_required_field_is_400_with_error_key(client, auth_headers):
    resp = _get(client, auth_headers, '/api/v1/files/read')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Path is required'


def test_browse_of_a_file_is_400(client, auth_headers, roots):
    resp = _get(client, auth_headers,
                f'/api/v1/files/browse?path={roots["file"]}')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Not a directory'


# ----------------------------------------------------------- success shape #

def test_success_bodies_keep_the_compat_envelope(client, auth_headers, roots):
    """The wire shape existing consumers read: success key + data keys."""
    resp = _get(client, auth_headers,
                f'/api/v1/files/browse?path={roots["rw"]}')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['path'] == str(roots['rw'])
    assert isinstance(body['entries'], list)

    resp = _get(client, auth_headers,
                f'/api/v1/files/read?path={roots["file"]}')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['content'] == 'x = 1\n'


def test_create_still_answers_201(client, auth_headers, roots):
    target = roots['rw'] / 'fresh.txt'
    resp = _post(client, auth_headers, '/api/v1/files/create',
                 {'path': str(target), 'content': 'hi'})
    assert resp.status_code == 201
    assert resp.get_json()['success'] is True
    assert target.read_text(encoding='utf-8') == 'hi'


# ----------------------------------------------------- service-level raises #

def test_service_conflict_and_notfound_are_typed(roots):
    from app.exceptions import ConflictError, NotFoundError

    with pytest.raises(ConflictError):
        FileService.create_file(str(roots['file']), 'x')
    with pytest.raises(NotFoundError):
        FileService.delete(str(roots['rw'] / 'ghost.txt'))


def test_binary_read_carries_is_binary_detail(roots):
    from app.exceptions import ValidationError

    blob = roots['rw'] / 'blob.bin'
    blob.write_bytes(b'\x00\xff\x00\xff')
    with pytest.raises(ValidationError) as exc:
        FileService.read_file(str(blob))
    assert exc.value.details == {'is_binary': True}
