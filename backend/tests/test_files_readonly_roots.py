"""Plan 73 item 3 — the File Manager's "Web config" quick-access shortcut.

The rail links the local target at /etc/nginx, but /etc was never in
ALLOWED_ROOTS, so the shortcut was a guaranteed 403 for every user — our own
regression, shipped after the review that flagged the surrounding SSL story.

/etc/nginx is now reachable, but read-only: the panel generates those vhosts
itself (a hand edit is silently overwritten on the next domain change) and an
editable /etc/nginx would hand anyone holding files.write a root-owned config
that the panel itself reloads.

Path behaviour is asserted against monkeypatched roots rather than the literal
/etc/nginx, because realpath('/etc/nginx') is C:\\etc\\nginx on a Windows dev
box; the literal constants get their own assertion below.
"""
import os

import pytest

from app.exceptions import PermissionDeniedError
from app.services.file_service import FileService


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """An allowed root with a read-only subtree inside it.

    Mirrors the production shape: READ_ONLY_ROOTS only bites while the path is
    also inside ALLOWED_ROOTS.
    """
    ro = tmp_path / 'ro'
    rw = tmp_path / 'rw'
    ro.mkdir()
    rw.mkdir()
    (ro / 'nginx.conf').write_text('server { }\n', encoding='utf-8')
    monkeypatch.setattr(FileService, 'ALLOWED_ROOTS', [str(tmp_path)])
    monkeypatch.setattr(FileService, 'READ_ONLY_ROOTS', [str(ro)])
    return {'ro': ro, 'rw': rw, 'conf': ro / 'nginx.conf'}


# --------------------------------------------------------------------------- #
# The shortcut resolves at all (the actual bug)
# --------------------------------------------------------------------------- #
def test_etc_nginx_is_allowed_but_read_only():
    """The literal constants behind the quick-access link. /etc itself stays
    shut — the shortcut needed one subtree, not the whole config tree."""
    assert '/etc/nginx' in FileService.ALLOWED_ROOTS
    assert '/etc/nginx' in FileService.READ_ONLY_ROOTS
    assert '/etc' not in FileService.ALLOWED_ROOTS
    assert not FileService.is_path_allowed('/etc/passwd')
    assert not FileService.is_path_allowed('/etc/shadow')


def test_read_only_subtree_is_browsable(roots):
    assert FileService.is_path_allowed(str(roots['ro']))
    assert FileService.is_path_allowed(str(roots['conf']))
    assert FileService.is_path_readonly(str(roots['conf']))
    assert not FileService.is_path_writable(str(roots['conf']))


def test_writable_root_is_unaffected(roots):
    target = roots['rw'] / 'index.html'
    assert FileService.is_path_allowed(str(target))
    assert not FileService.is_path_readonly(str(target))
    assert FileService.is_path_writable(str(target))


def test_paths_outside_every_root_stay_denied(roots, tmp_path):
    outside = tmp_path.parent / 'elsewhere.txt'
    assert not FileService.is_path_allowed(str(outside))
    assert not FileService.is_path_writable(str(outside))


# --------------------------------------------------------------------------- #
# Every mutating entry point refuses — and refuses before touching disk
# --------------------------------------------------------------------------- #
def test_write_file_refuses_and_leaves_content_untouched(roots):
    original = roots['conf'].read_text(encoding='utf-8')
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.write_file(str(roots['conf']), 'server { evil; }')

    assert roots['conf'].read_text(encoding='utf-8') == original
    # ...and no .bak was dropped next to it either.
    assert not (roots['ro'] / 'nginx.conf.bak').exists()


def test_create_file_refuses(roots):
    target = roots['ro'] / 'new.conf'
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.create_file(str(target), 'x')

    assert not target.exists()


def test_create_directory_refuses(roots):
    target = roots['ro'] / 'sites-enabled'
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.create_directory(str(target))

    assert not target.exists()


def test_delete_refuses(roots):
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.delete(str(roots['conf']))

    assert roots['conf'].exists()


def test_rename_refuses(roots):
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.rename(str(roots['conf']), 'nginx.conf.disabled')

    assert roots['conf'].exists()
    assert not (roots['ro'] / 'nginx.conf.disabled').exists()


def test_change_permissions_refuses(roots):
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.change_permissions(str(roots['conf']), '777')


def test_move_refuses_in_both_directions(roots):
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.move(str(roots['conf']), str(roots['rw'] / 'nginx.conf'))
    assert roots['conf'].exists()

    donor = roots['rw'] / 'payload.conf'
    donor.write_text('x', encoding='utf-8')
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.move(str(donor), str(roots['ro'] / 'payload.conf'))
    assert not (roots['ro'] / 'payload.conf').exists()
    assert donor.exists()


def test_copy_out_is_allowed_but_copy_in_is_refused(roots):
    """Taking a vhost out to keep is reading; writing one in is not."""
    out = FileService.copy(str(roots['conf']), str(roots['rw'] / 'nginx.conf'))
    assert out == {'src': str(roots['conf']), 'dest': str(roots['rw'] / 'nginx.conf')}
    assert (roots['rw'] / 'nginx.conf').exists()
    assert roots['conf'].exists()

    donor = roots['rw'] / 'payload.conf'
    donor.write_text('x', encoding='utf-8')
    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.copy(str(donor), str(roots['ro'] / 'payload.conf'))
    assert not (roots['ro'] / 'payload.conf').exists()


# --------------------------------------------------------------------------- #
# A symlink out of a writable root must not launder a write into the read-only
# subtree — the check resolves before comparing.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.name == 'nt', reason='symlink creation needs privilege on Windows')
def test_symlink_into_read_only_root_does_not_launder_a_write(roots):
    link = roots['rw'] / 'sneaky.conf'
    link.symlink_to(roots['conf'])

    with pytest.raises(PermissionDeniedError, match='read-only'):
        FileService.write_file(str(link), 'server { evil; }')

    assert roots['conf'].read_text(encoding='utf-8') == 'server { }\n'
