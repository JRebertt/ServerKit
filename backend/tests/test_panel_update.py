"""One-click panel self-update — capability gates, launch contract, API.

Everything is faked: no test here touches systemd, the real updater script, or
/var/log. The interesting contracts are (a) the capability gates that keep the
button away from installs where the updater would be wrong or dangerous, and
(b) that the launch goes through systemd-run (its own cgroup) — a plain child
process would die when the updater restarts the panel's own unit.
"""
import os

import pytest

from app.services import panel_update_service as svc


def _systemd_box(monkeypatch, tmp_path):
    """Fake a root systemd install with the updater script present."""
    script_dir = tmp_path / 'scripts'
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / 'update.sh').write_text('#!/bin/bash\n')
    monkeypatch.setattr(svc, '_is_windows', lambda: False)
    monkeypatch.setattr(svc, '_in_docker', lambda: False)
    monkeypatch.setattr(svc, '_is_root', lambda: True)
    monkeypatch.setattr(svc, 'get_install_dir', lambda: str(tmp_path))
    monkeypatch.setattr(svc.shutil, 'which', lambda tool: f'/usr/bin/{tool}')


# ── Capability gates ─────────────────────────────────────────────────────────

def test_windows_dev_server_is_unsupported(monkeypatch):
    monkeypatch.setattr(svc, '_is_windows', lambda: True)
    cap = svc.get_capability()
    assert cap == {'supported': False, 'mode': 'unsupported',
                   'reason': 'Self-update requires a Linux install.'}


def test_docker_install_reports_docker_mode_with_host_instructions(monkeypatch):
    monkeypatch.setattr(svc, '_is_windows', lambda: False)
    monkeypatch.setattr(svc, '_in_docker', lambda: True)
    cap = svc.get_capability()
    assert cap['supported'] is False
    assert cap['mode'] == 'docker'
    assert 'docker compose pull' in cap['reason']


def test_non_root_process_is_unsupported(monkeypatch):
    monkeypatch.setattr(svc, '_is_windows', lambda: False)
    monkeypatch.setattr(svc, '_in_docker', lambda: False)
    monkeypatch.setattr(svc, '_is_root', lambda: False)
    cap = svc.get_capability()
    assert cap['supported'] is False
    assert 'root' in cap['reason']


def test_missing_updater_script_is_unsupported(monkeypatch, tmp_path):
    _systemd_box(monkeypatch, tmp_path)
    os.remove(tmp_path / 'scripts' / 'update.sh')
    cap = svc.get_capability()
    assert cap['supported'] is False
    assert 'update.sh' in cap['reason']


def test_missing_systemd_run_is_unsupported(monkeypatch, tmp_path):
    _systemd_box(monkeypatch, tmp_path)
    monkeypatch.setattr(svc.shutil, 'which', lambda tool: None)
    cap = svc.get_capability()
    assert cap['supported'] is False
    assert 'systemd-run' in cap['reason']


def test_root_systemd_install_is_supported(monkeypatch, tmp_path):
    _systemd_box(monkeypatch, tmp_path)
    cap = svc.get_capability()
    assert cap['supported'] is True
    assert cap['mode'] == 'systemd'
    assert cap['script'] == os.path.join(str(tmp_path), 'scripts', 'update.sh')


# ── Launch contract ──────────────────────────────────────────────────────────

def test_start_update_launches_through_systemd_run(monkeypatch, tmp_path):
    _systemd_box(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, 'is_running', lambda: False)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return {'success': True, 'output': '', 'stderr': '', 'error': None,
                'returncode': 0}

    monkeypatch.setattr(svc, 'run_checked', fake_run)
    result = svc.start_update()

    assert result == {'started': True, 'unit': svc.UPDATE_UNIT}
    # reset-failed first (a stale failed unit blocks reusing the name) …
    assert calls[0][:2] == ['systemctl', 'reset-failed']
    # … then the actual launch, detached into its own transient unit.
    launch = calls[1]
    assert launch[0] == 'systemd-run'
    assert '--unit' in launch and svc.UPDATE_UNIT in launch
    assert '--collect' in launch
    assert launch[-1].endswith('update.sh')


def test_start_update_refuses_unsupported_install(monkeypatch):
    monkeypatch.setattr(svc, '_is_windows', lambda: True)
    from app.exceptions import ValidationError
    with pytest.raises(ValidationError):
        svc.start_update()


def test_start_update_refuses_concurrent_run(monkeypatch, tmp_path):
    _systemd_box(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, 'is_running', lambda: True)
    from app.exceptions import ConflictError
    with pytest.raises(ConflictError):
        svc.start_update()


def test_start_update_surfaces_launch_failure(monkeypatch, tmp_path):
    _systemd_box(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, 'is_running', lambda: False)
    monkeypatch.setattr(svc, 'run_checked', lambda cmd, **kw: {
        'success': False, 'output': '', 'stderr': 'unit exists',
        'error': 'systemd-run failed', 'returncode': 1})
    from app.exceptions import ValidationError
    with pytest.raises(ValidationError, match='systemd-run failed'):
        svc.start_update()


# ── Log parsing ──────────────────────────────────────────────────────────────

def test_latest_log_strips_ansi_and_detects_outcome(monkeypatch, tmp_path):
    log_dir = tmp_path / 'logs'
    log_dir.mkdir()
    monkeypatch.setattr(svc, 'LOG_DIR', str(log_dir))

    (log_dir / 'update-20260830-010101.log').write_text('older run\n')
    newest = log_dir / 'update-20260831-020202.log'
    newest.write_text('step one\n\x1b[1m\x1b[32m✔  Update complete\x1b[0m\n',
                      encoding='utf-8')
    os.utime(log_dir / 'update-20260830-010101.log', (1, 1))

    log = svc.latest_log()
    assert log['path'] == str(newest)
    assert '\x1b' not in log['tail']
    assert log['outcome'] == 'success'


def test_latest_log_detects_rollback(monkeypatch, tmp_path):
    log_dir = tmp_path / 'logs'
    log_dir.mkdir()
    monkeypatch.setattr(svc, 'LOG_DIR', str(log_dir))
    (log_dir / 'update-20260831-030303.log').write_text(
        'Rolled back to /opt/serverkit-slots/a and it is healthy.\n')
    assert svc.latest_log()['outcome'] == 'rolled_back'


def test_latest_log_none_when_nothing_logged(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, 'LOG_DIR', str(tmp_path / 'nope'))
    assert svc.latest_log() is None


# ── API surface ──────────────────────────────────────────────────────────────

def _fake_status():
    return {'capability': {'supported': True, 'mode': 'systemd',
                           'reason': None, 'script': '/x/update.sh'},
            'running': False, 'unit': svc.UPDATE_UNIT,
            'version': '9.9.9', 'log': None}


def test_status_requires_admin(client, viewer_headers):
    response = client.get('/api/v1/system/update', headers=viewer_headers)
    assert response.status_code == 403


def test_status_reports_snapshot(client, auth_headers, monkeypatch):
    monkeypatch.setattr(svc, 'get_status', _fake_status)
    response = client.get('/api/v1/system/update', headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()['version'] == '9.9.9'


def test_start_requires_admin(client, viewer_headers):
    response = client.post('/api/v1/system/update', headers=viewer_headers,
                           json={'confirm': True})
    assert response.status_code == 403


def test_start_requires_explicit_confirmation(client, auth_headers):
    response = client.post('/api/v1/system/update', headers=auth_headers,
                           json={})
    assert response.status_code == 400
    assert 'confirm' in response.get_json()['error'].lower()


def test_start_launches_and_returns_202(client, auth_headers, monkeypatch):
    monkeypatch.setattr(svc, 'start_update',
                        lambda: {'started': True, 'unit': svc.UPDATE_UNIT})
    response = client.post('/api/v1/system/update', headers=auth_headers,
                           json={'confirm': True})
    assert response.status_code == 202
    assert response.get_json() == {'started': True, 'unit': svc.UPDATE_UNIT}


def test_start_conflict_when_already_running(client, auth_headers, monkeypatch):
    from app.exceptions import ConflictError

    def boom():
        raise ConflictError('An update is already running.')

    monkeypatch.setattr(svc, 'start_update', boom)
    response = client.post('/api/v1/system/update', headers=auth_headers,
                           json={'confirm': True})
    assert response.status_code == 409
