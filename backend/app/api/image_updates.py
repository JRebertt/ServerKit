# Bucket: PER-APP (plan 29 #9). The registry-check trigger stays admin; the
# latest-check read is scoped to callers who can access the app (can_access_app).
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.user import User
from app.models.application import Application
from app.services.image_update_service import ImageUpdateService
from app.services.resource_grant_service import ResourceGrantService

image_updates_bp = Blueprint('image_updates', __name__)


def _admin():
    user = User.query.get(get_jwt_identity())
    return user if user and user.is_admin else None


@image_updates_bp.route('/applications/<int:app_id>/check', methods=['POST'])
@jwt_required()
def check(app_id):
    """Run a registry-digest comparison for the application's image now."""
    if not _admin():
        return jsonify({'error': 'Admin access required'}), 403
    result = ImageUpdateService.check_application(app_id)
    if not result['success']:
        code = 404 if 'not found' in result['error'].lower() else 400
        return jsonify({'error': result['error']}), code
    return jsonify(result['check'])


@image_updates_bp.route('/applications/<int:app_id>', methods=['GET'])
@jwt_required()
def latest(app_id):
    """Return the most recent image-update check for the application (or null).

    Scoped to the app's workspace visibility (plan 29 #9) — a foreign caller
    gets a sealed 404."""
    app = Application.query_active().filter_by(id=app_id).first()
    user = User.query.get(get_jwt_identity())
    if app is None or not ResourceGrantService.can_access_app(user, app):
        return jsonify({'error': 'Not found'}), 404
    check_row = ImageUpdateService.latest_check(app_id)
    return jsonify(check_row.to_dict() if check_row else None)
