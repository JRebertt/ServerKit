"""Cloudflare operations API — zone settings (SSL/TLS, Speed, Caching, Security)
and one-click hardening, on top of the existing Cloudflare DNS connection.

Zones are addressed by their ServerKit ``DNSZone`` id (same as the ``/dns`` API);
the service resolves the Cloudflare credential + zone id server-side. Reads are
available to any authenticated user; writes require admin. Every mutating call is
captured by the global audit fallback (method, route args, sanitized body).
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.middleware.rbac import require_admin_user
from .cloudflare_service import CloudflareService, CloudflareError

cloudflare_bp = Blueprint('cloudflare', __name__)


def _service_response(res):
    """Map a service result dict to JSON. A failed *provider* call (reached
    Cloudflare, got an error back) is a 502; resolution errors are raised as
    CloudflareError upstream and handled separately as 400s."""
    if not res.get('success'):
        return jsonify({'error': res.get('error', 'Cloudflare request failed')}), 502
    return jsonify(res)


# ── Zone settings ────────────────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/settings', methods=['GET'])
@jwt_required()
def get_zone_settings(zone_id):
    try:
        res = CloudflareService.get_settings(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/settings/apply-preset', methods=['POST'])
@jwt_required()
def apply_preset(zone_id):
    require_admin_user()
    try:
        res = CloudflareService.apply_recommended(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    # A preset is best-effort across many toggles; return 200 with the per-setting
    # report even when the plan gated some (the UI surfaces partial success).
    return jsonify(res)


@cloudflare_bp.route('/zones/<int:zone_id>/settings/<setting_id>', methods=['GET'])
@jwt_required()
def get_zone_setting(zone_id, setting_id):
    try:
        res = CloudflareService.get_setting(zone_id, setting_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/settings/<setting_id>', methods=['PATCH'])
@jwt_required()
def update_zone_setting(zone_id, setting_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    if 'value' not in data:
        return jsonify({'error': 'A "value" field is required'}), 400
    try:
        res = CloudflareService.update_setting(zone_id, setting_id, data['value'])
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── Cache ────────────────────────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/purge-cache', methods=['POST'])
@jwt_required()
def purge_cache(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.purge_cache(
            zone_id,
            everything=bool(data.get('purge_everything') or data.get('everything')),
            files=data.get('files'), hosts=data.get('hosts'),
            prefixes=data.get('prefixes'), tags=data.get('tags'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── WAF custom rules ─────────────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/waf/rules', methods=['GET'])
@jwt_required()
def list_waf_rules(zone_id):
    try:
        res = CloudflareService.list_waf_rules(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/waf/rules', methods=['POST'])
@jwt_required()
def add_waf_rule(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.add_waf_rule(
            zone_id,
            description=data.get('description'),
            expression=data.get('expression'),
            action=data.get('action'),
            enabled=data.get('enabled', True))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/waf/presets/<preset_key>', methods=['POST'])
@jwt_required()
def apply_waf_preset(zone_id, preset_key):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.apply_waf_preset(zone_id, preset_key, data.get('params') or {})
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/waf/rulesets/<ruleset_id>/rules/<rule_id>',
                     methods=['PATCH'])
@jwt_required()
def update_waf_rule(zone_id, ruleset_id, rule_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.update_waf_rule(zone_id, ruleset_id, rule_id, data)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/waf/rulesets/<ruleset_id>/rules/<rule_id>',
                     methods=['DELETE'])
@jwt_required()
def delete_waf_rule(zone_id, ruleset_id, rule_id):
    require_admin_user()
    try:
        res = CloudflareService.delete_waf_rule(zone_id, ruleset_id, rule_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── Workers (edge hosting) ───────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/workers', methods=['GET'])
@jwt_required()
def list_workers(zone_id):
    try:
        res = CloudflareService.list_workers(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/workers', methods=['POST'])
@jwt_required()
def deploy_worker(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.deploy_worker(
            zone_id,
            name=data.get('name'),
            code=data.get('code'),
            compatibility_date=data.get('compatibility_date'),
            route_pattern=data.get('route_pattern'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/workers/routes', methods=['POST'])
@jwt_required()
def add_worker_route(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.add_worker_route(zone_id, data.get('pattern'), data.get('script'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/workers/routes/<route_id>', methods=['DELETE'])
@jwt_required()
def delete_worker_route(zone_id, route_id):
    require_admin_user()
    try:
        res = CloudflareService.delete_worker_route(zone_id, route_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# Note: this dynamic <name> route is registered last so it can't shadow the more
# specific /workers/routes paths above.
@cloudflare_bp.route('/zones/<int:zone_id>/workers/<name>', methods=['DELETE'])
@jwt_required()
def delete_worker(zone_id, name):
    require_admin_user()
    try:
        res = CloudflareService.delete_worker(zone_id, name)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── Tunnels (cloudflared) ────────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/tunnels', methods=['GET'])
@jwt_required()
def list_tunnels(zone_id):
    try:
        res = CloudflareService.list_tunnels(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/tunnels', methods=['POST'])
@jwt_required()
def create_tunnel(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.create_tunnel(zone_id, data.get('name'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/tunnels/<tunnel_id>/install', methods=['GET'])
@jwt_required()
def tunnel_install(zone_id, tunnel_id):
    require_admin_user()
    try:
        res = CloudflareService.get_tunnel_install(zone_id, tunnel_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/tunnels/<tunnel_id>/hostnames', methods=['GET'])
@jwt_required()
def tunnel_hostnames(zone_id, tunnel_id):
    try:
        res = CloudflareService.get_tunnel_hostnames(zone_id, tunnel_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/tunnels/<tunnel_id>/hostnames', methods=['POST'])
@jwt_required()
def add_tunnel_hostname(zone_id, tunnel_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.add_tunnel_hostname(
            zone_id, tunnel_id, data.get('hostname'), data.get('service'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/tunnels/<tunnel_id>/hostnames', methods=['DELETE'])
@jwt_required()
def remove_tunnel_hostname(zone_id, tunnel_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.remove_tunnel_hostname(zone_id, tunnel_id, data.get('hostname'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/tunnels/<tunnel_id>', methods=['DELETE'])
@jwt_required()
def delete_tunnel(zone_id, tunnel_id):
    require_admin_user()
    try:
        res = CloudflareService.delete_tunnel(zone_id, tunnel_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── Developer platform: R2 / KV / D1 ─────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/storage', methods=['GET'])
@jwt_required()
def list_storage(zone_id):
    try:
        res = CloudflareService.list_storage(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/storage/r2', methods=['POST'])
@jwt_required()
def create_r2_bucket(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.create_r2_bucket(zone_id, data.get('name'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/storage/r2/<bucket>', methods=['DELETE'])
@jwt_required()
def delete_r2_bucket(zone_id, bucket):
    require_admin_user()
    try:
        res = CloudflareService.delete_r2_bucket(zone_id, bucket)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/storage/kv', methods=['POST'])
@jwt_required()
def create_kv_namespace(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.create_kv_namespace(zone_id, data.get('title'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/storage/kv/<namespace_id>', methods=['DELETE'])
@jwt_required()
def delete_kv_namespace(zone_id, namespace_id):
    require_admin_user()
    try:
        res = CloudflareService.delete_kv_namespace(zone_id, namespace_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/storage/d1', methods=['POST'])
@jwt_required()
def create_d1_database(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.create_d1_database(zone_id, data.get('name'))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/storage/d1/<database_id>', methods=['DELETE'])
@jwt_required()
def delete_d1_database(zone_id, database_id):
    require_admin_user()
    try:
        res = CloudflareService.delete_d1_database(zone_id, database_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── DNSSEC ────────────────────────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/dnssec', methods=['GET'])
@jwt_required()
def get_dnssec(zone_id):
    try:
        res = CloudflareService.get_dnssec(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/dnssec', methods=['PATCH'])
@jwt_required()
def set_dnssec(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    if 'enabled' not in data:
        return jsonify({'error': 'An "enabled" boolean is required'}), 400
    try:
        res = CloudflareService.set_dnssec(zone_id, bool(data['enabled']))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── Origin CA certificates ─────────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/origin-certificates', methods=['GET'])
@jwt_required()
def list_origin_certificates(zone_id):
    try:
        res = CloudflareService.list_origin_certificates(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/origin-certificates', methods=['POST'])
@jwt_required()
def issue_origin_certificate(zone_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.issue_origin_certificate(
            zone_id,
            hostnames=data.get('hostnames'),
            validity_days=int(data.get('validity_days', 5475)),
            install=bool(data.get('install', True)))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    except (TypeError, ValueError):
        return jsonify({'error': 'validity_days must be a number'}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/origin-certificates/<certificate_id>',
                     methods=['DELETE'])
@jwt_required()
def revoke_origin_certificate(zone_id, certificate_id):
    require_admin_user()
    try:
        res = CloudflareService.revoke_origin_certificate(zone_id, certificate_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── Redirect + Transform rules ─────────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/rules/<slug>', methods=['GET'])
@jwt_required()
def list_rules(zone_id, slug):
    try:
        res = CloudflareService.list_rules(zone_id, slug)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/rules/<slug>', methods=['POST'])
@jwt_required()
def add_rule(zone_id, slug):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.add_rule(
            zone_id, slug,
            description=data.get('description'),
            expression=data.get('expression'),
            action=data.get('action'),
            action_parameters=data.get('action_parameters'),
            enabled=data.get('enabled', True))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/rules/<slug>/presets/<preset_key>', methods=['POST'])
@jwt_required()
def apply_rule_preset(zone_id, slug, preset_key):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.apply_rule_preset(zone_id, slug, preset_key, data.get('params') or {})
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/rules/<slug>/rulesets/<ruleset_id>/rules/<rule_id>',
                     methods=['PATCH'])
@jwt_required()
def update_rule(zone_id, slug, ruleset_id, rule_id):
    require_admin_user()
    data = request.get_json(silent=True) or {}
    try:
        res = CloudflareService.update_rule(zone_id, slug, ruleset_id, rule_id, data)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/rules/<slug>/rulesets/<ruleset_id>/rules/<rule_id>',
                     methods=['DELETE'])
@jwt_required()
def delete_rule(zone_id, slug, ruleset_id, rule_id):
    require_admin_user()
    try:
        res = CloudflareService.delete_rule(zone_id, slug, ruleset_id, rule_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)


# ── Activity + scope diagnostics ───────────────────────────────────────────────

@cloudflare_bp.route('/zones/<int:zone_id>/activity', methods=['GET'])
@jwt_required()
def list_activity(zone_id):
    try:
        res = CloudflareService.list_activity(
            zone_id,
            product=request.args.get('product'),
            result=request.args.get('result'),
            limit=min(int(request.args.get('limit', 100) or 100), 500))
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be a number'}), 400
    return _service_response(res)


@cloudflare_bp.route('/zones/<int:zone_id>/scope-check', methods=['GET'])
@jwt_required()
def scope_check(zone_id):
    try:
        res = CloudflareService.scope_check(zone_id)
    except CloudflareError as e:
        return jsonify({'error': str(e)}), 400
    return _service_response(res)
