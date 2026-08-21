#!/usr/bin/env bash
# Static regression guard for the feature -> dev -> main release path.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASE="$ROOT/.github/workflows/release.yml"
PROMOTION="$ROOT/.github/workflows/main-promotion.yml"
failures=0

expect_text() {
    file="$1"
    text="$2"
    label="$3"
    if grep -Fq -- "$text" "$file"; then
        printf 'ok   %s\n' "$label"
    else
        printf 'FAIL %s\n' "$label" >&2
        failures=$((failures + 1))
    fi
}

expect_absent() {
    file="$1"
    text="$2"
    label="$3"
    if grep -Fq -- "$text" "$file"; then
        printf 'FAIL %s\n' "$label" >&2
        failures=$((failures + 1))
    else
        printf 'ok   %s\n' "$label"
    fi
}

expect_text "$PROMOTION" 'branches: [main]' \
    'main promotion runs on pull requests targeting main'
expect_text "$PROMOTION" 'ready_for_review, edited]' \
    'main promotion reruns when a pull request is retargeted'
expect_text "$PROMOTION" 'HEAD_BRANCH: ${{ github.head_ref }}' \
    'main promotion reads the pull request head branch safely'
expect_text "$PROMOTION" '[ "$HEAD_BRANCH" != "dev" ]' \
    'main promotion rejects heads other than dev'
expect_text "$PROMOTION" '[ "$HEAD_REPOSITORY" != "$REPOSITORY" ]' \
    'main promotion rejects a fork branch named dev'

expect_text "$RELEASE" 'name: Verify dev promotion' \
    'release verifies the merged promotion'
expect_absent "$RELEASE" 'workflow_dispatch:' \
    'manual dispatch cannot bypass the dev promotion path'
expect_absent "$RELEASE" "      - 'v*'" \
    'tag pushes cannot bypass the dev promotion path'
expect_text "$RELEASE" 'listPullRequestsAssociatedWithCommit' \
    'release resolves the pull request associated with the main commit'
expect_text "$RELEASE" "pull.head.ref === 'dev'" \
    'release only accepts a merged dev head'
expect_text "$RELEASE" 'name: Require an unused release version' \
    'release checks version immutability before tagging'
expect_text "$RELEASE" 'Refusing to overwrite existing tag' \
    'release fails instead of reusing an existing tag'
expect_text "$RELEASE" 'Refusing to overwrite existing release' \
    'release fails instead of reusing an existing release'
expect_text "$RELEASE" 'overwrite_files: false' \
    'release assets cannot be overwritten'

if [ "$failures" -ne 0 ]; then
    printf '\n%d release workflow guard assertion(s) failed\n' "$failures" >&2
    exit 1
fi

printf '\nrelease workflow guards are intact\n'
