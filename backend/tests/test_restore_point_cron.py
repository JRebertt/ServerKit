"""Plan 81 M2: local CRON restore-point payloads and service hooks."""

from copy import deepcopy

import pytest

from app.services.cron_service import CronService
from app.services import restore_point_adapter_cron as adapter


@pytest.fixture
def cron_state(tmp_path, monkeypatch):
    import app.services.cron_service as module

    monkeypatch.setattr(module, 'JOBS_FILE', str(tmp_path / 'cron_jobs.json'))
    monkeypatch.setattr(CronService, 'is_linux', classmethod(lambda cls: True))
    state = {'crontab': '# hand-written\n0 1 * * * /usr/bin/original\n'}
    monkeypatch.setattr(
        CronService, '_read_crontab',
        classmethod(lambda cls: state['crontab']),
    )

    def install(cls, content):
        state['crontab'] = content
        return None

    monkeypatch.setattr(CronService, '_install_crontab', classmethod(install))
    CronService._save_jobs_metadata({'jobs': {
        'job_1': {
            'name': 'Original',
            'schedule': '0 1 * * *',
            'command': '/usr/bin/original',
            'enabled': True,
            'tracked': False,
            'application_id': 7,
        },
    }})
    return state


def test_capture_contains_full_crontab_and_metadata(cron_state):
    payload = adapter.capture('cron')

    assert payload['crontab'] == cron_state['crontab']
    assert payload['metadata']['jobs']['job_1']['application_id'] == 7


def test_capture_fails_when_linux_crontab_is_unreadable(cron_state, monkeypatch):
    monkeypatch.setattr(
        CronService, '_read_crontab', classmethod(lambda cls: None),
    )

    with pytest.raises(RuntimeError, match='Could not read'):
        adapter.capture('cron')


def test_capture_fails_when_metadata_is_corrupt(cron_state, monkeypatch):
    import app.services.cron_service as module

    with open(module.JOBS_FILE, 'w') as handle:
        handle.write('{not-json')

    with pytest.raises(RuntimeError, match='metadata is unreadable'):
        adapter.capture('cron')


def test_restore_round_trip_reconverges_both_components(cron_state):
    saved = adapter.capture('cron')
    cron_state['crontab'] = '*/5 * * * * /usr/bin/changed\n'
    CronService._save_jobs_metadata({'jobs': {
        'changed': {'schedule': '*/5 * * * *', 'command': '/usr/bin/changed'},
    }})

    result = adapter.restore('cron', saved)

    assert result['success'] is True
    assert adapter.capture('cron') == saved


def test_restore_rolls_crontab_back_when_metadata_write_fails(
        cron_state, monkeypatch):
    target = {
        'crontab': '0 4 * * * /usr/bin/target\n',
        'metadata': {'jobs': {'target': {'command': '/usr/bin/target'}}},
    }
    before = adapter.capture('cron')
    real_save = CronService._save_jobs_metadata.__func__
    writes = []

    def fail_target_once(cls, metadata):
        writes.append(deepcopy(metadata))
        if len(writes) == 1:
            raise OSError('disk full')
        return real_save(cls, metadata)

    monkeypatch.setattr(
        CronService, '_save_jobs_metadata', classmethod(fail_target_once),
    )

    result = adapter.restore('cron', target)

    assert result['success'] is False
    assert result['rolled_back'] is True
    assert cron_state['crontab'] == before['crontab']
    assert CronService._load_jobs_metadata() == before['metadata']


def test_metadata_only_mutators_checkpoint_and_alert_flag_is_in_service(
        app, tmp_path, monkeypatch):
    import app.services.cron_service as module
    from app.services import restore_point_service

    monkeypatch.setattr(module, 'JOBS_FILE', str(tmp_path / 'cron_jobs.json'))
    monkeypatch.setattr(CronService, 'is_linux', classmethod(lambda cls: False))
    existing = restore_point_service.get_adapter('cron')
    restore_point_service.register_adapter('cron', adapter)
    captured = []
    monkeypatch.setattr(
        restore_point_service, 'capture',
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    try:
        created = CronService.add_job(
            '0 0 * * *', '/usr/bin/task', application_id=9,
        )
        job_id = created['job_id']
        CronService.update_job(job_id, description='metadata only')
        CronService.set_tracking(job_id, True, alert_on_failure=False)
        assert CronService.get_job(job_id)['alert_on_failure'] is False
        CronService.toggle_job(job_id, False)
        CronService.remove_job(job_id)
    finally:
        if existing is None:
            restore_point_service.ADAPTERS.pop('cron', None)
        else:
            restore_point_service.register_adapter('cron', existing)

    actions = [item[1]['label'] for item in captured]
    assert actions == [
        'before cron.add_job',
        'before cron.update_job',
        'before cron.set_tracking',
        'before cron.toggle_job',
        'before cron.remove_job',
    ]


def test_application_bulk_suspend_captures_once(app, tmp_path, monkeypatch):
    import app.services.cron_service as module
    from app.services import restore_point_service

    monkeypatch.setattr(module, 'JOBS_FILE', str(tmp_path / 'cron_jobs.json'))
    monkeypatch.setattr(CronService, 'is_linux', classmethod(lambda cls: False))
    CronService._save_jobs_metadata({'jobs': {
        'one': {'application_id': 4, 'enabled': True},
        'two': {'application_id': 4, 'enabled': True},
    }})
    existing = restore_point_service.get_adapter('cron')
    restore_point_service.register_adapter('cron', adapter)
    captured = []
    monkeypatch.setattr(
        restore_point_service, 'capture',
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    try:
        assert CronService.suspend_for_application(4) == 2
        assert CronService.resume_for_application(4) == 2
        assert CronService.clear_application(4) == 2
    finally:
        if existing is None:
            restore_point_service.ADAPTERS.pop('cron', None)
        else:
            restore_point_service.register_adapter('cron', existing)

    assert [item[1]['label'] for item in captured] == [
        'before cron.suspend_for_application',
        'before cron.resume_for_application',
        'before cron.clear_application',
    ]
