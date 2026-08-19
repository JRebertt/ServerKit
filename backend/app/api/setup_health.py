"""REST surface for Setup Health — "how set up is this panel".

Mounted at /api/v1/setup-health (registered in app/__init__.py). Admin-only.

Contract:
    GET / -> {'items': [<check>...], 'summary': {critical_open, recommended_open,
              ok, total, score}}

Each ``item`` is a doctor-style check dict (key/title/status/detail/
repairable/repair_ref) plus the setup extras ``severity``/``scope``/``why``/
``fix`` (fix is a deep-link ``{kind:'link', to}`` or a repair ``{kind:'repair',
ref}``). The doctor report carries the same items as its ``setup.*`` section, so
this endpoint and Monitoring → Doctor stay in lockstep.
"""
from flask import Blueprint, jsonify, request
from app.error_reporting import unexpected_response

from ..middleware.rbac import admin_required, auth_required, get_current_user
from ..services.setup_health_service import SetupHealthService
from ..services.setup_reconcile_service import (
    DNS_BACKFILL_JOB_KIND,
    URL_FIX_JOB_KIND,
    SetupReconcileService,
)

setup_health_bp = Blueprint('setup_health', __name__)


@setup_health_bp.route('', methods=['GET'])
@setup_health_bp.route('/', methods=['GET'])
@admin_required
def get_setup_health():
    """Evaluate the setup-health registry (panel scope) and return items +
    summary. Cheap — DB/settings probes only, no host calls."""
    try:
        return jsonify(SetupHealthService.evaluate(scope='panel'))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@setup_health_bp.route('/account', methods=['GET'])
@auth_required()
def get_account_security():
    """The requesting user's own setup-health items (scope 'user') — e.g. the
    'secure your account' nudge. Any authenticated user, about themselves."""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify(SetupHealthService.evaluate(scope='user', user=user))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


# --------------------------------------------------------------------------- #
# Snooze / dismiss (Phase 6). Panel items require admin; personal (user-scope)
# items may be snoozed by the owning user.
# --------------------------------------------------------------------------- #

def _snooze_guard(key):
    """Resolve the requesting user and enforce admin for panel-scoped items.
    Returns (user, None) when allowed, or (None, (json, status)) on error."""
    user = get_current_user()
    if not user:
        return None, (jsonify({'error': 'User not found'}), 404)
    scope = SetupHealthService._item_scope(key)
    if scope is None:
        return None, (jsonify({'error': f'Unknown setup item: {key}'}), 400)
    if scope == 'panel' and not user.is_admin:
        return None, (jsonify({'error': 'Admin access required'}), 403)
    return user, None


@setup_health_bp.route('/snooze', methods=['POST'])
@auth_required()
def snooze_item():
    """Snooze a setup item (mutes it; it still renders, just quietly)."""
    data = request.get_json(silent=True) or {}
    key = data.get('key')
    if not key:
        return jsonify({'error': "Body must carry an item 'key'."}), 400
    user, err = _snooze_guard(key)
    if err:
        return err
    try:
        return jsonify(SetupHealthService.snooze(key, days=data.get('days', 30), user=user))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@setup_health_bp.route('/snooze', methods=['DELETE'])
@auth_required()
def unsnooze_item():
    """Clear a snooze so the item is active again."""
    data = request.get_json(silent=True) or {}
    key = data.get('key') or request.args.get('key')
    if not key:
        return jsonify({'error': "An item 'key' is required."}), 400
    user, err = _snooze_guard(key)
    if err:
        return err
    try:
        return jsonify(SetupHealthService.unsnooze(key, user=user))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


# --------------------------------------------------------------------------- #
# Reconcile-on-connect (Phase 3) — preview is synchronous; apply enqueues the
# job so a large backfill/heal runs off the request thread.
# --------------------------------------------------------------------------- #

@setup_health_bp.route('/reconcile/dns/preview', methods=['POST'])
@admin_required
def dns_backfill_preview():
    """Dry-run: the managed hosts a DNS backfill would ensure records for."""
    try:
        return jsonify(SetupReconcileService.dns_backfill_preview())
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@setup_health_bp.route('/reconcile/dns/apply', methods=['POST'])
@admin_required
def dns_backfill_apply():
    """Enqueue the DNS backfill job (loops ensure_a_record, ownership-guarded)."""
    try:
        from app.jobs.service import JobService
        job = JobService.enqueue(DNS_BACKFILL_JOB_KIND, payload={}, max_attempts=1)
        return jsonify({'job_id': job.id}), 202
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@setup_health_bp.route('/reconcile/url-fix/preview', methods=['POST'])
@admin_required
def url_fix_preview():
    """Dry-run: WordPress sites whose siteurl/home still point at localhost or a
    stale IP, with the per-site swap they'd get."""
    try:
        return jsonify(SetupReconcileService.url_fix_preview())
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)


@setup_health_bp.route('/reconcile/url-fix/apply', methods=['POST'])
@admin_required
def url_fix_apply():
    """Enqueue the WordPress URL-fix job (loops change_site_url)."""
    try:
        from app.jobs.service import JobService
        job = JobService.enqueue(URL_FIX_JOB_KIND, payload={}, max_attempts=1)
        return jsonify({'job_id': job.id}), 202
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
