#!/usr/bin/env bash
#
# Smoke-test a BUILT ServerKit image.
#
# This is the check that issue #101 needed and nobody had. Everything the panel
# reads off its own filesystem at request time -- installers, the SPA bundle,
# the VERSION file -- exists in the source tree, so the whole pytest suite passes
# while the shipped image is missing the file. The only way to catch that class
# of bug is to boot the artifact you are about to publish and ask it for the
# things it promises to serve.
#
# Usage:
#   bash scripts/test/smoke-docker-image.sh                  # builds serverkit:smoke, then tests
#   bash scripts/test/smoke-docker-image.sh <image[:tag]>     # tests an image you already have
#   SKIP_BUILD=1 bash scripts/test/smoke-docker-image.sh      # reuse the existing serverkit:smoke
#
# Exits non-zero on the first failed assertion, with the response that failed.

set -uo pipefail

IMAGE="${1:-serverkit:smoke}"
PORT="${SMOKE_PORT:-45990}"
CONTAINER="serverkit-smoke-$$"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  \033[32m✔\033[0m %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  \033[31m✘\033[0m %s\n' "$1"; }

cleanup() {
    if [ -n "${CONTAINER:-}" ] && docker inspect "$CONTAINER" >/dev/null 2>&1; then
        printf '\n--- container logs (tail) ---\n'
        docker logs --tail 40 "$CONTAINER" 2>&1 || true
        docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------
# Build (unless we were handed an image or told to skip)
# --------------------------------------------------------------------------
if [ -z "${SKIP_BUILD:-}" ] && [ "$IMAGE" = "serverkit:smoke" ]; then
    printf '\nBuilding %s (this is the slow part)...\n' "$IMAGE"
    if ! docker build -t "$IMAGE" "$REPO_ROOT"; then
        printf '\n\033[31mimage build failed\033[0m\n'
        exit 1
    fi
fi

printf '\nServerKit image smoke test — %s\n\n' "$IMAGE"

# --------------------------------------------------------------------------
# Filesystem assertions: cheap, and they name the missing path directly rather
# than making you infer it from an HTTP status.
# --------------------------------------------------------------------------
for f in /app/scripts/install.sh /app/scripts/install.ps1 /app/VERSION \
         /app/frontend/dist/index.html; do
    if docker run --rm --entrypoint sh "$IMAGE" -c "test -f $f" 2>/dev/null; then
        ok "image contains $f"
    else
        bad "image is MISSING $f — it will be requested at runtime"
    fi
done

# --------------------------------------------------------------------------
# Boot it
# --------------------------------------------------------------------------
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
if ! docker run -d --name "$CONTAINER" -p "${PORT}:5000" \
        -e SECRET_KEY=smoke-secret \
        -e JWT_SECRET_KEY=smoke-jwt \
        "$IMAGE" >/dev/null; then
    bad "container failed to start"
    exit 1
fi

BASE="http://127.0.0.1:${PORT}"
printf '  waiting for %s/api/v1/system/health ...\n' "$BASE"
ready=""
for _ in $(seq 1 90); do
    if curl -fsS -o /dev/null "${BASE}/api/v1/system/health" 2>/dev/null; then
        ready=1
        break
    fi
    # A container that has already exited will never become ready.
    if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" != "true" ]; then
        bad "container exited during boot"
        exit 1
    fi
    sleep 2
done

if [ -n "$ready" ]; then
    ok "panel boots and answers /api/v1/system/health"
else
    bad "panel never became healthy"
    exit 1
fi

# --------------------------------------------------------------------------
# HTTP assertions: every route that serves a file off the panel's own disk.
# --------------------------------------------------------------------------
assert_http() {
    local path="$1" want="$2" desc="$3"
    local code
    code="$(curl -s -o /tmp/smoke-body.$$ -w '%{http_code}' "${BASE}${path}")"
    if [ "$code" = "$want" ]; then
        ok "$desc"
    else
        bad "$desc — got HTTP $code, want $want: $(head -c 200 /tmp/smoke-body.$$)"
    fi
    rm -f /tmp/smoke-body.$$
}

assert_body() {
    local path="$1" needle="$2" desc="$3"
    if curl -fsS "${BASE}${path}" 2>/dev/null | grep -q -- "$needle"; then
        ok "$desc"
    else
        bad "$desc — '$needle' not found in the response body"
    fi
}

# The exact request from issue #101.
assert_http /api/v1/servers/install.sh  200 "GET /api/v1/servers/install.sh serves the agent installer"
assert_http /api/v1/servers/install.ps1 200 "GET /api/v1/servers/install.ps1 serves the Windows installer"
assert_http /                           200 "GET / serves the SPA"

assert_body /api/v1/servers/install.sh '#!/bin/bash' \
    "the served install.sh is a real bash script"
# Placeholder substitution runs against the served copy; if it silently stopped
# working the box would try to enroll against a nonexistent domain.
if curl -fsS "${BASE}/api/v1/servers/install.sh" | grep -q 'your-serverkit.com'; then
    bad "served install.sh still contains the your-serverkit.com placeholder"
else
    ok "served install.sh has this panel's URL substituted in"
fi
assert_body /api/v1/servers/install.sh 'jhd3197/serverkit-agent' \
    "the served install.sh downloads from the agent release repo"
assert_body /api/v1/servers/install.ps1 'Install-ServerKitAgent' \
    "the served install.ps1 is a real PowerShell installer"

printf '\n%d passed, %d failed\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
