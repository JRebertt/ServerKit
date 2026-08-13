# Bucket: PER-APP (plan 29 #9). Reads are scoped to callers who can access the
# app (can_access_app); mutations + install stay admin-only.
"""Per-application WAF (ModSecurity v3 + OWASP CRS) API.

Routes are mounted at ``/api/v1/waf``. Reads require access to the target app;
mutations and install require an admin user (mirrors ``app/api/dns_zones.py``).
Service ``ValueError``s map to HTTP 400.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.models.application import Application
from app.services.waf_service import WafService
from app.services.resource_grant_service import ResourceGrantService

waf_bp = Blueprint('waf', __name__)


def get_current_user():
    from flask_jwt_extended import get_jwt_identity
    from app.models.user import User
    return User.query.get(get_jwt_identity())


def _require_admin():
    """Return None if the caller is an admin, else a (response, status) tuple."""
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    return None


def _get_application_or_404(app_id):
    """Resolve the app and enforce read access (plan 29 #9): owner / admin / grant /
    workspace member. A caller who can't access it gets the same 404 as a missing
    app (sealed-from-open, no existence leak)."""
    application = Application.query_active().filter_by(id=app_id).first()
    if not application:
        return None, (jsonify({'error': 'Application not found'}), 404)
    if not ResourceGrantService.can_access_app(get_current_user(), application):
        return None, (jsonify({'error': 'Application not found'}), 404)
    return application, None


@waf_bp.route('/applications/<int:app_id>/policy', methods=['GET'])
@jwt_required()
def get_policy(app_id):
    _, err = _get_application_or_404(app_id)
    if err:
        return err
    policy = WafService.get_or_create_policy(app_id)
    return jsonify(policy.to_dict())


@waf_bp.route('/applications/<int:app_id>/policy', methods=['PUT'])
@jwt_required()
def update_policy(app_id):
    admin_err = _require_admin()
    if admin_err:
        return admin_err
    _, err = _get_application_or_404(app_id)
    if err:
        return err

    data = request.get_json() or {}
    try:
        policy = WafService.set_policy(
            app_id,
            mode=data.get('mode'),
            paranoia_level=data.get('paranoia_level'),
            anomaly_threshold=data.get('anomaly_threshold'),
            disabled_rule_ids=data.get('disabled_rule_ids'),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    # Best-effort enforcement: never fail the policy write because nginx /
    # ModSecurity isn't present on the host.
    try:
        apply_result = WafService.apply(app_id)
    except Exception as e:  # pragma: no cover - defensive
        apply_result = {'success': False, 'error': str(e)}

    response = policy.to_dict()
    response['apply'] = apply_result
    return jsonify(response)


@waf_bp.route('/applications/<int:app_id>/apply', methods=['POST'])
@jwt_required()
def apply_policy(app_id):
    admin_err = _require_admin()
    if admin_err:
        return admin_err
    _, err = _get_application_or_404(app_id)
    if err:
        return err
    result = WafService.apply(app_id)
    status = 200 if result.get('success') else 400
    return jsonify(result), status


@waf_bp.route('/applications/<int:app_id>/events', methods=['GET'])
@jwt_required()
def get_events(app_id):
    _, err = _get_application_or_404(app_id)
    if err:
        return err
    try:
        limit = int(request.args.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(500, limit))
    events = WafService.events(app_id, limit=limit)
    return jsonify({'events': events, 'count': len(events)})


@waf_bp.route('/status', methods=['GET'])
@jwt_required()
def status():
    return jsonify({'installed': WafService.modsecurity_installed()})


@waf_bp.route('/install', methods=['POST'])
@jwt_required()
def install():
    admin_err = _require_admin()
    if admin_err:
        return admin_err
    result = WafService.install_modsecurity()
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code
