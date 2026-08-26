"""Restore-point adapter for an application's local environment variables.

The payload deliberately stores metadata and references, but never plaintext
for a secret-flagged or sensitive-looking key.  Restore replays through
``EnvService`` so encryption, history, and future policy remain centralized.
"""

from app.models import Application, EnvironmentVariable
from app.services.configuration_service import ConfigurationService
from app.utils.sensitive_data_filter import MASK


coverage = (
    'Only environment variables set directly on this application are '
    'captured. Shared variable groups and their attachment order are outside '
    'this checkpoint.',
)


def _application_id(scope_id):
    try:
        return int(scope_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid application environment scope: {scope_id}') from exc


def _require_application(scope_id):
    application_id = _application_id(scope_id)
    application = Application.query_active().filter_by(id=application_id).first()
    if application is None:
        raise ValueError(f'Application {application_id} not found')
    return application_id


def _masked_value(env_var):
    """Avoid decrypting rows that ConfigurationService will redact anyway."""
    placeholder = ConfigurationService.mask_env_value(
        env_var.key, '', bool(env_var.is_secret),
    )
    if placeholder == MASK:
        return MASK
    return ConfigurationService.mask_env_value(
        env_var.key, env_var.value, bool(env_var.is_secret),
    )


def capture(scope_id, server_id=None):
    """Capture a deterministic, secret-safe per-key environment mapping."""
    del server_id  # Environment variables are scoped by application today.
    application_id = _require_application(scope_id)
    rows = EnvironmentVariable.query.filter_by(
        application_id=application_id,
    ).order_by(EnvironmentVariable.key).all()

    env = {}
    for row in rows:
        env[row.key] = {
            'value': _masked_value(row),
            'is_secret': bool(row.is_secret),
            'description': row.description,
            'target_service': row.target_service,
            # References contain source identity, never the resolved secret.
            'value_from': row.get_reference(),
        }
    return {'env': env}


def _env_mapping(payload):
    if not isinstance(payload, dict):
        raise ValueError('Environment restore payload must be an object')
    env = payload.get('env', {})
    if not isinstance(env, dict):
        raise ValueError('Environment restore payload.env must be an object')
    return env


def diff(old_payload, new_payload):
    """Return the shared added/removed/changed vocabulary at key granularity."""
    old = _env_mapping(old_payload)
    new = _env_mapping(new_payload)
    old_keys = set(old)
    new_keys = set(new)
    return {
        'added': {key: new[key] for key in sorted(new_keys - old_keys)},
        'removed': {key: old[key] for key in sorted(old_keys - new_keys)},
        'changed': {
            key: {'old': old[key], 'new': new[key]}
            for key in sorted(old_keys & new_keys)
            if old[key] != new[key]
        },
    }


def _validate_target(target):
    """Validate the full target before the first replay write."""
    for key, item in target.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            raise ValueError('Environment restore entries must be keyed objects')
        valid, error = _env_service().validate_key(key)
        if not valid:
            raise ValueError(f'{key}: {error}')
        reference = item.get('value_from')
        if reference is not None and not isinstance(reference, dict):
            raise ValueError(f'{key}: value_from must be an object or null')


def _env_service():
    # Lazy to avoid coupling the normal environment-service import path back
    # through the adapter registry during application startup.
    from app.services.env_service import EnvService

    return EnvService


def _actor_id(actor):
    return getattr(actor, 'id', actor)


def restore(scope_id, payload, actor=None, server_id=None):
    """Re-converge local env state without clobbering masked live material."""
    del server_id
    application_id = _require_application(scope_id)
    target = _env_mapping(payload)
    _validate_target(target)

    from app.services.env_service import _new_batch_id
    from app.services.restore_point_service import suppress_auto_capture

    EnvService = _env_service()
    actor_id = _actor_id(actor)
    batch_id = _new_batch_id()
    current = {
        row.key: row for row in EnvironmentVariable.query.filter_by(
            application_id=application_id,
        ).all()
    }

    restored = []
    removed = []
    skipped_secrets = []
    preserved_references = []

    # The generic restore service already suppresses nested auto-captures.
    # Keep the adapter safe when exercised directly as well.
    with suppress_auto_capture():
        for key in sorted(target):
            item = target[key]
            reference = item.get('value_from')
            value = item.get('value', '')

            if reference is not None:
                _, _, error = EnvService.set_env_reference(
                    application_id,
                    key,
                    reference,
                    user_id=actor_id,
                    target_service=item.get('target_service'),
                    description=item.get('description'),
                    batch_id=batch_id,
                )
                if error:
                    raise ValueError(f'{key}: {error}')
                restored.append(key)
                continue

            if value == MASK:
                # There is no recoverable value in the checkpoint.  If a live
                # row exists, leave its literal/reference and metadata intact;
                # if it is missing, do not manufacture a row containing MASK.
                skipped_secrets.append(key)
                if current.get(key) and current[key].get_reference():
                    preserved_references.append(key)
                continue

            _, _, error = EnvService.set_env_var(
                application_id,
                key,
                value,
                is_secret=bool(item.get('is_secret', False)),
                description=item.get('description'),
                user_id=actor_id,
                target_service=item.get('target_service'),
                batch_id=batch_id,
            )
            if error:
                raise ValueError(f'{key}: {error}')
            # ``set_env_var`` deliberately treats description=None as
            # "leave unchanged" for its longstanding callers. A checkpoint's
            # explicit null means clear it, so finish that metadata convergence
            # through the partial-update service door.
            if (
                item.get('description') is None
                and current.get(key)
                and current[key].description is not None
            ):
                _, error = EnvService.update_env_var(
                    application_id,
                    key,
                    description=None,
                    user_id=actor_id,
                    batch_id=batch_id,
                )
                if error:
                    raise ValueError(f'{key}: {error}')
            restored.append(key)

        for key in sorted(set(current) - set(target)):
            row = current[key]
            reference = row.get_reference()
            if reference is not None:
                preserved_references.append(key)
                continue
            if ConfigurationService.mask_env_value(
                key, '', bool(row.is_secret),
            ) == MASK:
                skipped_secrets.append(key)
                continue
            success, error = EnvService.delete_env_var(
                application_id, key, user_id=actor_id, batch_id=batch_id,
            )
            if not success:
                raise ValueError(f'{key}: {error}')
            removed.append(key)

    return {
        'success': True,
        'application_id': application_id,
        'batch_id': batch_id,
        'restored': restored,
        'removed': removed,
        'skipped_secrets': sorted(set(skipped_secrets)),
        'preserved_references': sorted(set(preserved_references)),
    }
