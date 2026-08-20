from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required

from app.services.migration_service import MigrationService
from app.middleware.rbac import require_admin_user

migrations_bp = Blueprint('migrations', __name__)


@migrations_bp.route('/status', methods=['GET'])
def get_migration_status():
    """Check if migrations are pending. No auth required (called before login)."""
    status = MigrationService.get_status()
    return jsonify(status), 200


@migrations_bp.route('/backup', methods=['POST'])
@jwt_required()
def create_backup():
    """Create a database backup before applying migrations. Admin only."""
    require_admin_user()

    result = MigrationService.create_backup(current_app)
    if result['success']:
        return jsonify(result), 200
    return jsonify(result), 500


@migrations_bp.route('/apply', methods=['POST'])
@jwt_required()
def apply_migrations():
    """Apply all pending migrations. Admin only."""
    require_admin_user()

    result = MigrationService.apply_migrations(current_app)
    if result['success']:
        return jsonify(result), 200
    return jsonify(result), 500


@migrations_bp.route('/history', methods=['GET'])
@jwt_required()
def get_migration_history():
    """Return all migration revisions. Admin only."""
    require_admin_user()

    history = MigrationService.get_migration_history(current_app)
    return jsonify({'revisions': history}), 200
