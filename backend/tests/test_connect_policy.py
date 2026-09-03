"""The panel half of fleet policies.

What matters here is the capability gate: a probe that cannot answer must
leave its bundle out of `capabilities`, because that is what makes ServerKit
Cloud show "not checkable here" instead of marking a healthy server
non-compliant. Every probe is replaced by the test, so nothing touches the
host.
"""
import pytest

from app.services import connect_policy


class _Firewall:
    active = True
    ports = [2222]

    @classmethod
    def get_status(cls):
        return {"any_active": cls.active}

    @classmethod
    def ssh_ports(cls):
        return list(cls.ports)

    @classmethod
    def enable(cls, firewall=None, force=False):
        cls.active = True
        return {"success": True}


class _Fail2ban:
    installed = True
    running = True

    @classmethod
    def get_fail2ban_status(cls):
        return {"installed": cls.installed, "service_running": cls.running}


class _SecurityPolicy:
    required = False

    @classmethod
    def require_2fa_enabled(cls):
        return cls.required

    @classmethod
    def set_require_2fa(cls, enabled, user_id=None):
        cls.required = bool(enabled)
        return cls.required


@pytest.fixture(autouse=True)
def probes(monkeypatch):
    """Point every probe at an in-memory host."""
    import app.services.firewall_service as fw
    import app.services.fail2ban_jail_service as f2b
    import app.services.security_policy_service as sp
    import app.services.panel_update_service as pu

    _Firewall.active = True
    _Firewall.ports = [2222]
    _Fail2ban.installed = True
    _Fail2ban.running = True
    _SecurityPolicy.required = False

    monkeypatch.setattr(fw, "FirewallService", _Firewall)
    monkeypatch.setattr(f2b, "Fail2banJailService", _Fail2ban)
    monkeypatch.setattr(sp, "SecurityPolicyService", _SecurityPolicy)
    monkeypatch.setattr(pu, "get_status", lambda: {"version": "1.9.22"})
    monkeypatch.setattr(connect_policy, "_backup_policy_rows", lambda app=None: [])
    return True


# ---------- facts ----------


def test_a_healthy_host_reports_every_bundle_it_can():
    facts = connect_policy.build_facts()
    assert facts["facts_version"] == 1
    assert facts["security"]["firewall_enabled"] is True
    assert facts["security"]["fail2ban_running"] is True
    assert facts["security"]["ssh_port"] == 2222
    assert facts["security"]["panel_2fa_required"] is False
    assert facts["updates"]["panel_version"] == "1.9.22"
    assert "security" in facts["capabilities"]
    assert "updates" in facts["capabilities"]


def test_packages_are_never_advertised_because_nothing_probes_them():
    """The rule Cloud has for pending security updates must read as
    "not checkable here", not as "no updates pending"."""
    facts = connect_policy.build_facts()
    assert "packages" not in facts["capabilities"]
    assert "os_security_pending" not in facts["updates"]


def test_a_firewall_that_is_off_is_reported_as_off():
    _Firewall.active = False
    assert connect_policy.build_facts()["security"]["firewall_enabled"] is False


def test_fail2ban_installed_but_stopped_is_not_running():
    _Fail2ban.running = False
    assert connect_policy.build_facts()["security"]["fail2ban_running"] is False


def test_a_probe_that_raises_leaves_its_fact_out_rather_than_guessing(monkeypatch):
    import app.services.firewall_service as fw

    class Broken:
        @staticmethod
        def get_status():
            raise RuntimeError("no ufw here")

        @staticmethod
        def ssh_ports():
            raise RuntimeError("no sshd_config")
    monkeypatch.setattr(fw, "FirewallService", Broken)
    facts = connect_policy.build_facts()
    assert "firewall_enabled" not in facts["security"]
    assert "ssh_port" not in facts["security"]
    # The bundle is still advertised: 2FA and fail2ban answered.
    assert "security" in facts["capabilities"]


def test_a_panel_with_no_backup_engine_is_not_judged_on_backups(monkeypatch):
    monkeypatch.setattr(connect_policy, "_backup_policy_rows", lambda app=None: None)

    import app.services.storage_provider_service as sps

    class NoStorage:
        @staticmethod
        def get_config():
            raise RuntimeError("no storage.json")
    monkeypatch.setattr(sps, "StorageProviderService", NoStorage)
    facts = connect_policy.build_facts()
    assert "backups" not in facts["capabilities"]
    assert "backups" not in facts


def test_the_newest_successful_backup_is_the_one_reported(monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(connect_policy, "_backup_policy_rows", lambda app=None: [
        {"last_status": "success", "last_run_at": now - timedelta(hours=9),
         "last_drill_at": None},
        {"last_status": "success", "last_run_at": now - timedelta(hours=2),
         "last_drill_at": now - timedelta(days=3)},
        {"last_status": "failed", "last_run_at": now, "last_drill_at": None},
    ])
    facts = connect_policy.build_facts()
    assert facts["backups"]["last_success_at"].startswith(
        (now - timedelta(hours=2)).isoformat()[:13])
    assert facts["backups"]["last_verified_at"] is not None
    assert "backups" in facts["capabilities"]


def test_a_backup_that_never_succeeded_reports_the_key_as_null(monkeypatch):
    """Null, not absent: Cloud tells "never succeeded" apart from "did not
    report" by whether the key is there."""
    monkeypatch.setattr(connect_policy, "_backup_policy_rows", lambda app=None: [
        {"last_status": "failed", "last_run_at": None, "last_drill_at": None},
    ])
    facts = connect_policy.build_facts()
    assert facts["backups"]["last_success_at"] is None
    assert "last_success_at" in facts["backups"]


def test_the_facts_frame_is_the_policy_stream():
    frame = connect_policy.facts_frame("pol1", {"facts_version": 1})
    assert frame == {"s": "pol1", "t": "open", "k": "policy",
                     "p": {"facts": {"facts_version": 1}}}


# ---------- repairs ----------


def test_turning_the_firewall_on_uses_the_panels_own_path():
    _Firewall.active = False
    out = connect_policy.enable_firewall({})
    assert out["ok"] is True
    assert _Firewall.active is True


def test_a_firewall_that_refuses_to_come_up_says_why(monkeypatch):
    import app.services.firewall_service as fw

    class Refuses(_Firewall):
        @classmethod
        def enable(cls, firewall=None, force=False):
            return {"success": False, "error": "enabling this would lock SSH out"}
    monkeypatch.setattr(fw, "FirewallService", Refuses)
    out = connect_policy.enable_firewall({})
    assert out["ok"] is False
    assert "lock SSH out" in out["summary"]


def test_requiring_two_factor_turns_the_policy_on():
    out = connect_policy.require_2fa({})
    assert out["ok"] is True
    assert _SecurityPolicy.required is True
    assert "grace window" in out["summary"]


def test_fail2ban_that_is_not_installed_is_refused_with_what_to_do():
    _Fail2ban.installed = False
    out = connect_policy.enable_fail2ban({})
    assert out["ok"] is False
    assert "not installed" in out["summary"]


def test_security_updates_are_refused_honestly_rather_than_faked():
    out = connect_policy.security_upgrade({})
    assert out["ok"] is False
    assert "does not install operating-system security updates" in out["summary"]


def test_check_now_without_a_relay_connection_says_so(monkeypatch):
    monkeypatch.setattr(connect_policy, "_relay_client", lambda: None)
    out = connect_policy.report({})
    assert out["ok"] is False
    assert "not connected to ServerKit Cloud" in out["summary"]


def test_check_now_publishes_the_document(monkeypatch):
    sent = []

    class Client:
        def publish_policy(self, facts):
            sent.append(facts)
            return True
    monkeypatch.setattr(connect_policy, "_relay_client", lambda: Client())
    out = connect_policy.report({})
    assert out["ok"] is True
    assert sent and sent[0]["facts_version"] == 1


def test_every_policy_action_is_registered_with_its_consent_scope():
    from app.services import connect_commands
    for action in ("policy.report", "security.firewall.enable", "security.fail2ban.enable",
                   "security.2fa.require", "packages.security_upgrade", "backup.verify"):
        assert action in connect_commands.HANDLERS
    assert connect_commands.scope_for("security.firewall.enable") == "security.remediate"
    assert connect_commands.scope_for("packages.security_upgrade") == "packages.upgrade"
    assert connect_commands.scope_for("backup.verify") == "backup.run"
    # policy.report has no entry, so its scope is its own name — the Observe
    # bundle every paired panel already grants.
    assert connect_commands.scope_for("policy.report") == "policy.report"
