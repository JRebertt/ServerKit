"""Self-scoped guided walkthrough progress API."""

from flask import Blueprint, jsonify, request

from app.middleware.rbac import get_current_user, require_role, viewer_required
from app.services.walkthrough_service import (
    WalkthroughService,
    WalkthroughStateError,
)


walkthroughs_bp = Blueprint('walkthroughs', __name__)


@walkthroughs_bp.route('/state', methods=['GET'])
@viewer_required
def get_walkthrough_state():
    user = get_current_user()
    return jsonify({'state': WalkthroughService.get_state(user.id)}), 200


@walkthroughs_bp.route('/state', methods=['PUT'])
@require_role('admin', 'developer', 'viewer')
def update_walkthrough_state():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        state = WalkthroughService.save_state(user.id, data.get('state', data))
    except WalkthroughStateError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'success': True, 'state': state}), 200
