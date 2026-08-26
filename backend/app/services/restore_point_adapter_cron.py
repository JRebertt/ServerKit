"""Restore-point adapter for the local CRON surface.

The crontab and ServerKit's JSON metadata are one logical state.  Capturing
only the rendered crontab would lose application attribution, tracking, and
alert preferences; capturing only metadata would lose hand-written lines.
"""

from copy import deepcopy

from app.services.cron_service import CronService


SCOPE_ID = 'cron'


def _validate_scope(scope_id, server_id):
    if str(scope_id) != SCOPE_ID:
        raise ValueError(f'Invalid CRON restore-point scope: {scope_id}')
    if server_id is not None:
        raise ValueError('Remote CRON restore points are not supported')


def capture(scope_id, server_id=None):
    """Return the complete readable crontab and its metadata sidecar."""
    _validate_scope(scope_id, server_id)

    if CronService.is_linux():
        crontab = CronService._read_crontab()
        if crontab is None:
            raise RuntimeError('Could not read the current crontab')
    else:
        # Non-Linux installs use the metadata-backed scheduler and therefore
        # have a real, readable empty system-crontab component.
        crontab = ''

    try:
        metadata = CronService._load_jobs_metadata_strict()
    except (OSError, ValueError) as exc:
        raise RuntimeError('CRON metadata is unreadable or malformed') from exc

    return {
        'crontab': crontab,
        'metadata': deepcopy(metadata),
    }


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('CRON restore payload must be an object')
    crontab = payload.get('crontab')
    metadata = payload.get('metadata')
    if not isinstance(crontab, str):
        raise ValueError('CRON restore payload requires readable crontab text')
    if not isinstance(metadata, dict) or not isinstance(metadata.get('jobs'), dict):
        raise ValueError('CRON restore payload requires jobs metadata')
    return crontab, deepcopy(metadata)


def restore(scope_id, payload, actor=None, server_id=None):
    """Restore CRON state, rolling the crontab back if metadata cannot persist.

    The normal service doors remain responsible for both writes.  A metadata
    failure after installing the target crontab is compensated with the full
    pre-image so callers never receive a false atomic-success result.
    """
    del actor  # Actor attribution belongs to the generic restore-point service.
    _validate_scope(scope_id, server_id)
    target_crontab, target_metadata = _validate_payload(payload)
    previous = capture(scope_id, server_id=server_id)

    if CronService.is_linux():
        failure = CronService._install_crontab(target_crontab)
        if failure:
            return failure

    try:
        CronService._save_jobs_metadata(target_metadata)
    except Exception as exc:  # noqa: BLE001 - compensate both state components
        rollback_errors = []
        if CronService.is_linux():
            rollback = CronService._install_crontab(previous['crontab'])
            if rollback:
                rollback_errors.append(
                    rollback.get('error') or 'failed to roll back crontab')
        try:
            CronService._save_jobs_metadata(previous['metadata'])
        except Exception as rollback_exc:  # noqa: BLE001 - report degraded rollback
            rollback_errors.append(
                f'failed to roll back metadata: {rollback_exc}')

        result = {
            'success': False,
            'error': f'Failed to restore CRON metadata: {exc}',
            'rolled_back': not rollback_errors,
        }
        if rollback_errors:
            result['rollback_error'] = '; '.join(rollback_errors)
        return result

    return {'success': True, 'message': 'CRON state restored'}
