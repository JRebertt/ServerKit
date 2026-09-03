"""The Storage Hub on the panel side.

ServerKit Cloud holds one set of object-storage credentials and hands each
server its own prefix in the bucket. This module is the whole panel half of
that: four command handlers, and the snapshot the panel sends back on the
`storage` stream.

What it deliberately does not do is re-implement anything. The destination
lands in `storage.json` through `StorageProviderService.save_config`, which
every upload, list and verify path in the panel already reads — including
`path_prefix`, which those paths have always honoured. Cloud is therefore
just another way of filling in the form on Backups > Storage, and a backup
run does not know or care which one was used.

While a destination is managed by Cloud, `managed_by_cloud` is set in
storage.json and the local form is read-only: two places writing the same
config would race, and the operator should be told where it is coming from
rather than watching their edit disappear.
"""
import logging
from datetime import datetime, timezone

from app.services.connect_commands import handler
from app.services.storage_provider_service import StorageProviderService

logger = logging.getLogger(__name__)

# ServerKit Cloud sends an S3 shape whatever the provider is (B2 through its
# S3-compatible endpoint, R2, Wasabi and the rest), so the panel keeps one
# client and writes one provider block.
PANEL_PROVIDER = 's3'


def _iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


# ==================== commands ====================


@handler('storage.assign')
def assign(args: dict, app=None) -> dict:
    """Write the destination Cloud sent, then prove it works before saying so.

    The reply is what flips the assignment to `ok` in Cloud, so it must be the
    result of a real `test_connection` and not the fact that a file was
    written.
    """
    if args.get('error') == 'connection_gone':
        return {'ok': False, 'summary': 'ServerKit Cloud no longer has that storage connection, '
                                        'so nothing was changed here.'}
    missing = [k for k in ('bucket', 'key_id', 'secret', 'prefix') if not args.get(k)]
    if missing:
        return {'ok': False, 'summary': f'The destination was incomplete: no {", ".join(missing)}.'}

    previous = StorageProviderService.get_config()
    # Merge, never replace: auto_upload, keep_local_copy and everything else
    # the operator set on this panel is theirs and stays.
    config = dict(previous)
    config.update({
        'provider': PANEL_PROVIDER,
        'managed_by_cloud': True,
        'managed_prefix': args['prefix'],
        's3': {
            'bucket': args['bucket'],
            'region': args.get('region') or 'auto',
            'endpoint_url': args.get('endpoint') or '',
            'access_key': args['key_id'],
            'secret_key': args['secret'],
            'path_prefix': args['prefix'].rstrip('/'),
        },
    })

    test = StorageProviderService.test_connection(config)
    if not test.get('success'):
        # Nothing is saved: a destination the panel cannot reach would stop
        # the next offsite copy without anybody being told why.
        return {'ok': False,
                'summary': test.get('error') or 'The panel could not reach that destination.'}

    StorageProviderService.save_config(config)
    logger.info('Connect storage: destination set by ServerKit Cloud (%s/%s)',
                args['bucket'], args['prefix'])
    return {'ok': True,
            'summary': f'Writing offsite backups to {args["bucket"]}/{args["prefix"]}',
            'output': _previous_note(previous)}


def _previous_note(previous: dict) -> str | None:
    """What the destination used to be, for the command's stored output. The
    operator can see what Cloud replaced without us keeping a second copy of
    the old credentials anywhere."""
    if not previous or previous.get('provider') in (None, 'local'):
        return 'Previous destination: local only.'
    block = previous.get(previous.get('provider'), {}) or {}
    bucket = block.get('bucket')
    return f'Previous destination: {previous.get("provider")}:{bucket or "unnamed bucket"}.'


@handler('storage.unassign')
def unassign(args: dict, app=None) -> dict:
    """Hand the destination back to this panel.

    Backups keep running; the offsite copy stops. Nothing in the bucket is
    touched — deleting a customer's objects is not something a command from
    Cloud is allowed to do.
    """
    config = StorageProviderService.get_config()
    if not config.get('managed_by_cloud'):
        return {'ok': True, 'summary': 'This panel\'s storage was not managed by Cloud; '
                                       'nothing was changed.'}
    # The credential came from Cloud and the operator never typed it, so it
    # goes with the assignment. Their own settings stay.
    config = {k: v for k, v in config.items() if k != PANEL_PROVIDER}
    config.update({'provider': 'local', 'managed_by_cloud': False, 'managed_prefix': None})
    StorageProviderService.save_config(config)
    logger.info('Connect storage: destination handed back to this panel')
    return {'ok': True, 'summary': 'Backups are local-only again. Nothing in the bucket was '
                                   'deleted; set a destination here to start copying offsite.'}


@handler('storage.test')
def test(args: dict, app=None) -> dict:
    result = StorageProviderService.test_connection()
    if result.get('success'):
        return {'ok': True, 'summary': result.get('message') or 'Destination reachable.'}
    return {'ok': False, 'summary': result.get('error') or 'The destination could not be reached.'}


@handler('storage.report')
def report(args: dict, app=None) -> dict:
    """Send a snapshot now. The frame itself goes out through the relay client;
    here we only prove we can build one."""
    snapshot = build_status(app)
    if snapshot is None:
        return {'ok': False, 'summary': 'This panel has no storage status to report yet.'}
    client = _relay_client()
    if client is None or not client.publish_storage(snapshot):
        return {'ok': False, 'summary': 'The panel is not connected to the relay right now, '
                                        'so the snapshot could not be sent. It goes out on the '
                                        'next connection.'}
    return {'ok': True, 'summary': 'Storage status sent.'}


def _relay_client():
    try:
        from app.services import connect_client
        return connect_client.get_client()
    except Exception:
        return None


# ==================== the storage stream ====================


def build_status(app=None) -> dict | None:
    """One snapshot of where this panel's backups go and how they went.

    Every field is something the panel actually knows. Anything it cannot
    read is left out rather than sent as a zero: "0 bytes stored" and "we
    could not list the bucket" are different answers.
    """
    config = StorageProviderService.get_config()
    provider = config.get('provider') or 'local'
    block = config.get(provider, {}) if provider != 'local' else {}
    prefix = config.get('managed_prefix') or block.get('path_prefix') or None
    bucket = block.get('bucket')

    payload = {
        'type': 'status',
        'destination': f'{bucket}/{prefix}' if bucket else None,
        'prefix': f'{prefix.rstrip("/")}/' if prefix else None,
        'managed_by_cloud': bool(config.get('managed_by_cloud')),
    }

    if provider != 'local':
        try:
            stats = StorageProviderService.get_remote_stats()
            payload['remote_bytes'] = stats.get('remote_size')
            payload['remote_objects'] = stats.get('remote_count')
        except Exception as exc:
            payload['error'] = f'Could not list the destination: {exc}'

    policies, last_run, last_ok = _policy_rows(app)
    if policies is not None:
        payload['policies'] = policies
        payload['last_backup_at'] = _iso(last_run)
        payload['last_backup_ok'] = last_ok
    return payload


def _policy_rows(app=None):
    """(rows, newest run time, whether it succeeded) from the panel's own
    backup policies. Returns (None, None, None) when there is no app context
    to read them in — the snapshot still carries the destination."""
    try:
        from app.models.backup_policy import BackupPolicy
    except Exception:
        return None, None, None

    def collect():
        rows = []
        newest = None
        newest_ok = None
        for p in BackupPolicy.query.all():
            rows.append({
                'name': f'{p.target_type}:{p.target_id}',
                'last_run_at': _iso(p.last_run_at),
                'status': p.last_status,
                'size': int(p.last_size) if p.last_size is not None else None,
                'remote_copy': bool(p.remote_copy),
            })
            if p.last_run_at is not None and (newest is None or p.last_run_at > newest):
                newest = p.last_run_at
                newest_ok = (p.last_status == 'success')
        return rows, newest, newest_ok

    try:
        if app is not None:
            with app.app_context():
                return collect()
        return collect()
    except Exception as exc:
        logger.debug('Connect storage: could not read backup policies (%s)', exc)
        return None, None, None


def status_frame(stream_id: str, snapshot: dict) -> dict:
    return {'s': stream_id, 't': 'open', 'k': 'storage', 'p': snapshot}


def is_managed_by_cloud() -> bool:
    """True while ServerKit Cloud owns this panel's backup destination. The
    local Backups > Storage form reads this and goes read-only."""
    try:
        return bool(StorageProviderService.get_config().get('managed_by_cloud'))
    except Exception:
        return False
