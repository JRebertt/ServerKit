"""OS / distro + environment detection.

The family mapping is a faithful port of install.sh's ``os_family_from`` (kept
in lockstep so bash and Python agree on what "supported distro" means), and the
container/WSL/systemd predicates mirror scripts/lib/env.sh.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

FAMILIES = ("debian", "rhel", "fedora", "suse", "arch", "alpine", "gentoo")

# Exact ID → family map (matches install.sh's case arms).
_ID_FAMILY = {
    "ubuntu": "debian", "linuxmint": "debian", "pop": "debian",
    "raspbian": "debian", "elementary": "debian", "zorin": "debian",
    "debian": "debian", "devuan": "debian",
    "fedora": "fedora", "nobara": "fedora",
    "rocky": "rhel", "almalinux": "rhel", "rhel": "rhel", "centos": "rhel",
    "ol": "rhel", "oracle": "rhel", "eurolinux": "rhel",
    "sles": "suse", "sled": "suse", "suse": "suse", "sle-micro": "suse",
    "arch": "arch", "manjaro": "arch", "endeavouros": "arch", "cachyos": "arch",
    "alpine": "alpine",
    "gentoo": "gentoo", "funtoo": "gentoo",
}

# ID_LIKE substrings → family, in priority order. rhel before fedora so RHEL
# clones (ID_LIKE="rhel centos fedora") pick the RHEL family, not fedora.
_LIKE_FAMILY = (
    ("debian", "debian"), ("ubuntu", "debian"),
    ("rhel", "rhel"), ("centos", "rhel"),
    ("fedora", "fedora"),
    ("suse", "suse"),
    ("arch", "arch"),
    ("alpine", "alpine"),
    ("gentoo", "gentoo"),
)


def family_from(distro_id: str, id_like: str = "") -> str:
    """Map an os-release ID (+ ID_LIKE fallback) to a ServerKit family.

    Returns one of FAMILIES or ``"unknown"``.
    """
    did = (distro_id or "").strip().lower()
    if did in _ID_FAMILY:
        return _ID_FAMILY[did]
    if did.startswith("opensuse"):
        return "suse"
    like = (id_like or "").lower()
    for needle, family in _LIKE_FAMILY:
        if needle in like:
            return family
    return "unknown"


def parse_os_release(path: str = "/etc/os-release") -> dict:
    """Parse a shell-style os-release file into a dict. Missing file → {}."""
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


@dataclass(frozen=True)
class Distro:
    id: str
    id_like: str
    pretty_name: str
    family: str

    @property
    def supported(self) -> bool:
        return self.family in FAMILIES


def detect(os_release_path: str = "/etc/os-release") -> Distro:
    """Detect the running distro from an os-release file."""
    data = parse_os_release(os_release_path)
    return Distro(
        id=data.get("ID", ""),
        id_like=data.get("ID_LIKE", ""),
        pretty_name=data.get("PRETTY_NAME", ""),
        family=family_from(data.get("ID", ""), data.get("ID_LIKE", "")),
    )


# ---------------------------------------------------------------------------
# Environment predicates (mirror scripts/lib/env.sh). The keyword overrides
# exist for unit testing against fixtures.
# ---------------------------------------------------------------------------
_CONTAINER_CGROUP_MARKERS = ("docker", "lxc", "containerd", "kubepods", "podman")


def is_container(
    *,
    force: "bool | None" = None,
    dockerenv: str = "/.dockerenv",
    containerenv: str = "/run/.containerenv",
    cgroup_file: str = "/proc/1/cgroup",
    container_env: "str | None" = None,
) -> bool:
    """True when running inside a container."""
    if force is not None:
        return force
    if os.path.exists(dockerenv):
        return True
    if os.path.exists(containerenv):
        return True
    env_val = os.environ.get("container") if container_env is None else container_env
    if env_val:
        return True
    try:
        with open(cgroup_file, encoding="utf-8", errors="ignore") as handle:
            content = handle.read()
        return any(marker in content for marker in _CONTAINER_CGROUP_MARKERS)
    except OSError:
        return False


def is_wsl(
    *,
    force: "bool | None" = None,
    osrelease_file: str = "/proc/sys/kernel/osrelease",
) -> bool:
    """True under Windows Subsystem for Linux."""
    if force is not None:
        return force
    try:
        with open(osrelease_file, encoding="utf-8", errors="ignore") as handle:
            content = handle.read().lower()
        return "microsoft" in content or "wsl" in content
    except OSError:
        return False


def has_systemd(
    *,
    force: "bool | None" = None,
    systemd_dir: str = "/run/systemd/system",
) -> bool:
    """True when systemd is usable as the init/service manager."""
    if force is not None:
        return force
    return bool(shutil.which("systemctl")) and os.path.isdir(systemd_dir)
