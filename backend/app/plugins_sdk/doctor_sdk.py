"""Plugin-facing SDK for health checks.

    from app.plugins_sdk import doctor

    def check_worlds():
        stale = [w for w in World.query.all() if w.backup_age_days > 7]
        if not stale:
            return {'key': 'backups', 'title': 'World backups',
                    'status': 'ok', 'detail': 'Every world backed up this week.'}
        return {'key': 'backups', 'title': 'World backups are stale',
                'status': 'warn',
                'detail': f'{len(stale)} world(s) have no backup in 7 days.',
                'repairable': True, 'repair_ref': {'worlds': [w.id for w in stale]}}

    def back_up(ref):
        for world_id in ref['worlds']:
            back_up_world(world_id)
        return {'success': True, 'message': 'Backed up.'}

    doctor.register('minecraft', check_worlds, repair=back_up)

An extension that can say it is unhealthy — on the page the operator already
opens to ask that question — is worth much more than one that can't. A
registered check appears in the sweep with core's, and the panel renders it
without a frontend change.

A check is ``{'key', 'title', 'status', 'detail'}`` where status is ``ok``,
``warn`` or ``fail``. Return one, or a list. Keys are namespaced for you.

Pass ``repair`` to get a Repair button wired to your handler; a check that
claims to be repairable without one is demoted rather than shown as a button
that does nothing. Your provider runs with a time budget (10s by default) and
its own error boundary, so a slow or broken check degrades to a warning instead
of taking the whole sweep with it.
"""

from app.services import doctor_check_registry


class DoctorSdk:
    """Stable health-check surface for plugins."""

    #: Statuses the panel can render.
    STATUSES = doctor_check_registry.VALID_STATUSES

    def register(self, namespace, provider, repair=None,
                 timeout=doctor_check_registry.DEFAULT_TIMEOUT, replace=False):
        """Register ``provider() -> check | [check, ...]`` under *namespace*.

        Namespace after your plugin (``minecraft``); core's own namespaces are
        reserved. *repair* is ``fn(ref) -> {'success': bool, ...}``.
        """
        return doctor_check_registry.register(
            namespace, provider, repair=repair, timeout=timeout, replace=replace)

    def namespaces(self):
        """Namespaces registered by plugins."""
        return doctor_check_registry.namespaces()


doctor = DoctorSdk()
