"""Linked-panel API — manage this panel's link to a master ServerKit panel."""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.middleware.rbac import developer_required
from app.services.linked_panel_service import LinkedPanelService

linked_panel_bp = Blueprint('linked_panel', __name__)


@linked_panel_bp.route('', methods=['GET'])
@jwt_required()
def get_status():
    """Current link status (linked/connected/last_error)."""
    return jsonify(LinkedPanelService.get_status())


@linked_panel_bp.route('', methods=['POST'])
@developer_required
def link():
    """Link this panel to a master ServerKit panel.

    Body: {"master_url": "https://panel-a", "registration_token": "sk_reg_…",
           "name": "optional display name"}
    The registration token comes from the master's Servers page (Add Server
    / regenerate-token) — the same token the Go agent consumes.
    """
    data = request.get_json(silent=True) or {}
    result = LinkedPanelService.link(
        master_url=data.get('master_url'),
        registration_token=data.get('registration_token'),
        name=data.get('name'),
    )
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)


@linked_panel_bp.route('', methods=['DELETE'])
@developer_required
def unlink():
    """Stop the embedded agent and forget the master credentials."""
    return jsonify(LinkedPanelService.unlink())
