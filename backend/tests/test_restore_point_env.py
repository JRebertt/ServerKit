"""Plan 81 M2: environment restore-point adapter and mutation doors."""

import json

import pytest

from app.models import EnvironmentVariableHistory, RestorePoint
from app.services import restore_point_adapter_env as env_adapter
from app.utils.sensitive_data_filter import MASK


@pytest.fixture
def registered_env_adapter():
    from app.services import restore_point_service

    existing = dict(restore_point_service.ADAPTERS)
    restore_point_service.register_adapter('env', env_adapter)
    try:
        yield restore_point_service
    finally:
        restore_point_service.clear_adapters()
        restore_point_service.ADAPTERS.update(existing)


def _make_app():
    from app import db
    from factories import make_application, make_user

    user = make_user(
        db,
        username='restore-env-owner',
        email='restore-env-owner@example.test',
        role='admin',
    )
    application = make_application(
        db,
        name='restore-env-app',
        user_id=user.id,
        status='running',
    )
    return application, user


def test_capture_masks_flags_sensitive_names_and_keeps_reference_metadata(
        app, registered_env_adapter):
    from app.services.env_service import EnvService

    application, user = _make_app()
    EnvService.set_env_var(
        application.id, 'PUBLIC_URL', 'https://example.test', user_id=user.id,
    )
    EnvService.set_env_var(
        application.id, 'API_TOKEN', 'raw-token', is_secret=False,
        user_id=user.id,
    )
    EnvService.set_env_var(
        application.id, 'INTERNAL', 'raw-secret', is_secret=True,
        user_id=user.id,
    )
    reference = {'kind': 'secret', 'secret': 'stripe_prod'}
    EnvService.set_env_reference(
        application.id, 'STRIPE_KEY', reference, user.id,
        target_service='web', description='Stripe credential',
    )

    point = registered_env_adapter.capture(
        'env', application.id, 'manual', label='mask-proof', actor=user.id,
    )
    payload = json.loads(point.payload_json)
    assert payload['env']['PUBLIC_URL']['value'] == 'https://example.test'
    assert payload['env']['API_TOKEN']['value'] == MASK
    assert payload['env']['INTERNAL']['value'] == MASK
    assert payload['env']['STRIPE_KEY'] == {
        'value': MASK,
        'is_secret': True,
        'description': 'Stripe credential',
        'target_service': 'web',
        'value_from': reference,
    }
    serialized = json.dumps(payload)
    assert 'raw-token' not in serialized
    assert 'raw-secret' not in serialized


def test_every_env_mutation_door_auto_captures_once(
        app, monkeypatch, registered_env_adapter):
    from app.services import restore_point_service
    from app.services.env_service import EnvService

    application, user = _make_app()
    captures = []

    def fake_capture(scope_type, scope_id, trigger, **kwargs):
        captures.append((scope_type, scope_id, trigger, kwargs.get('label')))
        return object()

    monkeypatch.setattr(restore_point_service, 'capture', fake_capture)

    first, _, _ = EnvService.set_env_var(
        application.id, 'FIRST', '1', user_id=user.id,
    )
    EnvService.update_env_var(
        application.id, 'FIRST', value='2', user_id=user.id,
    )
    EnvService.set_env_reference(
        application.id, 'REF', {'kind': 'secret', 'secret': 'one'}, user.id,
    )
    EnvService.delete_env_var(application.id, 'REF', user.id)
    EnvService.delete_env_var_by_id(first.id, user.id)
    EnvService.bulk_set_env_vars(
        application.id, {'SECOND': '2', 'THIRD': '3'}, user.id,
    )
    EnvService.clear_all(application.id, user.id)

    assert [item[3] for item in captures] == [
        'before env.set_env_var',
        'before env.update_env_var',
        'before env.set_env_reference',
        'before env.delete_env_var',
        'before env.delete_env_var_by_id',
        'before env.bulk_set_env_vars',
        'before env.clear_all',
    ]
    assert all(item[:3] == (
        'env', str(application.id), 'pre_mutation',
    ) for item in captures)


def test_bulk_and_clear_history_rows_share_operation_batch(
        app, registered_env_adapter):
    from app.services.env_service import EnvService

    application, user = _make_app()
    EnvService.bulk_set_env_vars(
        application.id, {'ONE': '1', 'TWO': '2'}, user.id,
    )

    created = EnvironmentVariableHistory.query.filter_by(
        application_id=application.id,
        action='created',
    ).order_by(EnvironmentVariableHistory.id).all()
    assert len(created) == 2
    assert created[0].batch_id
    assert {row.batch_id for row in created} == {created[0].batch_id}

    EnvService.clear_all(application.id, user.id)
    deleted = EnvironmentVariableHistory.query.filter_by(
        application_id=application.id,
        action='deleted',
    ).order_by(EnvironmentVariableHistory.id).all()
    assert len(deleted) == 2
    assert deleted[0].batch_id
    assert {row.batch_id for row in deleted} == {deleted[0].batch_id}
    assert deleted[0].batch_id != created[0].batch_id
    assert all(row.to_dict()['batch_id'] == row.batch_id for row in deleted)


def test_restore_round_trip_reconverges_and_groups_history(
        app, registered_env_adapter):
    from app.services.env_service import EnvService

    application, user = _make_app()
    EnvService.set_env_var(
        application.id, 'FEATURE_FLAG', 'on', user_id=user.id,
    )
    point = registered_env_adapter.capture(
        'env', application.id, 'manual', label='known-good', actor=user.id,
    )

    EnvService.set_env_var(
        application.id, 'FEATURE_FLAG', 'off', user_id=user.id,
    )
    EnvService.set_env_var(
        application.id, 'TEMPORARY', 'remove-me', user_id=user.id,
    )
    points_before_restore = RestorePoint.query.filter_by(
        scope_type='env', scope_id=str(application.id),
    ).count()

    result = registered_env_adapter.restore(point.id, actor=user)

    assert result['success'] is True
    assert EnvService.get_env_var(application.id, 'FEATURE_FLAG').value == 'on'
    assert EnvService.get_env_var(application.id, 'TEMPORARY') is None
    assert RestorePoint.query.filter_by(
        scope_type='env', scope_id=str(application.id),
    ).count() == points_before_restore + 1

    replay_rows = EnvironmentVariableHistory.query.filter_by(
        application_id=application.id,
        batch_id=result['batch_id'],
    ).all()
    assert {row.key for row in replay_rows} == {'FEATURE_FLAG', 'TEMPORARY'}
    assert {row.batch_id for row in replay_rows} == {result['batch_id']}


def test_restore_keeps_live_masked_values_and_replays_references(
        app, registered_env_adapter):
    from app.services.env_service import EnvService

    application, user = _make_app()
    EnvService.set_env_var(
        application.id, 'API_TOKEN', 'old-token', is_secret=True,
        user_id=user.id,
    )
    original_reference = {'kind': 'secret', 'secret': 'stripe_old'}
    EnvService.set_env_reference(
        application.id, 'STRIPE_KEY', original_reference, user.id,
    )
    point = registered_env_adapter.capture(
        'env', application.id, 'manual', label='with-secrets', actor=user.id,
    )

    EnvService.set_env_var(
        application.id, 'API_TOKEN', 'rotated-token', is_secret=True,
        user_id=user.id,
    )
    EnvService.set_env_reference(
        application.id, 'STRIPE_KEY',
        {'kind': 'secret', 'secret': 'stripe_new'}, user.id,
    )
    EnvService.set_env_reference(
        application.id, 'LIVE_ONLY_REF',
        {'kind': 'secret', 'secret': 'keep_me'}, user.id,
    )

    result = registered_env_adapter.restore(point.id, actor=user)

    token = EnvService.get_env_var(application.id, 'API_TOKEN')
    stripe = EnvService.get_env_var(application.id, 'STRIPE_KEY')
    live_only = EnvService.get_env_var(application.id, 'LIVE_ONLY_REF')
    assert token.value == 'rotated-token'
    assert stripe.get_reference() == original_reference
    assert live_only.get_reference() == {
        'kind': 'secret', 'secret': 'keep_me',
    }
    assert 'API_TOKEN' in result['skipped_secrets']
    assert 'LIVE_ONLY_REF' in result['preserved_references']
    assert MASK not in {token.value, stripe.value, live_only.value}


def test_env_diff_is_secret_safe_and_key_granular():
    old = {'env': {
        'TOKEN': {'value': MASK, 'is_secret': True},
        'FLAG': {'value': 'on', 'is_secret': False},
    }}
    new = {'env': {
        'TOKEN': {'value': MASK, 'is_secret': True},
        'FLAG': {'value': 'off', 'is_secret': False},
        'ADDED': {'value': 'yes', 'is_secret': False},
    }}

    result = env_adapter.diff(old, new)
    assert set(result['added']) == {'ADDED'}
    assert set(result['changed']) == {'FLAG'}
    assert result['removed'] == {}
    assert 'TOKEN' not in result['changed']
