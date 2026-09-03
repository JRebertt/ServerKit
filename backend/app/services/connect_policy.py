"""The panel half of fleet policies.

Two jobs, and neither of them is deciding anything. ServerKit Cloud holds the
policy; this panel reports what is true and, when asked with a consent the
operator granted, changes it.

**Facts.** `build_facts()` assembles one document from services that already
exist — the firewall, fail2ban, the 2FA policy, the panel updater, backup
policies, the storage destination — and it advertises a `capabilities` list
naming only the bundles it could actually read. That list is the whole of the
capability gate: a rule Cloud cannot get facts for reads "not checkable here"
rather than "failing", which is FLEET_CONTRACT rule 2 and the difference
between a useful compliance page and a wall of red on servers that are fine.

**Repairs.** Four handlers, each calling the panel's own path — the same code
an operator pressing the button in this panel would run. A repair this install
cannot perform says so in a sentence rather than failing obscurely; Cloud shows
that sentence next to the finding.
"""
import logging
from datetime import datetime, timezone

from app.services.connect_commands import handler

logger = logging.getLogger(__name__)

FACTS_VERSION = 1


def _iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


# ==================== facts ====================


def build_facts(app=None) -> dict:
    """One document describing this server. Never raises: a probe that fails
    leaves its bundle out of `capabilities`, which is the honest answer."""
    facts = {
        "facts_version": FACTS_VERSION,
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "capabilities": [],
    }

    security = _security_facts()
    if security:
        facts["security"] = security
        facts["capabilities"].append("security")

    updates = _update_facts()
    if updates:
        facts["updates"] = updates
        facts["capabilities"].append("updates")

    backups = _backup_facts(app)
    if backups is not None:
        facts["backups"] = backups
        facts["capabilities"].append("backups")

    return facts


def _security_facts() -> dict:
    out = {}
    try:
        from app.services.firewall_service import FirewallService
        status = FirewallService.get_status() or {}
        out["firewall_enabled"] = bool(status.get("any_active"))
    except Exception:
        logger.debug("Connect policy: no firewall status", exc_info=True)
    try:
        from app.services.firewall_service import FirewallService
        ports = FirewallService.ssh_ports()
        if ports:
            # One number is what the rule compares; the lowest configured port
            # is the one an untargeted scan finds first.
            out["ssh_port"] = int(min(ports))
    except Exception:
        logger.debug("Connect policy: no ssh port", exc_info=True)
    try:
        from app.services.fail2ban_jail_service import Fail2banJailService
        status = Fail2banJailService.get_fail2ban_status() or {}
        out["fail2ban_running"] = bool(status.get("installed")
                                       and status.get("service_running"))
    except Exception:
        logger.debug("Connect policy: no fail2ban status", exc_info=True)
    try:
        from app.services.security_policy_service import SecurityPolicyService
        out["panel_2fa_required"] = bool(SecurityPolicyService.require_2fa_enabled())
    except Exception:
        logger.debug("Connect policy: no 2FA policy", exc_info=True)
    return out


def _update_facts() -> dict:
    out = {}
    try:
        from app.services import panel_update_service
        out["panel_version"] = panel_update_service.get_status().get("version")
    except Exception:
        logger.debug("Connect policy: no panel version", exc_info=True)
    # Pending operating-system security updates are not probed by this panel
    # yet, so `packages` is deliberately absent from capabilities and Cloud
    # reads that rule as "not checkable here" rather than "no updates pending".
    return out


def _backup_facts(app=None) -> dict | None:
    """Backups need an app context to read policy rows; the destination does
    not. A panel with no backup engine returns None and is not judged on it."""
    out = {}
    try:
        from app.services.storage_provider_service import StorageProviderService
        config = StorageProviderService.get_config()
        out["destination_configured"] = (config.get("provider") or "local") != "local"
    except Exception:
        logger.debug("Connect policy: no storage config", exc_info=True)

    rows = _backup_policy_rows(app)
    if rows is None and not out:
        return None
    if rows is not None:
        newest_success = newest_verify = None
        for row in rows:
            if row.get("last_status") == "success" and row.get("last_run_at"):
                at = row["last_run_at"]
                newest_success = at if newest_success is None or at > newest_success else newest_success
            if row.get("last_drill_at"):
                at = row["last_drill_at"]
                newest_verify = at if newest_verify is None or at > newest_verify else newest_verify
        # The keys are always present when policies could be read, so Cloud can
        # tell "never succeeded" apart from "did not report".
        out["last_success_at"] = _iso(newest_success)
        out["last_verified_at"] = _iso(newest_verify)
    return out


def _backup_policy_rows(app=None):
    try:
        from app.models.backup_policy import BackupPolicy
    except Exception:
        return None

    def collect():
        return [{"last_status": p.last_status, "last_run_at": p.last_run_at,
                 "last_drill_at": p.last_drill_at} for p in BackupPolicy.query.all()]

    try:
        if app is not None:
            with app.app_context():
                return collect()
        return collect()
    except Exception:
        logger.debug("Connect policy: could not read backup policies", exc_info=True)
        return None


def facts_frame(stream_id: str, facts: dict) -> dict:
    return {"s": stream_id, "t": "open", "k": "policy", "p": {"facts": facts}}


# ==================== commands ====================


@handler('policy.report')
def report(args: dict, app=None) -> dict:
    """"Check now": build a document and push it up the policy stream."""
    facts = build_facts(app)
    client = _relay_client()
    if client is None or not client.publish_policy(facts):
        return {'ok': False, 'summary': 'The panel is not connected to ServerKit Cloud right '
                                        'now, so the check could not be sent. It goes out on '
                                        'the next connection.'}
    return {'ok': True, 'summary': f'Reported {len(facts.get("capabilities") or [])} fact '
                                   f'bundles.'}


@handler('security.firewall.enable')
def enable_firewall(args: dict, app=None) -> dict:
    """Turn the host firewall on, through the panel's own path — including its
    refusal to lock SSH out, which is exactly the check we want here."""
    try:
        from app.services.firewall_service import FirewallService
    except Exception as exc:
        return {'ok': False, 'summary': f'This install has no firewall management ({exc}).'}
    result = FirewallService.enable() or {}
    if result.get('success') is False or result.get('error'):
        return {'ok': False, 'summary': result.get('error') or 'The firewall did not come up.'}
    return {'ok': True, 'summary': 'The host firewall is on.'}


@handler('security.2fa.require')
def require_2fa(args: dict, app=None) -> dict:
    """Turn on the panel's require-2FA policy. Its grace window starts now, so
    nobody is locked out by a policy that arrived while they were asleep."""
    try:
        from app.services.security_policy_service import SecurityPolicyService
    except Exception as exc:
        return {'ok': False, 'summary': f'This install has no 2FA policy ({exc}).'}

    def go():
        SecurityPolicyService.set_require_2fa(True)
    if app is not None:
        with app.app_context():
            go()
    else:
        go()
    return {'ok': True, 'summary': 'The panel now requires two-factor authentication, with its '
                                   'usual grace window for people who have not set it up yet.'}


@handler('security.fail2ban.enable')
def enable_fail2ban(args: dict, app=None) -> dict:
    """Start fail2ban if this host manages its own services."""
    try:
        from app.services.fail2ban_jail_service import Fail2banJailService
        status = Fail2banJailService.get_fail2ban_status() or {}
    except Exception as exc:
        return {'ok': False, 'summary': f'This install cannot manage fail2ban ({exc}).'}
    if not status.get('installed'):
        return {'ok': False, 'summary': 'fail2ban is not installed on this host. Install it and '
                                        'ServerKit Cloud will see it on the next check.'}
    started = _systemctl('start', 'fail2ban')
    if started is not True:
        return {'ok': False, 'summary': f'fail2ban would not start: {started}'}
    return {'ok': True, 'summary': 'fail2ban is running.'}


@handler('backup.verify')
def verify_backup(args: dict, app=None) -> dict:
    try:
        from app.services.backup_offsite_service import BackupOffsiteService
    except Exception as exc:
        return {'ok': False, 'summary': f'This install has no offsite verification ({exc}).'}

    def go():
        return BackupOffsiteService.run_offsite_verify()
    result = (go() if app is None else _in_app(app, go)) or {}
    if result.get('success') is False or result.get('error'):
        return {'ok': False, 'summary': result.get('error') or 'The verification did not pass.'}
    return {'ok': True, 'summary': 'The most recent backup was read back from its destination.'}


@handler('packages.security_upgrade')
def security_upgrade(args: dict, app=None) -> dict:
    """Not implemented on the panel yet, and it says so rather than pretending.

    Cloud shows this sentence next to the finding, which is the truth: the rule
    that produced it evaluates `unsupported` anyway, because `_update_facts`
    does not advertise the `packages` bundle.
    """
    return {'ok': False,
            'summary': 'This version of ServerKit does not install operating-system security '
                       'updates from ServerKit Cloud. Run them on the host, or update ServerKit '
                       'and try again.'}


def _in_app(app, fn):
    with app.app_context():
        return fn()


def _systemctl(action: str, unit: str):
    """True, or the reason it did not work. Never raises.

    run_privileged() adds sudo when the panel is not root, which is the
    difference between a repair that works off a packaged install and one
    that reports a permission error the operator cannot act on.
    """
    from app.utils.system import is_command_available, run_privileged
    if not is_command_available('systemctl'):
        return 'this host does not use systemd'
    try:
        out = run_privileged(['systemctl', action, unit], timeout=60)
    except Exception as exc:
        return str(exc)
    if out.returncode == 0:
        return True
    return (out.stderr or out.stdout or f'systemctl {action} {unit} exited {out.returncode}').strip()


def _relay_client():
    try:
        from app.services import connect_client
        return connect_client.get_client()
    except Exception:
        return None
