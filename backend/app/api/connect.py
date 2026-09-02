"""Connect API — expose this panel's ServerKit Cloud connection state.

Pairing itself happens via `serverkit connect` on the host (see
app/services/connect_client.py); this read-only endpoint lets the Settings
UI render the connection state.
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from app.services import connect_client

connect_bp = Blueprint('connect', __name__)


@connect_bp.route('/status', methods=['GET'])
@jwt_required()
def get_status():
    """Current ServerKit Cloud connection state (unpaired/paired_offline/...)."""
    return jsonify(connect_client.status())
