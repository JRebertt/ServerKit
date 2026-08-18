#!/usr/bin/env bash
# probe-matrix.sh — run the plan 75 §D probe-honesty integration tests
# (backend/tests/test_probe_env_integration.py) across the install
# environments plan 74 could not verify on its single Ubuntu 22.04 root box:
#
#   ubuntu-root-sbinless  ubuntu:22.04, root, ufw+nginx, pytest run with
#                         PATH=/usr/local/bin:/usr/bin:/bin — the panel
#                         systemd unit's PATH shape (no sbin dirs).
#   ubuntu-nonroot-sudo   ubuntu:22.04, unprivileged user with passwordless
#                         sudo; _needs_sudo() is True and probes route
#                         through sudo's secure_path.
#   rocky-root            rockylinux:9, root, firewalld — different binary
#                         paths, package names, rpm/dnf instead of dpkg/apt.
#   ubuntu-capdrop        ubuntu:22.04, root, --cap-drop=NET_ADMIN (explicit;
#                         docker's default already drops it) — the
#                         unprivileged-LXC shape: ufw exists, resolves, and
#                         `ufw status` still fails on permissions.
#
# Usage:
#   scripts/test/probe-matrix.sh            # run all legs
#   scripts/test/probe-matrix.sh rocky      # run legs matching a substring
#   scripts/test/probe-matrix.sh --list     # list legs and exit
#
# The repo is mounted read-only at /src; each leg installs python3+pytest+the
# firewall package, then runs
#   python3 -m pytest tests/test_probe_env_integration.py -v
# from /src/backend. Prints a summary table; exits non-zero if any leg fails.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Git Bash on Windows mangles -v paths; hand docker a Windows-style source
# path and suppress MSYS path conversion for the docker invocation.
if command -v cygpath >/dev/null 2>&1; then
    MOUNT_SRC="$(cygpath -m "$REPO_ROOT")"
else
    MOUNT_SRC="$REPO_ROOT"
fi

PYTEST_CMD='cd /src/backend && PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_probe_env_integration.py -v -p no:cacheprovider'

# In-container setup+run script. Parameterized by env vars passed via
# docker -e: FW_PKGS (firewall packages to install), CREATE_USER (run pytest
# as this passwordless-sudo user instead of root), TEST_PATH (PATH override
# for the pytest invocation).
container_script() {
    cat <<'EOS'
set -e
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
    rm -rf /var/lib/apt/lists/*
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip $FW_PKGS
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q python3 python3-pip $FW_PKGS
elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip $FW_PKGS
fi
pip3 install --break-system-packages pytest 2>/dev/null || pip3 install pytest
if [ -n "$TEST_PATH" ]; then
    export PATH="$TEST_PATH"
fi
if [ -n "$CREATE_USER" ]; then
    useradd -m "$CREATE_USER"
    echo "$CREATE_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-probe-matrix
    chmod 440 /etc/sudoers.d/90-probe-matrix
    su "$CREATE_USER" -c "$PYTEST_CMD_INNER"
else
    eval "$PYTEST_CMD_INNER"
fi
EOS
}

# leg definitions: name|image|extra docker args|FW_PKGS|CREATE_USER|TEST_PATH
LEGS=(
    "ubuntu-root-sbinless|ubuntu:22.04||ufw nginx||/usr/local/bin:/usr/bin:/bin"
    "ubuntu-nonroot-sudo|ubuntu:22.04||ufw sudo|tester|"
    "rocky-root|rockylinux:9||firewalld||"
    "ubuntu-capdrop|ubuntu:22.04|--cap-drop=NET_ADMIN|ufw||"
)

if [ "${1:-}" = "--list" ]; then
    for leg in "${LEGS[@]}"; do echo "${leg%%|*}"; done
    exit 0
fi

FILTER="${1:-all}"

declare -a RESULT_NAMES=()
declare -a RESULT_STATUS=()

run_leg() {
    local name="$1" image="$2" extra_args="$3" fw_pkgs="$4" create_user="$5" test_path="$6"
    echo ""
    echo "======================================================================"
    echo " LEG: $name  (image: $image${extra_args:+, $extra_args})"
    echo "======================================================================"
    # extra_args is intentionally word-split (it is e.g. "--cap-drop=NET_ADMIN").
    # shellcheck disable=SC2086
    MSYS_NO_PATHCONV=1 docker run --rm -i \
        $extra_args \
        -v "$MOUNT_SRC:/src:ro" \
        -e FW_PKGS="$fw_pkgs" \
        -e CREATE_USER="$create_user" \
        -e TEST_PATH="$test_path" \
        -e PYTEST_CMD_INNER="$PYTEST_CMD" \
        "$image" bash -s < <(container_script)
    local rc=$?
    RESULT_NAMES+=("$name")
    if [ $rc -eq 0 ]; then
        RESULT_STATUS+=("PASS")
    else
        RESULT_STATUS+=("FAIL (rc=$rc)")
    fi
}

for leg in "${LEGS[@]}"; do
    IFS='|' read -r name image extra_args fw_pkgs create_user test_path <<< "$leg"
    if [ "$FILTER" != "all" ] && [[ "$name" != *"$FILTER"* ]]; then
        continue
    fi
    run_leg "$name" "$image" "$extra_args" "$fw_pkgs" "$create_user" "$test_path"
done

if [ ${#RESULT_NAMES[@]} -eq 0 ]; then
    echo "No legs matched filter '$FILTER'. Available:"
    for leg in "${LEGS[@]}"; do echo "  ${leg%%|*}"; done
    exit 2
fi

echo ""
echo "======================================================================"
echo " PROBE MATRIX SUMMARY"
echo "======================================================================"
printf ' %-24s %s\n' "LEG" "RESULT"
printf ' %-24s %s\n' "------------------------" "------------"
failures=0
for i in "${!RESULT_NAMES[@]}"; do
    printf ' %-24s %s\n' "${RESULT_NAMES[$i]}" "${RESULT_STATUS[$i]}"
    [[ "${RESULT_STATUS[$i]}" == PASS* ]] || failures=$((failures + 1))
done
echo "======================================================================"
if [ $failures -gt 0 ]; then
    echo " $failures leg(s) FAILED"
    exit 1
fi
echo " all legs passed"
exit 0
