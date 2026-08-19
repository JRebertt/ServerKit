"""Curated DB config tuner API.

Target addressing (consistent with the databases API, which addresses Docker
databases as ``/databases/docker/<container>/...`` by container *name*):

- ``<target>`` is normally the Docker **container name**, with the engine
  passed as ``?engine=mysql|mariadb|postgresql`` (query param on GET, body
  field on POST).
- As a convenience, an all-digits ``<target>`` is treated as a **managed
  database id** (``managed_databases`` row with ``host_kind='docker'``); its
  ``container_ref``/``engine``/admin credentials are used automatically.

MySQL auth follows the existing convention: the password travels in the
``X-DB-Password`` header (never in the URL), user via ``user`` param/field.

All endpoints are admin-only; ``apply`` requires an explicit settings payload
— suggestions are never auto-applied.
"""
from flask import Blueprint, request, jsonify

from app.middleware.rbac import admin_required
from app.services.db_config_tuner_service import DbConfigTunerService

db_tuner_bp = Blueprint('db_tuner', __name__)


def _build_target(target, data):
    """Resolve <target> + request context into the service target dict.
    → (target_dict, None) or (None, (json, status))."""
    data = data or {}
    password = request.headers.get('X-DB-Password') or data.get('password')
    user = data.get('user') or request.args.get('user')

    if target.isdigit():
        from app.services.managed_database_service import ManagedDatabaseService
        managed = ManagedDatabaseService.get(int(target))
        if not managed:
            return None, (jsonify({'error': 'Managed database not found'}), 404)
        if managed.host_kind != 'docker' or not managed.container_ref:
            return None, (jsonify({'error': 'Managed database is not a Docker container target'}), 400)
        engine = DbConfigTunerService.normalize_engine(managed.engine)
        if not engine:
            return None, (jsonify({'error': f'Unsupported engine: {managed.engine}'}), 400)
        if not password and managed.admin_secret_encrypted:
            from app.utils.crypto import decrypt_secret_safe
            password = decrypt_secret_safe(managed.admin_secret_encrypted)
        return {
            'container': managed.container_ref,
            'engine': engine,
            'user': user or managed.admin_username,
            'password': password,
        }, None

    engine = DbConfigTunerService.normalize_engine(
        data.get('engine') or request.args.get('engine'))
    if not engine:
        return None, (jsonify({'error': 'engine is required (mysql|mariadb|postgresql)'}), 400)
    return {'container': target, 'engine': engine, 'user': user, 'password': password}, None


@db_tuner_bp.route('/<target>/inspect', methods=['GET'])
@admin_required
def inspect_target(target):
    """Current vs RAM-aware suggested values for the curated settings."""
    resolved, err = _build_target(target, None)
    if err:
        return err
    dedicated = str(request.args.get('dedicated', '')).lower() in ('1', 'true', 'yes')
    return jsonify(DbConfigTunerService.inspect(resolved, is_dedicated=dedicated)), 200


@db_tuner_bp.route('/<target>/apply', methods=['POST'])
@admin_required
def apply_target(target):
    """Apply an explicit operator-chosen settings dict (restarts the engine)."""
    data = request.get_json() or {}
    if not data.get('settings'):
        return jsonify({'error': 'settings is required'}), 400
    resolved, err = _build_target(target, data)
    if err:
        return err
    return jsonify(DbConfigTunerService.apply(resolved, data['settings'])), 200


@db_tuner_bp.route('/<target>/rollback', methods=['POST'])
@admin_required
def rollback_target(target):
    """Restore the pre-apply config and restart the engine."""
    data = request.get_json() or {}
    resolved, err = _build_target(target, data)
    if err:
        return err
    return jsonify(DbConfigTunerService.rollback(resolved)), 200
