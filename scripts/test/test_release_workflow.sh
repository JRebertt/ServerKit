#!/usr/bin/env bash
# Static regression guard for the feature -> dev -> main release path.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASE="$ROOT/.github/workflows/release.yml"
PROMOTION="$ROOT/.github/workflows/main-promotion.yml"
VERSION_BUMP="$ROOT/.github/workflows/version-bump.yml"
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

expect_text "$VERSION_BUMP" 'name: Wait for sibling CI before advancing dev' \
    'version bump waits for the checks on the triggering commit'
expect_text "$VERSION_BUMP" '.workflowName != "Version Bump"' \
    'version bump excludes its own in-progress run from the sibling gate'
expect_text "$VERSION_BUMP" 'statuses: write' \
    'version bump may preserve the required status on its generated commit'
expect_text "$VERSION_BUMP" "-f context='Require dev source'" \
    'generated version commit receives the protected promotion context'
expect_text "$VERSION_BUMP" '-f head="$owner:dev"' \
    'promotion status requires an open same-repository dev head'

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

# The release tarball must be able to rebuild its own frontend: build-release
# used to strip every png outside frontend/dist, which emptied
# frontend/src/assets and made any rebuild from /opt/serverkit die on
# unresolved imports (issue #127).
BUILD_RELEASE="$ROOT/scripts/build-release.sh"
expect_text "$BUILD_RELEASE" '! -path "$BUILD_DIR/frontend/*"' \
    'release image cleanup leaves the whole frontend/ tree alone'
expect_absent "$BUILD_RELEASE" '! -path "$BUILD_DIR/frontend/dist/*" -delete' \
    'release image cleanup no longer strips frontend/src assets'

if [ "$failures" -ne 0 ]; then
    printf '\n%d release workflow guard assertion(s) failed\n' "$failures" >&2
    exit 1
fi

printf '\nrelease workflow guards are intact\n'
