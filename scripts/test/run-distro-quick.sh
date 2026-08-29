#!/usr/bin/env bash
# Syntax + source-level installer suites. This deliberately avoids systemd,
# nginx, Docker-in-Docker, and real host mutation; those belong to the VM and
# full-container harnesses.
set -uo pipefail

SOURCE_DIR="${SERVERKIT_SOURCE_DIR:-/src}"
cd "$SOURCE_DIR" || exit 2

fail=0
for file in serverkit install.sh uninstall.sh scripts/*.sh scripts/lib/*.sh scripts/test/*.sh; do
    [ -f "$file" ] || continue
    if bash -n "$file"; then
        printf 'ok   %s\n' "$file"
    else
        printf 'FAIL %s\n' "$file"
        fail=1
    fi
done

for suite in \
    test_update \
    test_install \
    test_lib \
    test_cli \
    test_agent_install \
    test_stage \
    test_release_workflow; do
    printf '=== %s ===\n' "$suite"
    bash "scripts/test/$suite.sh" || fail=1
done

if [ "$fail" -eq 0 ]; then
    printf 'QUICK_RESULT=PASS\n'
else
    printf 'QUICK_RESULT=FAIL\n'
fi
exit "$fail"
