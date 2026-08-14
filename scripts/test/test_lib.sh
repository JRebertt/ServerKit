#!/usr/bin/env bash
#
# Unit tests for the multi-distro abstraction libs:
#   scripts/lib/pkg.sh       — package-manager abstraction
#   scripts/lib/init.sh      — init-system / service control
#   scripts/lib/env.sh       — container / WSL / systemd detection
#   scripts/lib/state.sh     — install-state tracker (warn-and-no-op contract)
#   scripts/lib/firewall.sh  — firewall abstraction (detection under pipefail)
#   scripts/lib/uninstall.sh — canonical teardown (never dies mid-teardown)
# plus the root uninstall.sh entry point's remnants-only fallback path.
#
# Everything is pure, override-friendly, and dry-run aware — or exercised
# against throwaway fixtures and PATH stubs — so it tests deterministically on
# any host (including this Windows/Git-Bash dev box) without touching a real
# package manager, init system, firewall, or /etc.
#
# Each unit-under-test runs in a subshell that re-enables `set -Eeuo pipefail`,
# so an unguarded command silently aborting under set -e is caught here as a
# failed assertion rather than on someone's server.
#
# Run:  bash scripts/test/test_lib.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "$SCRIPT_DIR/../lib" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

PASS=0
FAIL=0
SKIP=0
ok()   { PASS=$((PASS + 1)); printf '  \033[32m✔\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  \033[31m✘\033[0m %s\n' "$1"; }
skip() { SKIP=$((SKIP + 1)); printf '  \033[33m∼\033[0m %s (skipped)\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Shared stub factories.
# shellcheck source=stubs.sh
source "$SCRIPT_DIR/stubs.sh"

# shellcheck source=/dev/null
source "$LIB_DIR/pkg.sh"
# shellcheck source=/dev/null
source "$LIB_DIR/init.sh"
# shellcheck source=/dev/null
source "$LIB_DIR/env.sh"

printf '\nmulti-distro lib unit tests\n\n'

# ==========================================================================
# pkg.sh
# ==========================================================================
for mgr in apt dnf yum zypper pacman apk; do
    if ! got="$( set -Eeuo pipefail; PKG_MGR_OVERRIDE="$mgr" pkg_detect )" || [ "$got" != "$mgr" ]; then
        bad "pkg_detect override $mgr -> [$got]"
    fi
done
ok "pkg_detect honors PKG_MGR_OVERRIDE for all six managers"

# Each manager's install command, captured in dry-run.
declare -A expect_install=(
    # apt must carry the non-interactive guard in ARGV (sudo strips exported
    # env), or debconf stalls the install forever with no visible prompt.
    [apt]="env DEBIAN_FRONTEND=noninteractive apt-get install -y"
    [dnf]="dnf install -y git"
    [yum]="yum install -y git"
    [zypper]="zypper --non-interactive install git"
    [pacman]="pacman -S --noconfirm git"
    [apk]="apk add git"
)
allok=1
for mgr in "${!expect_install[@]}"; do
    if ! out="$( set -Eeuo pipefail; PKG_DRY_RUN=1 PKG_MGR_OVERRIDE="$mgr" pkg_install git 2>&1 )" \
       || ! printf '%s' "$out" | grep -qF "${expect_install[$mgr]}"; then
        bad "pkg_install $mgr dry-run: [$out]"; allok=0
    fi
done
[ "$allok" = "1" ] && ok "pkg_install emits the right command per manager (dry-run)"

# Every manager must be non-interactive. An install that stops to ask a question
# nobody can answer hangs forever, and under `curl | bash` stdin is the script
# itself — so the prompt may consume installer source as its answer.
declare -A expect_noninteractive=(
    [apt]="DEBIAN_FRONTEND=noninteractive"
    [dnf]="-y"
    [yum]="-y"
    [zypper]="--non-interactive"
    [pacman]="--noconfirm"
)
allok=1
for mgr in "${!expect_noninteractive[@]}"; do
    # `--` before the pattern: these expectations are flags (-y, --noconfirm),
    # and grep would otherwise parse them as its own options.
    if ! out="$( set -Eeuo pipefail; PKG_DRY_RUN=1 PKG_MGR_OVERRIDE="$mgr" pkg_install git 2>&1 )" \
       || ! printf '%s' "$out" | grep -qF -- "${expect_noninteractive[$mgr]}"; then
        bad "pkg_install $mgr can prompt: [$out]"; allok=0
    fi
done
[ "$allok" = "1" ] && ok "pkg_install is non-interactive for every manager"

# Empty PATH genuinely hides every package manager (CI distro containers DO ship
# one, so PKG_MGR_OVERRIDE="" alone would run a real install here).
if ( set -Eeuo pipefail; PATH="" PKG_MGR_OVERRIDE="" PKG_DRY_RUN=0 pkg_install git ) 2>/dev/null; then
    bad "pkg_install must fail (return 1) when no manager is detected"
else
    ok "pkg_install returns non-zero when no package manager is present"
fi

# ==========================================================================
# init.sh
# ==========================================================================
for init in systemd openrc runit sysvinit none; do
    if ! got="$( set -Eeuo pipefail; INIT_OVERRIDE="$init" init_detect )" || [ "$got" != "$init" ]; then
        bad "init_detect override $init -> [$got]"
    fi
done
ok "init_detect honors INIT_OVERRIDE for all five init systems"

# Start command per init, captured in dry-run (substring match — sudo prefix
# varies with euid and is irrelevant to the assertion).
allok=1
check_start() { # <init> <expected-substring>
    local out
    if ! out="$( set -Eeuo pipefail; INIT_OVERRIDE="$1" INIT_DRY_RUN=1 init_start serverkit 2>&1 )" \
       || ! printf '%s' "$out" | grep -qF "$2"; then
        bad "init_start $1 dry-run: [$out]"; allok=0
    fi
}
check_start systemd  "systemctl start serverkit"
check_start openrc   "rc-service serverkit start"
check_start runit    "sv up serverkit"
check_start sysvinit "service serverkit start"
[ "$allok" = "1" ] && ok "init_start emits the right command per init system (dry-run)"

if ( set -Eeuo pipefail; INIT_OVERRIDE=none init_start serverkit ) >/dev/null 2>&1; then
    bad "init_start must return non-zero under 'none'"
else
    ok "init_start returns non-zero (and warns) when no init system is detected"
fi

# init_reload: no service arg under systemd → daemon-reload.
if out="$( set -Eeuo pipefail; INIT_OVERRIDE=systemd INIT_DRY_RUN=1 init_reload 2>&1 )" \
   && printf '%s' "$out" | grep -qF "systemctl daemon-reload"; then
    ok "init_reload (no arg, systemd) runs daemon-reload"
else
    bad "init_reload systemd no-arg: [$out]"
fi

# ==========================================================================
# env.sh
# ==========================================================================
cg="$WORK/cgroup"; printf '0::/system.slice/docker-abc.scope\n' > "$cg"
if ( set -Eeuo pipefail; SERVERKIT_CGROUP_FILE="$cg" is_container ); then
    ok "is_container true via a docker cgroup fixture"
else
    bad "is_container should be true for a docker cgroup"
fi
cg2="$WORK/cgroup-host"; printf '0::/init.scope\n' > "$cg2"
# `container=""` neutralizes the ambient env var that RPM/SUSE base images set
# (container=oci) — without it this case would see "we're in a container" via the
# real environment and wrongly report true. We're isolating the cgroup path.
if ( set -Eeuo pipefail; container="" SERVERKIT_IS_CONTAINER="" SERVERKIT_CONTAINERENV_FILE="$WORK/none" SERVERKIT_DOCKERENV_FILE="$WORK/none" SERVERKIT_CGROUP_FILE="$cg2" is_container ); then
    bad "is_container should be false on a plain host cgroup"
else
    ok "is_container false on a non-container cgroup"
fi
if ( set -Eeuo pipefail; SERVERKIT_IS_CONTAINER=1 is_container ) && \
   ! ( set -Eeuo pipefail; SERVERKIT_IS_CONTAINER=0 is_container ); then
    ok "is_container honors the SERVERKIT_IS_CONTAINER force-override"
else
    bad "is_container force-override broken"
fi

osr="$WORK/osrelease"; printf '5.15.0-microsoft-standard-WSL2\n' > "$osr"
if ( set -Eeuo pipefail; SERVERKIT_OSRELEASE_FILE="$osr" is_wsl ); then
    ok "is_wsl true for a microsoft/WSL osrelease fixture"
else
    bad "is_wsl should detect WSL"
fi
osr2="$WORK/osrelease-bare"; printf '6.1.0-generic\n' > "$osr2"
if ( set -Eeuo pipefail; SERVERKIT_IS_WSL="" SERVERKIT_OSRELEASE_FILE="$osr2" is_wsl ); then
    bad "is_wsl should be false for a non-WSL kernel"
else
    ok "is_wsl false for a non-WSL kernel"
fi

if ( set -Eeuo pipefail; SERVERKIT_HAS_SYSTEMD=1 has_systemd ) && \
   ! ( set -Eeuo pipefail; SERVERKIT_HAS_SYSTEMD=0 has_systemd ); then
    ok "has_systemd honors the SERVERKIT_HAS_SYSTEMD force-override"
else
    bad "has_systemd force-override broken"
fi

# ==========================================================================
# init.sh — L13: zero-arg safety under set -u, the detection cache, and the
# init_reload contract.
# ==========================================================================
errf="$WORK/init-noargs.err"
if ( set -Eeuo pipefail; init_start ) 2>"$errf"; then
    bad "init_start with no args must return non-zero"
elif grep -q 'unbound variable' "$errf"; then
    bad "init_start with no args died on an unbound \$1 instead of a clean warn"
elif grep -q 'requires a service name' "$errf"; then
    ok "init_start with no args warns and returns 1 (set -u safe)"
else
    bad "init_start with no args returned 1 but without the missing-name warning"
fi
if ( set -Eeuo pipefail; init_is_active ) 2>"$errf"; then
    bad "init_is_active with no args must return non-zero"
elif grep -q 'unbound variable' "$errf"; then
    bad "init_is_active with no args died on an unbound \$1 under set -u"
else
    ok "init_is_active with no args quietly returns 1 (set -u safe)"
fi

# The lazily-populated cache must be read back — and the override must still
# beat it (that ordering is what keeps per-call INIT_OVERRIDE tests working).
cache_rc=0
got="$( set -Eeuo pipefail; INIT_OVERRIDE="" _INIT_DETECTED=openrc init_detect )" || cache_rc=$?
got2="$( set -Eeuo pipefail; INIT_OVERRIDE=runit _INIT_DETECTED=openrc init_detect )" || cache_rc=$?
if [ "$cache_rc" -eq 0 ] && [ "$got" = "openrc" ] && [ "$got2" = "runit" ]; then
    ok "init_detect serves the _INIT_DETECTED cache, but INIT_OVERRIDE still wins"
else
    bad "init_detect cache/override order wrong (cache→[$got], override→[$got2])"
fi

# init_reload: a NAMED reload behaves like init_start (emits the tool command,
# warns-and-fails under 'none'); a BARE reload is a systemd-only no-op.
reload_ok=1
if ! out="$( set -Eeuo pipefail; INIT_OVERRIDE=openrc INIT_DRY_RUN=1 init_reload serverkit 2>&1 )" \
   || ! printf '%s' "$out" | grep -qF "rc-service serverkit reload"; then
    bad "init_reload openrc dry-run: [$out]"; reload_ok=0
fi
( set -Eeuo pipefail; INIT_OVERRIDE=openrc init_reload ) >/dev/null 2>&1 || { bad "bare init_reload must be a no-op 0 on non-systemd inits"; reload_ok=0; }
( set -Eeuo pipefail; INIT_OVERRIDE=none init_reload serverkit ) >/dev/null 2>&1 && { bad "named init_reload under 'none' must return non-zero like its siblings"; reload_ok=0; }
[ "$reload_ok" = "1" ] && ok "init_reload: named reload matches the siblings' contract; bare reload is systemd-only"

# ==========================================================================
# pkg.sh — L10: pkg_refresh promises "never propagate the manager's exit".
# ==========================================================================
t="$WORK/pkgrefresh"; mkdir -p "$t/bin"
make_stub_exit "$t/bin" 7 apt-get
# sudo shim: on a non-root Linux host _pkg_sudo would prepend sudo; keep the
# stub chain deterministic everywhere.
printf '#!/bin/sh\nexec "$@"\n' > "$t/bin/sudo"; chmod +x "$t/bin/sudo"
if ( set -Eeuo pipefail; PATH="$t/bin:$PATH" PKG_MGR_OVERRIDE=apt PKG_DRY_RUN=0 pkg_refresh ); then
    ok "pkg_refresh returns 0 when the manager's refresh fails (best-effort doc contract)"
else
    bad "pkg_refresh propagated a failing package manager's exit (L10 regression)"
fi

# ==========================================================================
# firewall.sh — L11: ufw detection is capture-then-case (no `| grep -q`
# SIGPIPE race under a pipefail caller), and "inactive" is never misread as
# active. L13: zero-arg calls are safe no-ops under set -u.
# ==========================================================================
t="$WORK/fw"; mkdir -p "$t/on" "$t/off"
# The active stub prints a rule table far bigger than a 64K pipe buffer: with
# the old `ufw status | grep -q` shape, grep exits at the first line and the
# still-writing ufw dies of SIGPIPE — flipping the pipeline non-zero under
# pipefail and misdetecting the box. Capture-then-case must shrug this off.
cat > "$t/on/ufw" <<'UFW_EOF'
#!/bin/sh
echo "Status: active"
i=0
while [ "$i" -lt 2000 ]; do
    echo "22/tcp                     ALLOW       Anywhere         # filler $i"
    i=$((i+1))
done
UFW_EOF
chmod +x "$t/on/ufw"
printf '#!/bin/sh\necho "Status: inactive"\n' > "$t/off/ufw"; chmod +x "$t/off/ufw"
fw_rc=0
# && chains: these captures sit on the left of `||` (and the if-conditions
# below), where bash suppresses set -e even inside the subshell/substitution —
# sequential statements would gate only on the LAST one.
got="$( set -Eeuo pipefail; source "$LIB_DIR/firewall.sh" \
        && PATH="$t/on" FIREWALL_BACKEND="" firewall_detect )" || fw_rc=$?
got2="$( set -Eeuo pipefail; source "$LIB_DIR/firewall.sh" \
        && PATH="$t/off" FIREWALL_BACKEND="" firewall_detect )" || fw_rc=$?
if [ "$fw_rc" -eq 0 ] && [ "$got" = "ufw" ] && [ "$got2" = "none" ]; then
    ok "firewall_detect sees an active ufw under pipefail and never misreads 'inactive'"
else
    bad "firewall_detect wrong: active→[$got] (want ufw), inactive→[$got2] (want none)"
fi

errf="$WORK/fw-noargs.err"
if ( set -Eeuo pipefail; source "$LIB_DIR/firewall.sh" \
     && firewall_open && firewall_close && firewall_manual_hint >/dev/null ) 2>"$errf"; then
    if grep -q 'unbound variable' "$errf"; then
        bad "zero-arg firewall helpers leaked an unbound-variable error"
    else
        ok "firewall_open/close/manual_hint with zero args are safe no-ops under set -u"
    fi
else
    bad "zero-arg firewall helpers aborted under set -u: $(tr -d '\r' < "$errf")"
fi

# ==========================================================================
# state.sh — L1: the header promises warn-and-no-op, so a PRESENT python3
# with an unusable state file (path is a directory, parent is a file,
# unwritable dir) must warn and exit 0 for mutations, and stay quiet-empty
# for reads — never abort a `set -Eeuo pipefail` caller.
# ==========================================================================
if command -v python3 >/dev/null 2>&1; then
    sdir="$WORK/state-as-dir"; mkdir -p "$sdir"
    errf="$WORK/state-l1.err"
    if ( set -Eeuo pipefail; source "$LIB_DIR/state.sh" \
         && SERVERKIT_STATE_FILE="$sdir" state_set firewall_backend ufw ) 2>"$errf"; then
        if grep -q '\[state\]' "$errf"; then
            ok "state_set warns and exits 0 when the state path is a directory"
        else
            bad "state_set exited 0 on a directory state path but never warned"
        fi
    else
        bad "state_set ABORTED when the state path is a directory (L1 regression)"
    fi

    if out="$( set -Eeuo pipefail; source "$LIB_DIR/state.sh" \
               && SERVERKIT_STATE_FILE="$sdir" state_get firewall_backend 2>/dev/null )" \
       && [ -z "$out" ]; then
        ok "state_get is quiet-empty (exit 0) on an unreadable state path"
    else
        bad "state_get aborted or printed [$out] on an unreadable state path"
    fi

    if ( set -Eeuo pipefail; source "$LIB_DIR/state.sh" \
         && ports="$(SERVERKIT_STATE_FILE="$sdir" state_list firewall_ports | tr '\n' ' ')" \
         && [ -z "${ports// /}" ] ); then
        ok "state_list | tr survives set -Eeuo pipefail on an unreadable state path"
    else
        bad "state_list | tr aborted under pipefail (the L2-shaped uninstall killer)"
    fi

    : > "$WORK/state-blocker"
    if ( set -Eeuo pipefail; source "$LIB_DIR/state.sh" \
         && SERVERKIT_STATE_FILE="$WORK/state-blocker/state.json" state_append firewall_ports 80/tcp ) 2>/dev/null; then
        ok "state_append warns and exits 0 when the state parent is a regular file"
    else
        bad "state_append ABORTED when the state parent is a regular file (L1 regression)"
    fi

    # Unwritable parent dir. As root (distro-container CI) or on Windows the
    # write may legitimately succeed — the contract under test is only
    # "never non-zero", which must hold either way.
    ro="$WORK/state-ro"; mkdir -p "$ro"; chmod 555 "$ro" 2>/dev/null || true
    if ( set -Eeuo pipefail; source "$LIB_DIR/state.sh" \
         && SERVERKIT_STATE_FILE="$ro/state.json" state_set k v ) 2>/dev/null; then
        ok "state_set exits 0 with an unwritable state directory"
    else
        bad "state_set ABORTED on an unwritable state directory (L1 regression)"
    fi
    chmod 755 "$ro" 2>/dev/null || true
else
    skip "state.sh warn-and-no-op contract — python3 unavailable here"
fi

# ==========================================================================
# lib/uninstall.sh — L2: a failing `state_list | tr` must not abort the whole
# uninstall; L3: failed rm/mkdir teardown steps warn and continue (_u_try);
# L8: telemetry curl is bounded with --max-time and skipped under --dry-run.
# ==========================================================================
t="$WORK/ucore"; mkdir -p "$t/bin" "$t/inst/scripts/lib"
# Hostile state fixture: state_list emits one port then FAILS mid-pipe —
# exactly the shape that used to kill the uninstall before it removed anything.
cat > "$t/inst/scripts/lib/state.sh" <<'HOSTILE_EOF'
state_get() { printf 'iptables'; }
state_list() { printf '80/tcp\n'; return 1; }
HOSTILE_EOF
printf 'firewall_close() { return 0; }\n' > "$t/inst/scripts/lib/firewall.sh"
# rm always fails (EBUSY/EROFS stand-in); docker/systemctl fail hermetically;
# curl logs its argv so the telemetry contract is observable.
make_stub_exit "$t/bin" 1 rm docker systemctl
CURL_LOG="$t/curl.log"; : > "$CURL_LOG"
cat > "$t/bin/curl" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> "$CURL_LOG"
exit 0
EOF
chmod +x "$t/bin/curl"

out="$(
    set -Eeuo pipefail
    source "$LIB_DIR/uninstall.sh"
    export PATH="$t/bin:$PATH"
    export SERVERKIT_DIR="$t/inst"
    serverkit_uninstall_core 2>&1
)"
rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qF 'Removing firewall rules we added (iptables): 80/tcp'; then
    ok "uninstall survives a state_list failing mid-pipe and still gets its firewall record (L2)"
else
    bad "uninstall rc=$rc or never reached the firewall step past the failing state_list: [$out]"
fi
if printf '%s' "$out" | grep -qF 'Step failed (continuing): rm' && \
   printf '%s' "$out" | grep -qF 'Preserved user data'; then
    ok "uninstall warns on every failed rm and continues to the last teardown step (L3/_u_try)"
else
    bad "uninstall did not warn-and-continue past failing rm steps (L3 regression): [$out]"
fi
if grep -q -- '--max-time 5' "$CURL_LOG"; then
    ok "telemetry curl is bounded with --max-time (no air-gapped hang) (L8)"
else
    bad "telemetry curl ran unbounded; curl saw: $(tr '\n' ';' < "$CURL_LOG")"
fi

: > "$CURL_LOG"
if (
    set -Eeuo pipefail
    source "$LIB_DIR/uninstall.sh" \
        && export PATH="$t/bin:$PATH" \
        && export SERVERKIT_DIR="$t/inst" SERVERKIT_UNINSTALL_DRY_RUN=1 \
        && serverkit_uninstall_core
) >/dev/null 2>&1 && [ ! -s "$CURL_LOG" ]; then
    ok "uninstall --dry-run never phones home (L8)"
else
    bad "uninstall --dry-run failed or still called curl: $(tr '\n' ';' < "$CURL_LOG")"
fi

# ==========================================================================
# root uninstall.sh — L4: a remnants-only box (no scripts/lib anywhere) must
# still be uninstallable via the inline fallback teardown, honoring --dry-run.
# ==========================================================================
t="$WORK/fallback"; mkdir -p "$t/remnants" "$t/remnants-a"
printf '1.2.3\n' > "$t/remnants/VERSION"
printf 'x\n' > "$t/remnants/leftover.txt"
cp "$ROOT_DIR/uninstall.sh" "$t/uninstall.sh"   # copied away from the repo so no scripts/lib is findable

out="$( cd "$t" && SERVERKIT_UNINSTALL_ALLOW_NONROOT=1 SERVERKIT_UNINSTALL_LOG="$t/un.log" \
        SERVERKIT_DIR="$t/remnants" bash ./uninstall.sh --dry-run --yes 2>&1 )"
rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qi 'fallback' && \
   printf '%s' "$out" | grep -qF "would run: rm -rf $t/remnants" && \
   [ -d "$t/remnants" ] && [ -d "$t/remnants-a" ]; then
    ok "root uninstall.sh with no lib announces the fallback; --dry-run changes nothing (L4)"
else
    bad "fallback dry-run rc=$rc, or it mutated the fixture: [$out]"
fi

out="$( cd "$t" && SERVERKIT_UNINSTALL_ALLOW_NONROOT=1 SERVERKIT_UNINSTALL_LOG="$t/un.log" \
        SERVERKIT_DIR="$t/remnants" bash ./uninstall.sh --yes 2>&1 )"
rc=$?
if [ "$rc" -eq 0 ] && [ ! -e "$t/remnants" ] && [ ! -e "$t/remnants-a" ]; then
    ok "root uninstall.sh fallback removes the remnants and exits 0 (L4)"
else
    bad "fallback teardown rc=$rc; remnants left: $(ls -d "$t"/remnants* 2>/dev/null | tr '\n' ' '): [$out]"
fi

# --------------------------------------------------------------------------
printf '\n%d passed, %d failed, %d skipped\n\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
