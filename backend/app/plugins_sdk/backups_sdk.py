"""Plugin-facing SDK for backups.

    from app.plugins_sdk import backups

    def resolve(policy):
        world = World.query.get(policy.target_id)
        if not world:
            raise ValueError('World not found')
        return {'name': world.name, 'root_path': world.directory, 'world': world}

    def execute(policy, target, kind):
        path = tar_up(target['root_path'])
        return path, os.path.getsize(path), {'world': target['name']}

    def restore(policy, target, run, options):
        untar(run.storage_path, target['root_path'])

    backups.register('minecraft.world', resolve=resolve, execute=execute,
                     restore=restore)

Registering a kind means never writing backup plumbing again: the policy row
and its cron schedule, run history, retention (count and age, aware of
incremental chains), offsite copy, verification, restore, and the Protection
panel — which is already generic over the target type — all come from the
panel. Create a policy the way core does::

    from app.services.backup_policy_service import BackupPolicyService
    BackupPolicyService.get_or_create_policy('minecraft.world', world.id)

Then the operator schedules, runs, prunes and restores it from the UI.

``restore`` is optional but strongly encouraged. Without it the panel refuses
the restore up front and says so, rather than queueing a job that fails — and
critically, rather than falling through to core's application restore, which
would unpack your archive over an app directory.
"""

from app.services import backup_kind_registry


class BackupsSdk:
    """Stable backup surface for plugins."""

    def register(self, target_type, resolve, execute, restore=None, replace=False):
        """Register a backup target type.

        ``resolve(policy) -> dict`` describes the live target (include
        ``name``, and ``root_path`` if it is a directory); raise if it is gone.
        ``execute(policy, target, kind) -> (storage_path, size_bytes, meta)``
        produces the artifact. ``restore(policy, target, run, options)`` puts
        one back.

        Namespace the type after your plugin (``minecraft.world``); core's bare
        words are reserved.
        """
        return backup_kind_registry.register(
            target_type, resolve=resolve, execute=execute, restore=restore,
            replace=replace)

    def kinds(self):
        """Backup target types registered by plugins."""
        return backup_kind_registry.kinds()


backups = BackupsSdk()
