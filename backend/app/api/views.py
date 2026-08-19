from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.services import saved_view_service

views_bp = Blueprint('views', __name__)


@views_bp.route('', methods=['GET'])
@jwt_required()
def list_views():
    """List the current user's saved views, optionally for one page."""
    page = request.args.get('page', '').strip()
    if not page:
        return jsonify({'error': 'The page query parameter is required'}), 400
    return jsonify({'views': saved_view_service.list_views(get_jwt_identity(), page)})


@views_bp.route('', methods=['POST'])
@jwt_required()
def create_view():
    body = request.get_json(silent=True) or {}
    view = saved_view_service.create_view(
        get_jwt_identity(),
        body.get('page'),
        body.get('name'),
        body.get('state'),
        is_default=bool(body.get('is_default')),
    )
    return jsonify(view), 201


@views_bp.route('/<int:view_id>', methods=['PUT'])
@jwt_required()
def update_view(view_id):
    body = request.get_json(silent=True) or {}
    view = saved_view_service.update_view(get_jwt_identity(), view_id, body)
    return jsonify(view)


@views_bp.route('/<int:view_id>', methods=['DELETE'])
@jwt_required()
def delete_view(view_id):
    saved_view_service.delete_view(get_jwt_identity(), view_id)
    return jsonify({'success': True})
