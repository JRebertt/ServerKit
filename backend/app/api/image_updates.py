# Bucket: PER-APP (plan 29 #9). The registry-check trigger stays admin; the
# latest-check read is scoped to callers who can access the app (can_access_app).
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from app.models.application import Application
from app.services.image_update_service import ImageUpdateService
from app.services.resource_grant_service import ResourceGrantService
from app.middleware.rbac import get_current_user

image_updates_bp = Blueprint('image_updates', __name__)


def _admin():
    user = get_current_user()
    return user if user and user.is_admin else None


@image_updates_bp.route('/applications/<int:app_id>/check', methods=['POST'])
@jwt_required()
def check(app_id):
    """Run a registry-digest comparison for the application's image now."""
    if not _admin():
        return jsonify({'error': 'Admin access required'}), 403
    return jsonify(ImageUpdateService.check_application(app_id))


@image_updates_bp.route('/applications/<int:app_id>', methods=['GET'])
@jwt_required()
def latest(app_id):
    """Return the most recent image-update check for the application (or null).

    Scoped to the app's workspace visibility (plan 29 #9) — a foreign caller
    gets a sealed 404."""
    app = Application.query_active().filter_by(id=app_id).first()
    user = get_current_user()
    if app is None or not ResourceGrantService.can_access_app(user, app):
        return jsonify({'error': 'Not found'}), 404
    check_row = ImageUpdateService.latest_check(app_id)
    return jsonify(check_row.to_dict() if check_row else None)
