# Bucket: PER-APP (plan 29 #9). Per-app scan/security routes gate on the shared
# app-access seam; host-level firewall/fail2ban/malware surfaces stay admin-only.
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.middleware.rbac import admin_required
from app.services.security_service import SecurityService
from app.services.image_scanner_service import ImageScannerService
from app.services.malware_scan_service import MalwareScanService
from app.services.yara_scan_service import YaraScanService
from app.error_reporting import unexpected_response

security_bp = Blueprint('security', __name__)

# Register the security.malware_scan job handler at boot (this module is
# imported by create_app); registration is idempotent and also re-asserted on
# every enqueue.
MalwareScanService.register_jobs()
ImageScannerService.register_jobs()
SecurityService.register_jobs()


# ==========================================
# STATUS & CONFIG
# ==========================================
@security_bp.route('/status', methods=['GET'])
@jwt_required()
def get_security_status():
    """Get overall security status summary."""
    summary = SecurityService.get_security_summary()
    return jsonify(summary), 200


@security_bp.route('/config', methods=['GET'])
@admin_required
def get_config():
    """Get security configuration."""
    config = SecurityService.get_config()
    return jsonify(config), 200


@security_bp.route('/config', methods=['PUT'])
@admin_required
def update_config():
    """Update security configuration."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    current_config = SecurityService.get_config()

    # Update nested config sections
    for key in ['clamav', 'file_integrity', 'suspicious_activity', 'notifications']:
        if key in data:
            current_config[key] = {**current_config.get(key, {}), **data[key]}

    result = SecurityService.save_config(current_config)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# CLAMAV
# ==========================================
@security_bp.route('/clamav/status', methods=['GET'])
@jwt_required()
def get_clamav_status():
    """Get ClamAV installation and service status."""
    status = SecurityService.get_clamav_status()
    return jsonify(status), 200


@security_bp.route('/clamav/install', methods=['POST'])
@admin_required
def install_clamav():
    """Install ClamAV packages."""
    result = SecurityService.install_clamav()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/clamav/update', methods=['POST'])
@admin_required
def update_definitions():
    """Update ClamAV virus definitions."""
    result = SecurityService.update_definitions()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/clamav/start', methods=['POST'])
@admin_required
def start_clamav():
    """Start the ClamAV daemon (one-click posture fix)."""
    result = SecurityService.start_clamav()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/scan/file', methods=['POST'])
@admin_required
def scan_file():
    """Scan a single file for malware."""
    data = request.get_json()
    if not data or 'path' not in data:
        return jsonify({'error': 'File path required'}), 400

    result = SecurityService.scan_file(data['path'])
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/scan/directory', methods=['POST'])
@admin_required
def scan_directory():
    """Start a directory scan (runs in background)."""
    data = request.get_json()
    if not data or 'path' not in data:
        return jsonify({'error': 'Directory path required'}), 400

    recursive = data.get('recursive', True)
    result = SecurityService.scan_directory(data['path'], recursive)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/scan/app/<int:app_id>', methods=['POST'])
@admin_required
def scan_app(app_id):
    """Enqueue a job-backed malware scan (YARA + ClamAV) of an app's docroot."""
    try:
        job = MalwareScanService.enqueue_scan(app_id=app_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if 'not found' in str(e) else 400
    return jsonify({'job_id': job.id, 'kind': job.kind,
                    'path': (job.get_payload() or {}).get('path')}), 202


@security_bp.route('/scan/job', methods=['POST'])
@admin_required
def scan_path_job():
    """Enqueue a job-backed malware scan of an arbitrary path."""
    data = request.get_json()
    if not data or not data.get('path'):
        return jsonify({'error': 'Path required'}), 400
    try:
        job = MalwareScanService.enqueue_scan(path=data['path'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'job_id': job.id, 'kind': job.kind, 'path': data['path']}), 202


@security_bp.route('/scan/status', methods=['GET'])
@jwt_required()
def get_scan_status():
    """Get current scan status."""
    status = SecurityService.get_scan_status()
    return jsonify(status), 200


@security_bp.route('/scan/cancel', methods=['POST'])
@admin_required
def cancel_scan():
    """Cancel running scan."""
    result = SecurityService.cancel_scan()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/scan/history', methods=['GET'])
@jwt_required()
def get_scan_history():
    """Get scan history."""
    limit = request.args.get('limit', 50, type=int)
    result = SecurityService.get_scan_history(limit)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# QUARANTINE
# ==========================================
@security_bp.route('/quarantine', methods=['GET'])
@admin_required
def get_quarantined_files():
    """List quarantined files."""
    result = SecurityService.get_quarantined_files()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/quarantine', methods=['POST'])
@admin_required
def quarantine_file():
    """Move a file to quarantine."""
    data = request.get_json()
    if not data or 'path' not in data:
        return jsonify({'error': 'File path required'}), 400

    result = SecurityService.quarantine_file(data['path'])
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/quarantine/<filename>', methods=['DELETE'])
@admin_required
def delete_quarantined_file(filename):
    """Permanently delete a quarantined file."""
    result = SecurityService.delete_quarantined_file(filename)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/quarantine/<filename>/restore', methods=['POST'])
@admin_required
def restore_quarantined_file(filename):
    """Restore a quarantined file to its recorded original location."""
    result = SecurityService.restore_quarantined_file(filename)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# YARA RULES (web-shell pass)
# ==========================================
@security_bp.route('/yara/rules', methods=['GET'])
@admin_required
def list_yara_rules():
    """List builtin (curated) and custom YARA rule files."""
    return jsonify(YaraScanService.list_rules()), 200


@security_bp.route('/yara/rules', methods=['POST'])
@admin_required
def upload_yara_rule():
    """Upload a custom .yar rule file (size-capped; requires real yara to run)."""
    data = request.get_json()
    if not data or not data.get('filename'):
        return jsonify({'error': 'filename required'}), 400
    result = YaraScanService.save_custom_rule(data['filename'], data.get('content', ''))
    if not result['success']:
        return jsonify({'error': result['error']}), 400
    return jsonify(result), 200


@security_bp.route('/yara/rules/<filename>', methods=['DELETE'])
@admin_required
def delete_yara_rule(filename):
    """Delete a custom .yar rule file."""
    result = YaraScanService.delete_custom_rule(filename)
    if not result['success']:
        return jsonify({'error': result['error']}), 400
    return jsonify(result), 200


# ==========================================
# FILE INTEGRITY
# ==========================================
@security_bp.route('/integrity/initialize', methods=['POST'])
@admin_required
def initialize_integrity():
    """Create baseline for file integrity monitoring."""
    data = request.get_json() or {}
    paths = data.get('paths')
    result = SecurityService.initialize_integrity_database(paths)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/integrity/check', methods=['GET'])
@admin_required
def check_integrity():
    """Check files against integrity database."""
    result = SecurityService.check_file_integrity()
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# SUSPICIOUS ACTIVITY
# ==========================================
@security_bp.route('/failed-logins', methods=['GET'])
@admin_required
def check_failed_logins():
    """Check for failed login attempts."""
    hours = request.args.get('hours', 24, type=int)
    result = SecurityService.check_failed_logins(hours)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# EVENTS & ALERTS
# ==========================================
@security_bp.route('/events', methods=['GET'])
@jwt_required()
def get_security_events():
    """Get recent security events/alerts."""
    limit = request.args.get('limit', 100, type=int)
    result = SecurityService.get_security_events(limit)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# QUICK SCAN PRESETS
# ==========================================
@security_bp.route('/scan/quick', methods=['POST'])
@admin_required
def quick_scan():
    """Run a quick scan on common web directories."""
    config = SecurityService.get_config()
    scan_paths = config.get('clamav', {}).get('scan_paths', ['/var/www', '/home'])

    # Scan each path
    results = []
    for path in scan_paths:
        result = SecurityService.scan_directory(path, recursive=True)
        results.append({'path': path, 'result': result})

    return jsonify({
        'success': True,
        'message': f'Started scans for {len(scan_paths)} directories',
        'scans': results
    }), 200


@security_bp.route('/scan/full', methods=['POST'])
@admin_required
def full_scan():
    """Run a full system scan."""
    result = SecurityService.scan_directory('/', recursive=True)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# FAIL2BAN
# ==========================================
@security_bp.route('/fail2ban/status', methods=['GET'])
@admin_required
def get_fail2ban_status():
    """Get Fail2ban status."""
    status = SecurityService.get_fail2ban_status()
    return jsonify(status), 200


@security_bp.route('/fail2ban/install', methods=['POST'])
@admin_required
def install_fail2ban():
    """Install Fail2ban."""
    result = SecurityService.install_fail2ban()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/fail2ban/jails/<jail>', methods=['GET'])
@admin_required
def get_jail_status(jail):
    """Get status of a specific jail."""
    result = SecurityService.get_fail2ban_jail_status(jail)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/fail2ban/bans', methods=['GET'])
@admin_required
def get_all_bans():
    """Get all banned IPs across all jails."""
    result = SecurityService.get_all_fail2ban_bans()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/fail2ban/unban', methods=['POST'])
@admin_required
def unban_ip():
    """Unban an IP address."""
    data = request.get_json()
    if not data or 'ip' not in data:
        return jsonify({'error': 'IP address required'}), 400

    jail = data.get('jail')
    result = SecurityService.unban_ip(data['ip'], jail)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/fail2ban/ban', methods=['POST'])
@admin_required
def ban_ip():
    """Manually ban an IP address."""
    data = request.get_json()
    if not data or 'ip' not in data:
        return jsonify({'error': 'IP address required'}), 400

    jail = data.get('jail', 'sshd')
    result = SecurityService.ban_ip(data['ip'], jail)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# SSH KEYS
# ==========================================
@security_bp.route('/ssh-keys', methods=['GET'])
@admin_required
def get_ssh_keys():
    """Get SSH authorized keys."""
    user = request.args.get('user', 'root')
    result = SecurityService.get_ssh_keys(user)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ssh-keys', methods=['POST'])
@admin_required
def add_ssh_key():
    """Add an SSH public key."""
    data = request.get_json()
    if not data or 'key' not in data:
        return jsonify({'error': 'SSH key required'}), 400

    user = data.get('user', 'root')
    result = SecurityService.add_ssh_key(data['key'], user)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ssh-keys/<int:key_id>', methods=['DELETE'])
@admin_required
def remove_ssh_key(key_id):
    """Remove an SSH key."""
    user = request.args.get('user', 'root')
    result = SecurityService.remove_ssh_key(key_id, user)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# IP ALLOWLIST/BLOCKLIST
# ==========================================
@security_bp.route('/ip-lists', methods=['GET'])
@admin_required
def get_ip_lists():
    """Get IP allowlist and blocklist."""
    result = SecurityService.get_ip_lists()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ip-lists/<list_type>', methods=['POST'])
@admin_required
def add_to_ip_list(list_type):
    """Add IP to allowlist or blocklist."""
    data = request.get_json()
    if not data or 'ip' not in data:
        return jsonify({'error': 'IP address required'}), 400

    comment = data.get('comment', '')
    result = SecurityService.add_to_ip_list(data['ip'], list_type, comment)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/ip-lists/<list_type>/<ip>', methods=['DELETE'])
@admin_required
def remove_from_ip_list(list_type, ip):
    """Remove IP from allowlist or blocklist."""
    result = SecurityService.remove_from_ip_list(ip, list_type)
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# SECURITY AUDIT
# ==========================================
@security_bp.route('/audit', methods=['GET'])
@admin_required
def generate_audit():
    """Generate a security audit report."""
    result = SecurityService.generate_security_audit()
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# VULNERABILITY SCANNING (Lynis)
# ==========================================
@security_bp.route('/lynis/status', methods=['GET'])
@admin_required
def get_lynis_status():
    """Get Lynis installation status."""
    status = SecurityService.get_lynis_status()
    return jsonify(status), 200


@security_bp.route('/lynis/install', methods=['POST'])
@admin_required
def install_lynis():
    """Install Lynis."""
    result = SecurityService.install_lynis()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/lynis/scan', methods=['POST'])
@admin_required
def run_lynis_scan():
    """Start a Lynis security scan."""
    result = SecurityService.run_lynis_scan()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/lynis/scan/status', methods=['GET'])
@admin_required
def get_lynis_scan_status():
    """Get Lynis scan status."""
    status = SecurityService.get_lynis_scan_status()
    return jsonify(status), 200


# ==========================================
# AUTOMATIC UPDATES
# ==========================================
@security_bp.route('/auto-updates/status', methods=['GET'])
@admin_required
def get_auto_updates_status():
    """Get automatic updates status."""
    status = SecurityService.get_auto_updates_status()
    return jsonify(status), 200


@security_bp.route('/auto-updates/install', methods=['POST'])
@admin_required
def install_auto_updates():
    """Install automatic updates package."""
    result = SecurityService.install_auto_updates()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/auto-updates/enable', methods=['POST'])
@admin_required
def enable_auto_updates():
    """Enable automatic security updates."""
    result = SecurityService.enable_auto_updates()
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/auto-updates/disable', methods=['POST'])
@admin_required
def disable_auto_updates():
    """Disable automatic security updates."""
    result = SecurityService.disable_auto_updates()
    return jsonify(result), 200 if result['success'] else 400


# ==========================================
# IMAGE VULNERABILITY SCANNING
# ==========================================
@security_bp.route('/image-scans/install', methods=['POST'])
@admin_required
def install_image_scanner():
    """Install grype and syft scanner binaries."""
    grype = ImageScannerService.install_grype()
    syft = ImageScannerService.install_syft()
    return jsonify({'grype': grype, 'syft': syft}), 200


@security_bp.route('/image-scans/applications/<int:application_id>', methods=['POST'])
@admin_required
def scan_application_image(application_id):
    """Trigger a CVE scan for an application image."""
    result = ImageScannerService.scan_application(application_id)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/image-scans/applications/<int:application_id>', methods=['GET'])
@admin_required
def get_application_image_scans(application_id):
    """Get scan history for an application."""
    limit = request.args.get('limit', 20, type=int)
    scans = ImageScannerService.scan_history(application_id, limit=limit)
    latest = ImageScannerService.latest_scan(application_id)
    return jsonify({
        'scans': scans,
        'latest': latest.to_dict() if latest else None
    }), 200


@security_bp.route('/image-scans/<int:scan_id>', methods=['GET'])
@admin_required
def get_image_scan(scan_id):
    """Get a single scan with findings."""
    from app.models import ImageVulnerabilityScan
    scan = ImageVulnerabilityScan.query.get(scan_id)
    if not scan:
        return jsonify({'error': 'Scan not found'}), 404
    return jsonify(scan.to_dict(include_findings=True)), 200


@security_bp.route('/image-scans/applications/<int:application_id>/deploy-gate', methods=['GET'])
@admin_required
def get_image_deploy_gate(application_id):
    """Check whether the latest scan passes the deploy gate."""
    from app.services.image_scanner_service import ImageScannerService
    allowed = request.args.getlist('allowed') or None
    result = ImageScannerService.check_deploy_gate(application_id, allowed_severities=allowed)
    return jsonify(result), 200


# ==========================================
# SBOM GENERATION
# ==========================================
@security_bp.route('/sboms/applications/<int:application_id>', methods=['POST'])
@admin_required
def generate_application_sbom(application_id):
    """Generate an SPDX SBOM for an application image."""
    from app.services.image_scanner_service import ImageScannerService
    result = ImageScannerService.generate_sbom(application_id)
    return jsonify(result), 200 if result['success'] else 400


@security_bp.route('/sboms/applications/<int:application_id>', methods=['GET'])
@admin_required
def get_application_sboms(application_id):
    """List generated SBOMs for an application."""
    from app.models import SbomArtifact
    sboms = SbomArtifact.query.filter_by(application_id=application_id).order_by(
        SbomArtifact.created_at.desc()).limit(50).all()
    return jsonify({'sboms': [s.to_dict() for s in sboms]}), 200


@security_bp.route('/sboms/<int:sbom_id>', methods=['GET'])
@admin_required
def get_sbom(sbom_id):
    """Download an SPDX SBOM JSON."""
    from app.models import SbomArtifact
    sbom = SbomArtifact.query.get(sbom_id)
    if not sbom:
        return jsonify({'error': 'SBOM not found'}), 404
    return jsonify(sbom.to_dict(include_sbom=True)), 200


# ==========================================
# FILE INTEGRITY MONITORING (SCOPED FIM)
# ==========================================
# Baseline-and-diff over ServerKit-managed paths (nginx / systemd /
# opted-in app docroots). The legacy /integrity/* endpoints above are kept
# as-is for compatibility; this is the scoped surface the UI uses.

@security_bp.route('/fim', methods=['GET'])
@jwt_required()
def get_fim_status():
    """Get FIM scopes, baselines and last check results."""
    from app.services.file_integrity_service import FileIntegrityService
    return jsonify(FileIntegrityService.get_status()), 200


@security_bp.route('/fim/<scope>/baseline', methods=['POST'])
@admin_required
def fim_baseline(scope):
    """Create (or recreate) the baseline for a scope."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    data = request.get_json(silent=True) or {}
    options = data.get('options') if isinstance(data.get('options'), dict) else None
    try:
        result = FileIntegrityService.baseline(scope, options=options)
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
    return jsonify(result), 200


@security_bp.route('/fim/<scope>/check', methods=['POST'])
@admin_required
def fim_check(scope):
    """Diff the scope against its baseline."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    try:
        result = FileIntegrityService.check(scope)
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
    return jsonify(result), 200


@security_bp.route('/fim/<scope>/accept', methods=['POST'])
@admin_required
def fim_accept(scope):
    """Accept current state (re-baseline the scope)."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    try:
        result = FileIntegrityService.accept(scope)
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return unexpected_response(exc)
    return jsonify(result), 200


@security_bp.route('/fim/apps', methods=['PUT'])
@admin_required
def fim_set_app_optins():
    """Set the per-app FIM opt-in list: {app_ids: [1, 2, ...]}."""
    from app.services.file_integrity_service import (
        FileIntegrityService, FileIntegrityScopeError,
    )
    data = request.get_json(silent=True)
    if not data or 'app_ids' not in data:
        return jsonify({'error': 'app_ids required'}), 400
    try:
        ids = FileIntegrityService.set_app_optins(data['app_ids'])
    except FileIntegrityScopeError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'app_optins': ids}), 200
