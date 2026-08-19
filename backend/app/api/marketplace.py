"""Marketplace API — the extension registry surface.

The legacy DB-seeded ``Extension``/``ExtensionInstall`` catalog was retired
(#51): nothing ever populated it on a real panel, so it fed Browse an empty
third lane that was redundant with the three real sources — the builtin
folder scan (``/plugins/builtin``), the remote registry (below), and live
``InstalledPlugin`` state. This blueprint now serves only the registry.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from app.services.audit_service import AuditService
from app.models.audit_log import AuditLog
from app.middleware.rbac import get_current_user
from app.error_reporting import unexpected_response

marketplace_bp = Blueprint('marketplace', __name__)


@marketplace_bp.route('/registry', methods=['GET'])
@jwt_required()
def list_registry():
    """Return the remote-registry extensions (with live install state), for the
    Browse merge. Read-only; offline-tolerant (falls back to a bundled index).

    Bundled entries (builtins listed for the public catalog) are excluded by
    default to avoid duplicating the builtin cards; pass
    ``?include_bundled=true`` for the complete catalog."""
    from app.services import registry_service
    include_bundled = request.args.get('include_bundled', '').lower() in ('1', 'true', 'yes')
    return jsonify({
        'extensions': registry_service.list_catalog(include_bundled=include_bundled),
        'source': registry_service.registry_source_label(),
    })


@marketplace_bp.route('/registry/<slug>/install', methods=['POST'])
@jwt_required()
def install_registry(slug):
    """Install a registry extension by slug. Checksum-verified (the entry's
    sha256, when present, must match before extraction)."""
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    # Trust gate: an unreviewed community extension, or any entry with no
    # pinned checksum (possible even for first_party), installs only after an
    # explicit risk acknowledgment — the Marketplace shows a confirmation
    # dialog and resends with acknowledge_risk: true. first_party / reviewed
    # entries install as-is. `reason` tells the UI which case it is so the
    # dialog copy stays accurate.
    from app.services import registry_service
    entry = registry_service.get_entry(slug)
    # Hidden means not installable: unreviewed entries only exist in
    # development contexts (see registry_service._show_unreviewed).
    if entry is not None and entry.get('trust') == 'unreviewed' \
            and not registry_service._show_unreviewed():
        return jsonify({'error': 'Extension not found in the registry'}), 404
    body = request.get_json(silent=True) or {}
    trust = (entry or {}).get('trust', 'unreviewed')
    acknowledged = body.get('acknowledge_risk') is True
    # Consent gate (shared with the update path — audits M2/M3):
    # unreviewed (dev-stage) > unverified (no checksum) > signature gate
    # (untrusted key, or unsigned first-party = possible downgrade).
    reason, message = registry_service.consent_gate(entry, acknowledged)
    if reason:
        return jsonify({
            'error': f'{message} Resend with acknowledge_risk: true to proceed.',
            'trust': trust,
            'reason': reason,
            'requires_acknowledgment': True,
        }), 409

    from app.services.plugin_service import install_registry_extension
    try:
        plugin = install_registry_extension(slug, user_id=user.id)
        details = {'name': plugin.name, 'version': plugin.version, 'source': 'registry'}
        if acknowledged:
            details['trust'] = trust
            details['acknowledged_risk'] = True
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user.id,
            target_type='plugin',
            target_id=plugin.id,
            details=details,
        )
        # Opt-in anonymous install ping (default OFF; #17). Best-effort — never
        # affects the install result.
        try:
            registry_service.record_install(plugin.slug, plugin.version)
        except Exception:
            pass
        return jsonify(plugin.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
