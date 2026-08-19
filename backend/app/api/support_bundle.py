"""Support bundle API: build and download a scrubbed diagnostic zip.

Registration (app/__init__.py):
    from app.api.support_bundle import support_bundle_bp
    app.register_blueprint(support_bundle_bp, url_prefix='/api/v1/support-bundle')
"""
import os
from datetime import datetime

from flask import Blueprint, jsonify, send_file

from app.middleware.rbac import admin_required
from app.services import support_bundle_service
from app.error_reporting import unexpected_response

support_bundle_bp = Blueprint('support_bundle', __name__)


@support_bundle_bp.route('', methods=['POST'])
@admin_required
def build_support_bundle():
    """Build a diagnostic support bundle and return it as a zip download."""
    try:
        path = support_bundle_service.build()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)

    if not os.path.isfile(path):
        return jsonify({'error': 'Support bundle was not created'}), 500

    filename = f"serverkit-support-{datetime.utcnow().strftime('%Y-%m-%d')}.zip"
    return send_file(
        path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )
