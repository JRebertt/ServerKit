"""authorized_keys list ↔ remove round trip.

get_ssh_keys numbered keys over raw file lines (comments and blanks included)
while remove_ssh_key popped that id from a list of key lines only, so any
comment banner in authorized_keys shifted every id and delete-by-id removed
the wrong key — the same write/read join-key mismatch as the cron #117 bug.
These tests pin the cycle: list → remove by the listed id → list again and
assert the right key went away and the file kept its shape.
"""

import pytest

from app.services.security_service import SecurityService


KEY_A = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKeyAlicelicealice alice@laptop'
KEY_B = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKeyBobbobbobbobbob bob@desktop'
KEY_C = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABKeyCarolcarolcarol carol@ci'


@pytest.fixture
def auth_keys(tmp_path, monkeypatch):
    """Point the service at a temp authorized_keys and stub the fingerprint
    subprocess so no ssh-keygen is spawned."""
    path = tmp_path / 'authorized_keys'
    monkeypatch.setattr(SecurityService, 'SSH_DIR', str(tmp_path))
    monkeypatch.setattr(SecurityService, 'AUTHORIZED_KEYS', str(path))
    monkeypatch.setattr(
        SecurityService, '_get_key_fingerprint',
        classmethod(lambda cls, line: 'SHA256:' + line.split()[1][:8]))
    return path


def _write(path, *lines):
    path.write_text('\n'.join(lines) + '\n')


def test_ids_index_key_lines_not_file_lines(auth_keys):
    _write(auth_keys, '# cloud-init banner', '', KEY_A, KEY_B)

    result = SecurityService.get_ssh_keys()
    assert result['success']
    assert [k['id'] for k in result['keys']] == [0, 1]
    assert result['keys'][0]['comment'] == 'alice@laptop'


def test_remove_by_listed_id_removes_that_key(auth_keys):
    _write(auth_keys, '# cloud-init banner', KEY_A, KEY_B, KEY_C)

    listed = SecurityService.get_ssh_keys()['keys']
    alice = next(k for k in listed if k['comment'] == 'alice@laptop')

    assert SecurityService.remove_ssh_key(alice['id'])['success']

    content = auth_keys.read_text()
    assert 'alice@laptop' not in content
    assert 'bob@desktop' in content
    assert 'carol@ci' in content


def test_remove_last_listed_key_is_valid(auth_keys):
    # With the old raw-line ids, the banner made the last key's id exceed
    # len(key_lines) and delete answered "Invalid key ID".
    _write(auth_keys, '# banner one', '# banner two', KEY_A, KEY_B)

    last = SecurityService.get_ssh_keys()['keys'][-1]
    result = SecurityService.remove_ssh_key(last['id'])
    assert result['success'], result
    assert 'bob@desktop' not in auth_keys.read_text()


def test_remove_preserves_comment_positions(auth_keys):
    _write(auth_keys, '# alice below', KEY_A, '# bob below', KEY_B)

    assert SecurityService.remove_ssh_key(0)['success']
    assert auth_keys.read_text().splitlines() == [
        '# alice below', '# bob below', KEY_B]


def test_ids_stay_joined_across_removals(auth_keys):
    _write(auth_keys, '# banner', KEY_A, KEY_B, KEY_C)

    for victim in ('bob@desktop', 'carol@ci', 'alice@laptop'):
        key = next(k for k in SecurityService.get_ssh_keys()['keys']
                   if k['comment'] == victim)
        assert SecurityService.remove_ssh_key(key['id'])['success']
        assert victim not in auth_keys.read_text()

    assert SecurityService.get_ssh_keys()['keys'] == []


def test_add_appends_cleanly_without_trailing_newline(auth_keys):
    auth_keys.write_text(KEY_A)  # no trailing newline

    assert SecurityService.add_ssh_key(KEY_B)['success']

    lines = auth_keys.read_text().splitlines()
    assert lines == [KEY_A, KEY_B]


def test_add_duplicate_matches_key_data_not_substring(auth_keys):
    _write(auth_keys, KEY_A)

    dup = SecurityService.add_ssh_key(KEY_A + ' renamed@host')
    assert not dup['success']

    # A different key must not be rejected just because its text shares a
    # prefix with an existing line.
    assert SecurityService.add_ssh_key(KEY_B)['success']
