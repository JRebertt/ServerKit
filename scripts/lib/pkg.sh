# shellcheck shell=bash
#
# scripts/lib/pkg.sh — sourceable cross-distro package-management abstraction.
#
# The ServerKit installer/updater needs to refresh the package index, install a
# handful of OS packages, and check whether something is already present — and it
# has to do this identically on Debian/Ubuntu (apt), RHEL/Rocky/Alma/Fedora
# (dnf, or yum on older boxes), openSUSE (zypper), Arch (pacman) and Alpine
# (apk). Sprinkling per-distro `if command -v apt` branches through every script
# rots fast and is impossible to unit-test, so we centralise the dispatch here.
#
# This bash helper mirrors the semantics of the Python PackageManager class in
# backend/app/utils/system.py (same detect → install/is_installed contract,
# same sudo-only-when-needed rule) so the host and the running panel agree on
# what "installed" means. It covers the three managers the Python side knows
# (apt/dnf/yum) plus the three install-time-only ones (zypper/pacman/apk) that
# the shell installer can hit before the panel is even up.
#
# Contract (these names/behaviours are depended on by callers and unit tests —
# do not rename them or add extra public functions):
#   pkg_detect                  → echoes: apt|dnf|yum|zypper|pacman|apk|"" (none)
#   pkg_refresh                 → refresh the package index (best-effort)
#   pkg_install <pkg> [pkg...]  → install packages non-interactively
#   pkg_is_installed <pkg>      → return 0 if installed, 1 otherwise
#
# Honors:
#   PKG_DRY_RUN=1          print intended commands instead of running them
#   PKG_MGR_OVERRIDE=...   force the detected manager (used by unit tests)
#
# Everything mutating is best-effort and privilege-aware: a refresh/install we
# can't run cleanly degrades to a non-zero return rather than aborting the
# caller, and sudo is prepended only when we are not already root.

# Prepend sudo for a mutating command when we are not root AND sudo exists;
# otherwise run the command as-is. Mirrors _needs_sudo() in system.py — minimal
# containers run as root without sudo installed, and Windows dev boxes have no
# sudo at all, so blindly prefixing it would break those.
_pkg_sudo() {
    if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
        sudo "$@"
        return $?
    fi
    "$@"
}

# Run a (privileged) mutating package command, or just print it under dry-run.
# Kept tiny so the dry-run output is exactly the command that would otherwise
# execute — which is what the installer unit tests assert against.
_pkg_run() {
    if [ "${PKG_DRY_RUN:-0}" = "1" ]; then
        printf '  [pkg] would run: %s\n' "$*"
        return 0
    fi
    # Discard the tool's own chatter (progress bars, "Nothing to do" noise) here
    # so callers don't redirect — that redirection would also swallow the
    # dry-run line above, which the installer unit tests assert on.
    _pkg_sudo "$@" >/dev/null 2>&1
}

# Detect the active package manager. Order matters and is fixed (apt first):
# a box can have several of these binaries installed, so we pick the first that
# is present in the documented precedence. An explicit override short-circuits
# detection entirely — that is how the unit tests force a given manager.
pkg_detect() {
    if [ -n "${PKG_MGR_OVERRIDE:-}" ]; then
        printf '%s\n' "$PKG_MGR_OVERRIDE"
        return 0
    fi
    local mgr
    for mgr in apt dnf yum zypper pacman apk; do
        if command -v "$mgr" >/dev/null 2>&1; then
            printf '%s\n' "$mgr"
            return 0
        fi
    done
    # No supported manager found: echo nothing (empty string).
    printf '\n'
    return 0
}

# Refresh the package index for the detected manager. Best-effort: index
# refreshes routinely fail on a flaky mirror and that should not abort an
# install, so we never propagate the manager's exit here — every arm is
# guarded and the function always returns 0.
pkg_refresh() {
    local mgr
    mgr="$(pkg_detect)"
    case "$mgr" in
        apt)    _pkg_run apt-get update || true ;;
        dnf)    _pkg_run dnf makecache --refresh || true ;;
        yum)    _pkg_run yum makecache || true ;;
        zypper) _pkg_run zypper --non-interactive refresh || true ;;
        pacman) _pkg_run pacman -Sy --noconfirm || true ;;
        apk)    _pkg_run apk update || true ;;
        *)      : ;;
    esac
    return 0
}

# Install one or more packages non-interactively for the detected manager.
# Propagates the manager's non-zero exit on failure (callers want to know an
# install failed); returns 1 with a stderr note when no manager was detected.
pkg_install() {
    if [ "$#" -eq 0 ]; then
        return 0
    fi
    local mgr
    mgr="$(pkg_detect)"
    case "$mgr" in
        # Deliberate word-splitting of the package list via "$@" — each argument
        # is already a separate, individually-quoted package name.
        # `env VAR=…` rather than an exported variable: _pkg_sudo runs plain
        # `sudo "$@"`, and sudo's env_reset would drop an exported
        # DEBIAN_FRONTEND before apt ever saw it. Putting it in argv survives.
        # Without it, debconf (tzdata et al) opens a dialog and waits forever —
        # the docstring above promised "non-interactively" and only apt did not
        # deliver it. --force-conf* covers modified-conffile prompts, which
        # DEBIAN_FRONTEND does not suppress.
        apt)    _pkg_run env DEBIAN_FRONTEND=noninteractive apt-get install -y \
                    -o Dpkg::Options::=--force-confold \
                    -o Dpkg::Options::=--force-confdef "$@" ;;
        dnf)    _pkg_run dnf install -y "$@" ;;
        yum)    _pkg_run yum install -y "$@" ;;
        zypper) _pkg_run zypper --non-interactive install "$@" ;;
        pacman) _pkg_run pacman -S --noconfirm "$@" ;;
        apk)    _pkg_run apk add "$@" ;;
        *)
            printf '  [pkg] no supported package manager found — cannot install: %s\n' "$*" >&2
            return 1
            ;;
    esac
}

# Return 0 if <pkg> is installed, 1 otherwise. Query-only (no sudo): we use the
# distro's low-level package database rather than the high-level manager so the
# answer matches what an install would see. Each branch tolerates the query tool
# being absent (it returns non-zero / 1 rather than aborting the caller).
pkg_is_installed() {
    local pkg="$1"
    local mgr
    mgr="$(pkg_detect)"
    case "$mgr" in
        apt)
            # dpkg can report a removed-but-configured package with returncode 0,
            # so additionally require the "install ok installed" status line —
            # matching PackageManager.is_installed() in system.py.
            local out
            if ! command -v dpkg >/dev/null 2>&1; then
                return 1
            fi
            out="$(dpkg -s "$pkg" 2>/dev/null)" || return 1
            case "$out" in
                *'install ok installed'*) return 0 ;;
                *) return 1 ;;
            esac
            ;;
        dnf|yum|zypper)
            command -v rpm >/dev/null 2>&1 || return 1
            rpm -q "$pkg" >/dev/null 2>&1
            ;;
        pacman)
            command -v pacman >/dev/null 2>&1 || return 1
            pacman -Q "$pkg" >/dev/null 2>&1
            ;;
        apk)
            command -v apk >/dev/null 2>&1 || return 1
            apk info -e "$pkg" >/dev/null 2>&1
            ;;
        *)
            return 1
            ;;
    esac
}
