"""Unit tests for the Phase 5 installer bootstrap (serverkit_installer).

These are pure-logic tests: distro/family mapping, manifest parsing, the
firewall/service command builders, environment predicates, and the read-only
plan. No host mutation, no Flask — the package is import-safe and stdlib-only,
so this file never touches the ``app`` fixture.
"""
import textwrap

import pytest

from serverkit_installer import deps, distro, firewall, service
from serverkit_installer.main import build_plan


# ---------------------------------------------------------------------------
# distro.family_from — must agree with install.sh's os_family_from
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("distro_id,expected", [
    ("ubuntu", "debian"),
    ("debian", "debian"),
    ("linuxmint", "debian"),
    ("fedora", "fedora"),
    ("nobara", "fedora"),
    ("rocky", "rhel"),
    ("almalinux", "rhel"),
    ("centos", "rhel"),
    ("opensuse-leap", "suse"),
    ("opensuse-tumbleweed", "suse"),
    ("sles", "suse"),
    ("arch", "arch"),
    ("manjaro", "arch"),
    ("alpine", "alpine"),
    ("totally-unknown", "unknown"),
])
def test_family_from_known_ids(distro_id, expected):
    assert distro.family_from(distro_id) == expected


@pytest.mark.parametrize("id_like,expected", [
    ("debian", "debian"),
    ("ubuntu debian", "debian"),
    ("rhel centos fedora", "rhel"),   # RHEL clone: rhel wins over fedora
    ("fedora", "fedora"),             # pure fedora spin
    ("suse opensuse", "suse"),
    ("arch", "arch"),
    ("alpine", "alpine"),
    ("plan9", "unknown"),
])
def test_family_from_id_like_fallback(id_like, expected):
    # Unknown ID forces the ID_LIKE path.
    assert distro.family_from("mystery-distro", id_like) == expected


def test_parse_os_release_and_detect(tmp_path):
    osr = tmp_path / "os-release"
    osr.write_text(textwrap.dedent('''\
        NAME="Rocky Linux"
        ID="rocky"
        ID_LIKE="rhel centos fedora"
        PRETTY_NAME="Rocky Linux 9.3 (Blue Onyx)"
        VERSION_ID="9.3"
    '''))
    box = distro.detect(str(osr))
    assert box.id == "rocky"
    assert box.family == "rhel"
    assert box.pretty_name.startswith("Rocky Linux 9")
    assert box.supported is True


def test_detect_missing_os_release_is_unknown(tmp_path):
    box = distro.detect(str(tmp_path / "does-not-exist"))
    assert box.family == "unknown"
    assert box.supported is False


# ---------------------------------------------------------------------------
# distro environment predicates
# ---------------------------------------------------------------------------
def test_is_container_via_cgroup_fixture(tmp_path):
    cg = tmp_path / "cgroup"
    cg.write_text("0::/system.slice/docker-abc.scope\n")
    assert distro.is_container(
        dockerenv=str(tmp_path / "none"),
        containerenv=str(tmp_path / "none"),
        container_env="",
        cgroup_file=str(cg),
    ) is True


def test_is_container_force_and_plain_host(tmp_path):
    assert distro.is_container(force=True) is True
    assert distro.is_container(force=False) is False
    cg = tmp_path / "cgroup"
    cg.write_text("0::/init.scope\n")
    assert distro.is_container(
        dockerenv=str(tmp_path / "none"),
        containerenv=str(tmp_path / "none"),
        container_env="",
        cgroup_file=str(cg),
    ) is False


def test_is_wsl(tmp_path):
    osr = tmp_path / "osrelease"
    osr.write_text("5.15.0-microsoft-standard-WSL2\n")
    assert distro.is_wsl(osrelease_file=str(osr)) is True
    bare = tmp_path / "bare"
    bare.write_text("6.1.0-generic\n")
    assert distro.is_wsl(osrelease_file=str(bare)) is False
    assert distro.is_wsl(force=True) is True


def test_has_systemd_force():
    assert distro.has_systemd(force=True) is True
    assert distro.has_systemd(force=False) is False


# ---------------------------------------------------------------------------
# deps — manifest loader (uses the real scripts/deps/manifest.yaml)
# ---------------------------------------------------------------------------
def test_manifest_loads_and_resolves_every_family():
    manifest = deps.load_manifest()
    for family in distro.FAMILIES:
        base = deps.base_packages(manifest, family)
        # Gentoo names packages as category/atom (www-servers/nginx).
        assert any(p == "nginx" or p.endswith("/nginx") for p in base), \
            f"{family} base packages should include nginx"
        assert deps.package_manager(manifest, family), f"{family} needs a package manager"
        assert deps.python_spec(manifest, family), f"{family} needs a python spec"


def test_manifest_python_packages_match_policy():
    manifest = deps.load_manifest()
    # Debian 12 ships 3.11; Ubuntu/Fedora ship 3.12.
    assert deps.python_spec(manifest, "debian")["package"] == "python3.11"
    assert deps.python_spec(manifest, "fedora")["package"] == "python3.12"
    assert deps.package_manager(manifest, "suse") == "zypper"


# ---------------------------------------------------------------------------
# firewall command builders (pure)
# ---------------------------------------------------------------------------
def test_firewall_detect_override():
    assert firewall.detect("ufw") == "ufw"


def test_firewall_open_firewalld():
    cmds = firewall.open_commands("firewalld", ["80/tcp", "443/tcp"])
    assert ["firewall-cmd", "--permanent", "--add-port=80/tcp"] in cmds
    assert ["firewall-cmd", "--permanent", "--add-port=443/tcp"] in cmds
    assert cmds[-1] == ["firewall-cmd", "--reload"]


def test_firewall_open_ufw_and_iptables():
    assert firewall.open_commands("ufw", ["80/tcp"]) == [["ufw", "allow", "80/tcp"]]
    assert firewall.open_commands("iptables", ["443/tcp"]) == [
        ["iptables", "-I", "INPUT", "-p", "tcp", "--dport", "443", "-j", "ACCEPT"]
    ]


def test_firewall_close_mirrors_open():
    assert firewall.close_commands("ufw", ["80/tcp"]) == [["ufw", "delete", "allow", "80/tcp"]]
    fd = firewall.close_commands("firewalld", ["80/tcp"])
    assert ["firewall-cmd", "--permanent", "--remove-port=80/tcp"] in fd
    assert fd[-1] == ["firewall-cmd", "--reload"]


def test_firewall_none_is_empty():
    assert firewall.open_commands("none", ["80/tcp"]) == []


def test_firewall_apply_dry_run_renders_without_executing():
    cmds = firewall.open_commands("firewalld", ["80/tcp"])
    rendered = firewall.apply(cmds, dry_run=True)
    assert any("firewall-cmd --permanent --add-port=80/tcp" in r for r in rendered)


# ---------------------------------------------------------------------------
# service / init command builders (pure)
# ---------------------------------------------------------------------------
def test_service_detect_override():
    assert service.detect("openrc") == "openrc"


@pytest.mark.parametrize("init,expected", [
    ("systemd", ["systemctl", "start", "serverkit"]),
    ("openrc", ["rc-service", "serverkit", "start"]),
    ("runit", ["sv", "up", "serverkit"]),
    ("sysvinit", ["service", "serverkit", "start"]),
])
def test_service_start_command(init, expected):
    assert service.start_command(init, "serverkit") == expected


def test_service_enable_command():
    assert service.enable_command("systemd", "serverkit") == ["systemctl", "enable", "serverkit"]
    assert service.enable_command("openrc", "serverkit") == ["rc-update", "add", "serverkit"]
    # runit/none have no simple enable command.
    assert service.enable_command("none", "serverkit") is None


def test_service_reload_command():
    assert service.reload_command("systemd") == ["systemctl", "daemon-reload"]
    assert service.reload_command("systemd", "serverkit") == ["systemctl", "reload", "serverkit"]


def test_service_apply_dry_run():
    rendered = service.apply(service.start_command("systemd", "serverkit"), dry_run=True)
    assert "systemctl start serverkit" in rendered
    assert service.apply(None, dry_run=True) is None


# ---------------------------------------------------------------------------
# main.build_plan — read-only end-to-end composition
# ---------------------------------------------------------------------------
def test_build_plan_for_a_forced_rhel_box(tmp_path):
    osr = tmp_path / "os-release"
    osr.write_text('ID="rocky"\nID_LIKE="rhel fedora"\nPRETTY_NAME="Rocky Linux 9"\n')
    plan = build_plan(
        os_release_path=str(osr),
        firewall_backend="firewalld",
        init_system="systemd",
    )
    assert plan["distro"]["family"] == "rhel"
    assert plan["distro"]["supported"] is True
    assert "nginx" in plan["packages"]["base"]
    assert plan["packages"]["package_manager"] == "dnf"
    assert plan["firewall"]["backend"] == "firewalld"
    assert any("--add-port=80/tcp" in c for c in plan["firewall"]["open"])
    assert plan["service"]["init"] == "systemd"
    assert plan["service"]["start"] == "systemctl start serverkit"
