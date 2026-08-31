from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.middleware.rbac import get_current_user
from .status_page_service import StatusPageService

status_pages_bp = Blueprint('status_pages', __name__)


# --- Public endpoints (no auth) ---

@status_pages_bp.route('/public/<slug>', methods=['GET'])
def get_public_page(slug):
    data = StatusPageService.get_public_page(slug)
    if not data:
        return jsonify({'error': 'Status page not found'}), 404
    return jsonify(data)


@status_pages_bp.route('/badge/<slug>', methods=['GET'])
def get_badge(slug):
    badge = StatusPageService.get_badge(slug)
    if not badge:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(badge)


# --- Admin endpoints ---

@status_pages_bp.route('/', methods=['GET'])
@jwt_required()
def list_pages():
    pages = StatusPageService.list_pages()
    return jsonify({'pages': [p.to_dict() for p in pages]})


@status_pages_bp.route('/<int:page_id>', methods=['GET'])
@jwt_required()
def get_page(page_id):
    page = StatusPageService.get_page(page_id)
    if not page:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(page.to_dict())


@status_pages_bp.route('/', methods=['POST'])
@jwt_required()
def create_page():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json()
    if not data or 'name' not in data or 'slug' not in data:
        return jsonify({'error': 'name and slug required'}), 400
    try:
        page = StatusPageService.create_page(data)
        return jsonify(page.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@status_pages_bp.route('/<int:page_id>', methods=['PUT'])
@jwt_required()
def update_page(page_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    page = StatusPageService.update_page(page_id, data)
    if not page:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(page.to_dict())


@status_pages_bp.route('/<int:page_id>', methods=['DELETE'])
@jwt_required()
def delete_page(page_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if not StatusPageService.delete_page(page_id):
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'message': 'Status page deleted'})


# --- Components ---

@status_pages_bp.route('/<int:page_id>/components', methods=['GET'])
@jwt_required()
def get_components(page_id):
    page = StatusPageService.get_page(page_id)
    if not page:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'components': [c.to_dict() for c in page.components.all()]})


@status_pages_bp.route('/<int:page_id>/components', methods=['POST'])
@jwt_required()
def create_component(page_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    try:
        comp = StatusPageService.create_component(page_id, data)
        return jsonify(comp.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@status_pages_bp.route('/components/<int:comp_id>', methods=['PUT'])
@jwt_required()
def update_component(comp_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    comp = StatusPageService.update_component(comp_id, data)
    if not comp:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(comp.to_dict())


@status_pages_bp.route('/components/<int:comp_id>', methods=['DELETE'])
@jwt_required()
def delete_component(comp_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if not StatusPageService.delete_component(comp_id):
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'message': 'Component deleted'})


@status_pages_bp.route('/components/<int:comp_id>/check', methods=['POST'])
@jwt_required()
def run_check(comp_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    hc = StatusPageService.run_check(comp_id)
    if not hc:
        return jsonify({'error': 'Component not found'}), 404
    return jsonify(hc.to_dict())


@status_pages_bp.route('/components/<int:comp_id>/history', methods=['GET'])
@jwt_required()
def get_history(comp_id):
    hours = request.args.get('hours', 24, type=int)
    checks = StatusPageService.get_check_history(comp_id, hours)
    return jsonify({'checks': [c.to_dict() for c in checks]})


# --- Incidents ---

@status_pages_bp.route('/<int:page_id>/incidents', methods=['GET'])
@jwt_required()
def list_incidents(page_id):
    page = StatusPageService.get_page(page_id)
    if not page:
        return jsonify({'error': 'Not found'}), 404
    incidents = page.incidents.limit(50).all()
    return jsonify({'incidents': [i.to_dict() for i in incidents]})


@status_pages_bp.route('/<int:page_id>/incidents', methods=['POST'])
@jwt_required()
def create_incident(page_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json()
    if not data or 'title' not in data:
        return jsonify({'error': 'title required'}), 400
    incident = StatusPageService.create_incident(page_id, data)
    return jsonify(incident.to_dict()), 201


@status_pages_bp.route('/incidents/<int:incident_id>', methods=['PUT'])
@jwt_required()
def update_incident(incident_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    incident = StatusPageService.update_incident(incident_id, data)
    if not incident:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(incident.to_dict())


@status_pages_bp.route('/incidents/<int:incident_id>', methods=['DELETE'])
@jwt_required()
def delete_incident(incident_id):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if not StatusPageService.delete_incident(incident_id):
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'message': 'Incident deleted'})
