"""Domain-registrar connections — the portfolio + expiry surface.

Connections are admin-managed (like DNS providers). Reading the portfolio is
available to any authenticated user so the Domains page and Connections cards
can show "what we own and when it lapses".
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services.registrar_service import RegistrarService
from app.middleware.rbac import get_current_user

registrars_bp = Blueprint('registrars', __name__)


@registrars_bp.route('/connections', methods=['GET'])
@jwt_required()
def list_connections():
    conns = RegistrarService.list_connections()
    return jsonify({'connections': [c.to_dict() for c in conns]})


@registrars_bp.route('/connections', methods=['POST'])
@jwt_required()
def add_connection():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    try:
        conn = RegistrarService.add_connection(data, user.id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    # Validate the credentials immediately; drop the row if they don't work so
    # we never persist a dead connection.
    test = RegistrarService.test_connection(conn)
    if not test.get('success'):
        RegistrarService.delete_connection(conn.id)
        return jsonify({'error': test.get('error', 'Connection test failed')}), 400
    return jsonify({'connection': conn.to_dict(), 'test': test}), 201


@registrars_bp.route('/connections/<int:cid>', methods=['DELETE'])
@jwt_required()
def delete_connection(cid):
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if not RegistrarService.delete_connection(cid):
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'message': 'Registrar disconnected'})


@registrars_bp.route('/connections/<int:cid>/test', methods=['POST'])
@jwt_required()
def test_connection(cid):
    conn = RegistrarService.get_connection(cid)
    if not conn:
        return jsonify({'error': 'Not found'}), 404
    result = RegistrarService.test_connection(conn)
    return jsonify(result), 200 if result.get('success') else 400


@registrars_bp.route('/domains', methods=['GET'])
@jwt_required()
def list_domains():
    """Aggregated domain portfolio across all connected registrars."""
    return jsonify({'domains': RegistrarService.list_all_domains()})


@registrars_bp.route('/sync', methods=['POST'])
@jwt_required()
def sync():
    """Force-refresh the portfolio (and stamp last_synced_at)."""
    return jsonify({'domains': RegistrarService.sync_now()})
