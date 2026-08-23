"""Plan 81 M1: generic restore-point store and lifecycle."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest


class MemoryAdapter:
    def __init__(self, state=None, coverage=None):
        self.state = state or {}
        self.restore_calls = 0
        self.capture_calls = 0
        self.diff_calls = 0
        self.coverage = coverage or []
        self.refusals = []
        self.nested_auto_capture = False

    def capture(self, scope_id, server_id=None):
        self.capture_calls += 1
        return deepcopy(self.state)

    def diff(self, old, new):
        from app.services.restore_point_service import diff_payloads
        self.diff_calls += 1
        return diff_payloads(old, new)

    def restore(self, scope_id, payload, actor=None, server_id=None):
        if self.nested_auto_capture:
            from app.services import restore_point_service
            self.state = {'mode': 'partial replay'}
            restore_point_service.auto_capture(
                'cron', scope_id, 'update', server_id=server_id,
            )
        self.restore_calls += 1
        self.state = deepcopy(payload)
        return {'success': True, 'scope_id': scope_id}

    def validate_restore(self, scope_id, payload, current_payload,
                         actor=None, server_id=None):
        return self.refusals


@pytest.fixture(autouse=True)
def clean_registry(app):
    from app.services import restore_point_service

    existing = dict(restore_point_service.ADAPTERS)
    restore_point_service.clear_adapters()
    yield
    restore_point_service.clear_adapters()
    restore_point_service.ADAPTERS.update(existing)


def test_registry_registers_replaces_and_validates(app):
    from app.services import restore_point_service as service

    first = MemoryAdapter()
    second = MemoryAdapter()
    assert service.register_adapter('cron', first) is first
    assert service.get_adapter('cron') is first
    service.register_adapter('cron', second)
    assert service.get_adapter('cron') is second

    with pytest.raises(ValueError, match=r'capture\(\)'):
        service.register_adapter('broken', {'restore': lambda *_a, **_k: None})
    with pytest.raises(ValueError, match=r'restore\(\)'):
        service.register_adapter('broken', {'capture': lambda *_a, **_k: {}})


def test_capture_dedupes_canonical_payload_and_audits(app):
    from app.models import AuditLog, RestorePoint
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'beta': 2, 'alpha': 1}, ['Only test state is covered.'])
    service.register_adapter('cron', adapter)

    first = service.capture('cron', 'cron', 'pre_mutation', label='before update')
    assert first is not None
    assert first.payload_json == '{"alpha":1,"beta":2}'
    assert first.keep is False
    assert first.expires_at is not None
    assert first.get_coverage()[0] == service.BASE_COVERAGE
    assert first.get_coverage()[-1] == 'Only test state is covered.'

    # Logically equal with the insertion order reversed: hash/capture dedupes.
    adapter.state = {'alpha': 1, 'beta': 2}
    again = service.capture('cron', 'cron', 'scheduled')
    assert again.id == first.id
    assert RestorePoint.query.count() == 1
    assert AuditLog.query.filter_by(
        action=AuditLog.ACTION_RESTORE_POINT_CREATE,
    ).count() == 1


def test_manual_capture_is_kept_and_setting_defaults_to_30(app):
    from app.services import restore_point_service as service
    from app.services.settings_service import SettingsService

    assert SettingsService.DEFAULT_SETTINGS['restore_point_retention_days']['value'] == 30
    service.register_adapter('env', MemoryAdapter({'PUBLIC': 'value'}))
    before = datetime.utcnow()
    point = service.capture('env', '42', 'manual', label='before maintenance')
    assert point.keep is True
    assert point.expires_at >= before + timedelta(days=29)


def test_manual_dedupe_promotes_existing_point_to_kept_tag(app):
    from app import db
    from app.models import AuditLog, RestorePoint
    from app.services import restore_point_service as service
    from factories import make_user

    service.register_adapter('env', MemoryAdapter({'PUBLIC': 'value'}))
    automatic = service.capture(
        'env', '42', 'pre_mutation', label='before env.update',
    )
    assert automatic.keep is False
    original_created_at = automatic.created_at
    actor = make_user(db, username='quicksave_actor')

    manual = service.capture(
        'env', '42', 'manual', label='known-good configuration', actor=actor,
    )
    assert manual.id == automatic.id
    assert manual.keep is True
    assert manual.trigger == 'manual'
    assert manual.actor_user_id == actor.id
    assert manual.label == 'known-good configuration'
    assert manual.created_at >= original_created_at
    assert manual.updated_at == manual.created_at
    assert RestorePoint.query.count() == 1
    audits = AuditLog.query.filter_by(
        action=AuditLog.ACTION_RESTORE_POINT_CREATE,
    ).order_by(AuditLog.id).all()
    assert len(audits) == 2
    assert audits[-1].get_details()['trigger'] == 'manual'


def test_capture_refuses_caller_owned_pending_transaction_without_touching_it(app):
    from app import db
    from app.models import SystemSettings
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'jobs': 1})
    service.register_adapter('cron', adapter)

    caller_row = SystemSettings(key='capture-boundary', value='new')
    db.session.add(caller_row)
    assert service.capture('cron', 'cron', 'pre_mutation') is None
    assert caller_row in db.session.new
    assert adapter.capture_calls == 0
    db.session.commit()

    caller_row.value = 'dirty'
    assert service.capture('cron', 'cron', 'pre_mutation') is None
    assert caller_row in db.session.dirty
    assert caller_row.value == 'dirty'
    assert adapter.capture_calls == 0
    db.session.commit()

    db.session.delete(caller_row)
    assert service.capture('cron', 'cron', 'pre_mutation') is None
    assert caller_row in db.session.deleted
    assert adapter.capture_calls == 0
    db.session.rollback()
    assert db.session.get(SystemSettings, caller_row.id) is not None


def test_capture_leaves_adapter_pending_data_for_caller(app):
    from app import db
    from app.models import RestorePoint, SystemSettings
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'jobs': 1})
    pending = SystemSettings(key='adapter-pending', value='owned-by-caller')

    def capture_with_pending_data(_scope_id, server_id=None):
        adapter.capture_calls += 1
        db.session.add(pending)
        return {'jobs': 1}

    adapter.capture = capture_with_pending_data
    service.register_adapter('cron', adapter)
    assert service.capture('cron', 'cron', 'pre_mutation') is None
    assert pending in db.session.new
    assert adapter.capture_calls == 1
    assert not any(isinstance(row, RestorePoint) for row in db.session.new)

    db.session.commit()
    assert SystemSettings.query.filter_by(key='adapter-pending').one().value == (
        'owned-by-caller'
    )


def test_capture_failure_is_best_effort(app):
    from app.models import RestorePoint
    from app.services import restore_point_service as service

    assert service.capture('missing', 'scope', 'pre_mutation') is None

    adapter = MemoryAdapter()
    adapter.capture = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('read failed'))
    service.register_adapter('cron', adapter)
    assert service.capture('cron', 'cron', 'pre_mutation') is None
    assert RestorePoint.query.count() == 0


def test_diff_uses_previous_point_in_same_scope(app):
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'mode': 'one', 'jobs': 1})
    service.register_adapter('cron', adapter)
    first = service.capture('cron', 'cron', 'pre_mutation')
    adapter.state = {'mode': 'two', 'jobs': 1}
    second = service.capture('cron', 'cron', 'pre_mutation')

    result = service.diff(second.id)
    assert result['against_point_id'] == first.id
    assert result['has_changes'] is True
    assert result['diff']['changed']['mode'] == {'old': 'one', 'new': 'two'}


def test_preview_and_restore_reconverge_with_pre_restore_point(app):
    from app.models import AuditLog, RestorePoint
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'mode': 'saved'})
    adapter.nested_auto_capture = True
    service.register_adapter('cron', adapter)
    saved = service.capture('cron', 'cron', 'manual', label='known good')
    adapter.state = {'mode': 'current'}

    dry_run = service.preview(saved.id)
    assert dry_run['can_restore'] is True
    assert dry_run['has_changes'] is True
    assert dry_run['diff']['changed']['mode'] == {
        'old': 'current', 'new': 'saved',
    }
    assert dry_run['outside_checkpoint'] == saved.get_coverage()

    result = service.restore(saved.id)
    assert result['success'] is True
    assert adapter.state == {'mode': 'saved'}
    assert adapter.restore_calls == 1

    before = RestorePoint.query.filter_by(trigger='pre_mutation').one()
    assert before.label == f'before restore {saved.id}'
    assert before.get_payload() == {'mode': 'current'}
    restore_audit = AuditLog.query.filter_by(
        action=AuditLog.ACTION_RESTORE_POINT_RESTORE,
    ).one()
    assert restore_audit.get_details()['pre_restore_point_id'] == before.id


def test_restore_refusal_is_typed_and_never_partially_applies(app):
    from app.models import RestorePoint
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'allow_ssh': True})
    service.register_adapter('firewall', adapter)
    saved = service.capture('firewall', 'firewall', 'manual')
    adapter.state = {'allow_ssh': False}
    adapter.refusals = ['Current SSH admission would be dropped.']

    with pytest.raises(service.RestorePointRefusedError) as caught:
        service.restore(saved.id)
    assert caught.value.status_code == 409
    assert caught.value.code == 'restore_point_refused'
    assert caught.value.details == {
        'refusals': ['Current SSH admission would be dropped.'],
    }
    assert adapter.restore_calls == 0
    assert RestorePoint.query.count() == 1


def test_restore_aborts_when_pre_restore_capture_fails(app, monkeypatch):
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'mode': 'saved'})
    service.register_adapter('cron', adapter)
    saved = service.capture('cron', 'cron', 'manual')
    adapter.state = {'mode': 'current'}
    monkeypatch.setattr(service, 'capture', lambda *_args, **_kwargs: None)

    with pytest.raises(service.RestorePointAdapterError) as caught:
        service.restore(saved.id)
    assert caught.value.status_code == 503
    assert adapter.restore_calls == 0


@pytest.mark.parametrize('payload_json', ['{broken', '[]'])
def test_corrupt_payload_is_typed_and_never_invokes_adapter(app, payload_json):
    from app import db
    from app.models import RestorePoint
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'mode': 'current'})
    service.register_adapter('cron', adapter)
    point = RestorePoint(
        scope_type='cron', scope_id='cron', trigger='manual',
        payload_hash='c' * 64, payload_json=payload_json,
        coverage_json='[]', keep=True,
    )
    db.session.add(point)
    db.session.commit()

    for operation in (service.diff, service.preview, service.restore):
        with pytest.raises(service.RestorePointCorruptError) as caught:
            operation(point.id)
        assert (caught.value.status_code, caught.value.code) == (
            409, 'restore_point_corrupt',
        )
    assert adapter.capture_calls == 0
    assert adapter.diff_calls == 0
    assert adapter.restore_calls == 0


def test_adapter_diff_errors_are_typed_in_diff_and_preview(app):
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'mode': 'saved'})
    service.register_adapter('cron', adapter)
    point = service.capture('cron', 'cron', 'manual')

    def broken_diff(_old, _new):
        raise RuntimeError('diff engine failed')

    adapter.diff = broken_diff
    for operation in (service.diff, service.preview):
        with pytest.raises(service.RestorePointAdapterError) as caught:
            operation(point.id)
        assert (caught.value.status_code, caught.value.code) == (
            503, 'restore_point_adapter_unavailable',
        )


def test_typed_not_found_and_adapter_unavailable_errors(app):
    from app.models import RestorePoint
    from app.services import restore_point_service as service

    with pytest.raises(service.RestorePointNotFoundError) as missing:
        service.preview('00000000-0000-0000-0000-000000000000')
    assert (missing.value.status_code, missing.value.code) == (
        404, 'restore_point_not_found',
    )

    point = RestorePoint(
        scope_type='cron', scope_id='cron', trigger='manual',
        payload_hash='a' * 64, payload_json='{}', coverage_json='[]', keep=True,
    )
    from app import db
    db.session.add(point)
    db.session.commit()
    with pytest.raises(service.RestorePointAdapterError) as unavailable:
        service.preview(point.id)
    assert (unavailable.value.status_code, unavailable.value.code) == (
        503, 'restore_point_adapter_unavailable',
    )


def test_restore_preserves_typed_adapter_errors(app):
    from app.exceptions import ConflictError
    from app.services import restore_point_service as service

    adapter = MemoryAdapter({'mode': 'saved'})
    service.register_adapter('cron', adapter)
    point = service.capture('cron', 'cron', 'manual')

    def conflict(*_args, **_kwargs):
        raise ConflictError('Surface is busy', code='surface_busy')

    adapter.restore = conflict
    with pytest.raises(ConflictError) as caught:
        service.restore(point.id)
    assert (caught.value.status_code, caught.value.code) == (409, 'surface_busy')


def test_prune_honors_expiry_keep_and_per_scope_cap(app):
    from app import db
    from app.models import RestorePoint
    from app.services import restore_point_service as service

    now = datetime.utcnow()
    for index in range(52):
        db.session.add(RestorePoint(
            scope_type='cron', scope_id='cron', trigger='pre_mutation',
            payload_hash=f'{index:064x}', payload_json=f'{{"n":{index}}}',
            coverage_json='[]', keep=False,
            created_at=now - timedelta(minutes=index),
            expires_at=now + timedelta(days=30),
        ))
    expired = RestorePoint(
        scope_type='env', scope_id='7', trigger='pre_mutation',
        payload_hash='e' * 64, payload_json='{}', coverage_json='[]', keep=False,
        created_at=now - timedelta(days=60),
        expires_at=now - timedelta(seconds=1),
    )
    kept = RestorePoint(
        scope_type='env', scope_id='7', trigger='manual',
        payload_hash='f' * 64, payload_json='{}', coverage_json='[]', keep=True,
        created_at=now - timedelta(days=60),
        expires_at=now - timedelta(days=30),
    )
    db.session.add_all([expired, kept])
    db.session.commit()

    result = service.prune(now=now)
    assert result == {
        'success': True,
        'backfilled': 0,
        'expired_deleted': 1,
        'cap_deleted': 2,
        'deleted': 3,
    }
    assert RestorePoint.query.filter_by(
        scope_type='cron', scope_id='cron', keep=False,
    ).count() == 50
    assert db.session.get(RestorePoint, kept.id) is not None
    assert db.session.get(RestorePoint, expired.id) is None


def test_auto_capture_suppression_is_nested_and_resets_after_exception(app):
    from app.models import RestorePoint
    from app.services import restore_point_service as service

    service.register_adapter('cron', MemoryAdapter({'jobs': 1}))
    with pytest.raises(RuntimeError, match='restore failed'):
        with service.suppress_auto_capture():
            assert service.auto_capture('cron', 'cron', 'update') is None
            with service.suppress_auto_capture():
                assert service.auto_capture('cron', 'cron', 'delete') is None
            raise RuntimeError('restore failed')

    point = service.auto_capture('cron', 'cron', 'update')
    assert point is not None
    assert point.label == 'before cron.update'
    assert RestorePoint.query.count() == 1


def test_restore_point_prune_job_is_registered_and_uses_setting(app, monkeypatch):
    from app.jobs import builtin_handlers
    from app.services import restore_point_service
    from app.services.settings_service import SettingsService

    entry = next(
        item for item in builtin_handlers._BUILTINS
        if item[0] == 'builtin.restore_point_retention'
    )
    assert entry[2:] == ('restore-point-retention', 3600, 180)

    monkeypatch.setattr(
        SettingsService, 'get',
        staticmethod(lambda key, default=None: '7' if key == 'restore_point_retention_days' else default),
    )
    seen = {}

    def fake_prune(**kwargs):
        seen.update(kwargs)
        return {'success': True, 'deleted': 2}

    monkeypatch.setattr(restore_point_service, 'prune', fake_prune)
    assert builtin_handlers.run_restore_point_retention() == {
        'success': True, 'deleted': 2,
    }
    assert seen == {'retention_days': 7}

    monkeypatch.setattr(
        restore_point_service, 'prune',
        lambda **_kwargs: {'success': False, 'error': 'database busy'},
    )
    with pytest.raises(RuntimeError, match='database busy'):
        builtin_handlers.run_restore_point_retention()
