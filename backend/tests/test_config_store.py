"""The ConfigStore contract (plan 75 §F4).

Five services shipped byte-identical save_config copies; the helpers in
``app.utils.config_store`` are now the one place those mechanics live. These
tests pin the behaviour the copies had — byte-for-byte compatibility is the
point of the consolidation: indented JSON, parent dir created, corrupt file
reads as the default, and the service-dict return shape.
"""
import json
import os

from app.utils.config_store import load_json_config, save_json_config


def test_missing_file_reads_as_the_default(tmp_path):
    default = {'enabled': False}
    assert load_json_config(str(tmp_path / 'cfg.json'), default) == default


def test_the_default_is_not_shared_between_calls(tmp_path):
    """Callers mutate what they get back; a shared default would leak."""
    default = {'items': []}
    first = load_json_config(str(tmp_path / 'cfg.json'), default)
    first['items'].append('x')
    assert load_json_config(str(tmp_path / 'cfg.json'), default) == default


def test_corrupt_file_reads_as_the_default_never_raises(tmp_path):
    path = tmp_path / 'cfg.json'
    path.write_text('{"truncated":')
    assert load_json_config(str(path), {'a': 1}) == {'a': 1}


def test_save_creates_the_parent_dir_and_writes_indented_json(tmp_path):
    path = tmp_path / 'nested' / 'cfg.json'
    result = save_json_config(str(path), {'b': 2})

    assert result == {'success': True, 'message': 'Configuration saved'}
    assert json.loads(path.read_text()) == {'b': 2}
    assert path.read_text() == json.dumps({'b': 2}, indent=2)


def test_save_failure_returns_the_error_shape(tmp_path):
    blocked = tmp_path / 'a-file'
    blocked.write_text('x')
    result = save_json_config(str(blocked / 'cfg.json'), {'b': 2})

    assert result['success'] is False
    assert result['error']


def test_round_trip(tmp_path):
    path = str(tmp_path / 'cfg.json')
    save_json_config(path, {'retention_days': 30})
    assert load_json_config(path, {}) == {'retention_days': 30}


# --------------------------------------------------------------------------- #
# The converted services actually go through the one door
# --------------------------------------------------------------------------- #

def test_converted_services_use_the_store(tmp_path, monkeypatch):
    """Spot-check two of the converted services end to end: their get/save
    config must round-trip through the store with unchanged semantics."""
    from app.services.backup_service import BackupService
    from app.services.git_service import GitService

    backup_path = str(tmp_path / 'backup.json')
    monkeypatch.setattr(BackupService, 'BACKUP_CONFIG', backup_path)
    assert BackupService.get_config()['retention_days'] == 30
    assert BackupService.save_config({'retention_days': 7})['success'] is True
    assert BackupService.get_config() == {'retention_days': 7}

    git_path = str(tmp_path / 'deployments.json')
    monkeypatch.setattr(GitService, 'DEPLOY_CONFIG', git_path)
    default = GitService.get_config()
    assert 'webhook_secret' in default and default['apps'] == {}
    assert GitService.save_config({'apps': {'1': {}}})['success'] is True
    assert GitService.get_config() == {'apps': {'1': {}}}
