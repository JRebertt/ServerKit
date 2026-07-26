"""Backup target types contributed by plugins (plugins_sdk.backups).

An extension with something worth backing up had to hand-roll it: no policy, no
schedule, no retention, no restore, no place in the Protection panel. A
registered kind inherits all of that, because everything downstream of the four
target_type switches — the run lifecycle, retention, the API blueprint, the
panel — is already generic.

The switch this file cares most about is restore: an unrecognised type falls
through to core's application restore, which would unpack a plugin's archive
over an app directory.
"""

import pytest

from app import db
from app.models.backup_policy import BackupPolicy
from app.models.backup_run import BackupRun
from app.services import backup_kind_registry
from app.services.backup_policy_service import BackupPolicyError, BackupPolicyService


@pytest.fixture(autouse=True)
def _clean_registry():
    backup_kind_registry.clear()
    yield
    backup_kind_registry.clear()


def _resolve(policy):
    return {'name': 'Overworld', 'root_path': '/srv/worlds/1'}


def _execute(policy, target, kind):
    return '/var/backups/world-1.tar.gz', 4096, {'world': target['name']}


def _register(**over):
    kwargs = {'resolve': _resolve, 'execute': _execute}
    kwargs.update(over)
    return backup_kind_registry.register('minecraft.world', **kwargs)


def _policy(app, target_type='minecraft.world', target_id=1):
    policy = BackupPolicy(target_type=target_type, target_id=target_id, enabled=True)
    db.session.add(policy)
    db.session.commit()
    return policy


class TestRegistry:
    def test_registers_and_resolves(self):
        entry = _register()
        assert backup_kind_registry.get('minecraft.world') is entry
        assert backup_kind_registry.kinds() == ['minecraft.world']

    def test_core_kinds_cannot_be_hijacked(self, app):
        for target_type in backup_kind_registry.core_kinds():
            with pytest.raises(ValueError):
                backup_kind_registry.register(target_type, _resolve, _execute)

    def test_duplicate_registration_needs_replace(self, app):
        _register()
        with pytest.raises(ValueError):
            _register()
        _register(replace=True)

    def test_requires_resolve_and_execute(self, app):
        with pytest.raises(ValueError):
            backup_kind_registry.register('minecraft.world', 'nope', _execute)
        with pytest.raises(ValueError):
            backup_kind_registry.register('minecraft.world', _resolve, None)
        with pytest.raises(ValueError):
            backup_kind_registry.register('minecraft.world', _resolve, _execute,
                                          restore='nope')


class TestValidation:
    def test_a_registered_kind_is_accepted_by_the_gate(self, app):
        # The keystone: every policy route funnels through this validator, so
        # passing it is what opens the whole blueprint to a plugin kind.
        with pytest.raises(BackupPolicyError):
            BackupPolicyService.validate_target_type('minecraft.world')

        _register()
        BackupPolicyService.validate_target_type('minecraft.world')

    def test_unknown_types_are_still_rejected(self, app):
        _register()
        with pytest.raises(BackupPolicyError):
            BackupPolicyService.validate_target_type('not.registered')

    def test_core_types_still_pass(self, app):
        for target_type in backup_kind_registry.core_kinds():
            BackupPolicyService.validate_target_type(target_type)

    def test_a_policy_can_be_created_for_a_registered_kind(self, app):
        _register()
        policy = BackupPolicyService.get_or_create_policy('minecraft.world', 7)
        assert policy.id is not None
        assert policy.target_type == 'minecraft.world'


class TestResolve:
    def test_routes_to_the_plugin_and_forces_the_type(self, app):
        _register(resolve=lambda policy: {'name': 'Overworld',
                                          'target_type': 'application'})
        target = BackupPolicyService._resolve_target(_policy(app))
        # A kind claiming to be an application would be restored as one.
        assert target['target_type'] == 'minecraft.world'
        assert target['name'] == 'Overworld'

    def test_fills_in_the_keys_core_branches_read(self, app):
        _register(resolve=lambda policy: {})
        target = BackupPolicyService._resolve_target(_policy(app))
        assert target['name'] == 'minecraft.world:1'
        assert target['root_path'] is None and target['app'] is None

    def test_a_non_dict_is_refused(self, app):
        _register(resolve=lambda policy: 'nope')
        with pytest.raises(ValueError):
            BackupPolicyService._resolve_target(_policy(app))

    def test_an_unregistered_type_still_falls_through_to_core(self, app):
        # Core's fallthrough treats anything unknown as an application; that
        # behaviour must be untouched for types we don't own.
        policy = _policy(app, target_type='application', target_id=424242)
        with pytest.raises(BackupPolicyError):
            BackupPolicyService._resolve_target(policy)


class TestExecute:
    def test_routes_to_the_plugin(self, app):
        _register()
        policy = _policy(app)
        target = BackupPolicyService._resolve_target(policy)

        path, size, meta = BackupPolicyService._execute_backup(policy, target, 'full')

        assert path == '/var/backups/world-1.tar.gz'
        assert size == 4096
        assert meta['world'] == 'Overworld'

    def test_fills_in_the_metadata_retention_and_the_panel_read(self, app):
        _register()
        policy = _policy(app)
        target = BackupPolicyService._resolve_target(policy)

        _path, _size, meta = BackupPolicyService._execute_backup(policy, target, 'full')

        assert meta['engine'] == 'minecraft.world'
        assert meta['kind'] == 'full'
        assert meta['incremental'] is False

    def test_a_bad_return_shape_is_refused(self, app):
        _register(execute=lambda policy, target, kind: 'just-a-path')
        policy = _policy(app)
        target = BackupPolicyService._resolve_target(policy)
        with pytest.raises(ValueError):
            BackupPolicyService._execute_backup(policy, target, 'full')

    def test_no_storage_path_is_refused(self, app):
        _register(execute=lambda policy, target, kind: (None, 0, {}))
        policy = _policy(app)
        target = BackupPolicyService._resolve_target(policy)
        with pytest.raises(ValueError):
            BackupPolicyService._execute_backup(policy, target, 'full')


class TestRestore:
    def _successful_run(self, policy):
        run = BackupRun(policy_id=policy.id, kind='full', status='success',
                        storage_path='/var/backups/world-1.tar.gz')
        db.session.add(run)
        db.session.commit()
        return run

    def test_restore_routes_to_the_plugin(self, app):
        seen = {}

        def restore(policy, target, run, options):
            seen['run_id'] = run.id
            seen['scope'] = options.get('scope')

        _register(restore=restore)
        policy = _policy(app)
        run = self._successful_run(policy)

        BackupPolicyService._resolve_target(policy)
        backup_kind_registry.restore(
            policy, {'target_type': 'minecraft.world', 'name': 'Overworld'},
            run, {'scope': 'full'})

        assert seen == {'run_id': run.id, 'scope': 'full'}

    def test_a_kind_without_restore_is_refused_before_queueing(self, app):
        # Not merely "the job fails later": queueing it would run the safety
        # backup and take the policy lock for nothing.
        _register()
        policy = _policy(app)
        run = self._successful_run(policy)

        with pytest.raises(BackupPolicyError) as excinfo:
            BackupPolicyService.request_restore(policy, run.id, {})
        assert 'cannot be restored' in str(excinfo.value)

    def test_restore_never_falls_through_to_the_application_branch(self, app):
        # The hazard this whole branch exists to close: core's else-branch
        # unpacks the archive over an app directory.
        _register()
        with pytest.raises(ValueError):
            backup_kind_registry.restore(
                _policy(app), {'target_type': 'minecraft.world'}, None, {})

    def test_supports_restore_reports_the_truth(self, app):
        _register()
        assert backup_kind_registry.supports_restore('minecraft.world') is False
        _register(restore=lambda *a: None, replace=True)
        assert backup_kind_registry.supports_restore('minecraft.world') is True
        assert backup_kind_registry.supports_restore('not.registered') is False


def test_sdk_is_reachable_from_the_package(app):
    from app import plugins_sdk

    plugins_sdk.backups.register('minecraft.world', resolve=_resolve, execute=_execute)
    assert plugins_sdk.backups.kinds() == ['minecraft.world']
