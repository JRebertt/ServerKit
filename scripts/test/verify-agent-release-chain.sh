#!/usr/bin/env bash
#
# Verify the agent enrollment chain against the REAL GitHub releases.
#
# Issue #101 had two breaks stacked on top of each other:
#
#   1. the panel image never shipped scripts/install.sh, so the enrollment URL
#      404'd (covered by scripts/test/smoke-docker-image.sh), and
#   2. the installer it would have served pointed at jhd3197/ServerKit and
#      `agent-v*` tags -- coordinates that stopped existing when the Go agent
#      moved to its own repo. Fixing (1) alone just moves the failure one step
#      later, into the download.
#
# Unit tests cannot see (2): they stub curl, so they only ever prove the script
# is self-consistent, never that the URL it builds resolves to a real file. This
# script asks GitHub. It needs network but no root, no Docker and no systemd.
#
# Usage:
#   bash scripts/test/verify-agent-release-chain.sh
#   bash scripts/test/verify-agent-release-chain.sh <panel-base-url>
#
# With a panel URL it checks the chain end to end, starting from the script the
# panel actually serves. Without one it checks the script in this checkout.

set -uo pipefail

PANEL_URL="${1:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  \033[32m✔\033[0m %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  \033[31m✘\033[0m %s\n' "$1"; }

printf '\nagent release chain\n\n'

# --------------------------------------------------------------------------
# 1. Get the installer -- from the panel if we were given one, else from disk.
# --------------------------------------------------------------------------
INSTALLER="$WORK/install.sh"
if [ -n "$PANEL_URL" ]; then
    url="${PANEL_URL%/}/api/v1/servers/install.sh"
    if curl -fsSL "$url" -o "$INSTALLER"; then
        ok "panel serves the installer at $url"
    else
        bad "panel did not serve $url (this is the #101 symptom)"
        printf '\n%d passed, %d failed\n\n' "$PASS" "$FAIL"
        exit 1
    fi
else
    cp "$REPO_ROOT/scripts/install.sh" "$INSTALLER"
    ok "using scripts/install.sh from this checkout"
fi

# --------------------------------------------------------------------------
# 2. Read the coordinates back out of the script itself, so we test what the
#    installer will really do rather than what we assume it does.
# --------------------------------------------------------------------------
REPO="$(grep -m1 '^GITHUB_REPO=' "$INSTALLER" | cut -d'"' -f2)"
if [ -n "$REPO" ]; then
    ok "installer targets repo: $REPO"
else
    bad "could not read GITHUB_REPO out of the installer"
    exit 1
fi

# --------------------------------------------------------------------------
# 3. Resolve a version the same way the installer does.
# --------------------------------------------------------------------------
releases="$WORK/releases.json"
if ! curl -fsSL "https://api.github.com/repos/${REPO}/releases?per_page=100&page=1" -o "$releases"; then
    bad "GitHub API unreachable for ${REPO} (rate limited? offline?)"
    printf '\n%d passed, %d failed\n\n' "$PASS" "$FAIL"
    exit 1
fi

VERSION="$(grep -o '"tag_name": *"v[0-9][^"]*"' "$releases" | head -1 | sed -e 's/.*"v//' -e 's/"$//')"
if [ -n "$VERSION" ]; then
    ok "resolved latest agent version: v${VERSION}"
else
    bad "no vX.Y.Z release found in ${REPO} — enrollment cannot resolve a version"
    printf '\n%d passed, %d failed\n\n' "$PASS" "$FAIL"
    exit 1
fi

# --------------------------------------------------------------------------
# 4. The URLs the installer builds must resolve to real assets. This is the
#    assertion that was missing: every unit test stubbed curl, so nothing ever
#    asked GitHub whether the download target existed.
# --------------------------------------------------------------------------
for arch in amd64 arm64; do
    asset="serverkit-agent-${VERSION}-linux-${arch}.tar.gz"
    url="https://github.com/${REPO}/releases/download/v${VERSION}/${asset}"
    code="$(curl -sSL -o /dev/null -w '%{http_code}' "$url")"
    if [ "$code" = "200" ]; then
        ok "linux-${arch} asset exists: ${asset}"
    else
        bad "HTTP ${code} for ${url}"
    fi
done

checksums_url="https://github.com/${REPO}/releases/download/v${VERSION}/checksums.txt"
if curl -fsSL "$checksums_url" -o "$WORK/checksums.txt"; then
    ok "checksums.txt published for v${VERSION}"
    if grep -q "serverkit-agent-${VERSION}-linux-amd64.tar.gz" "$WORK/checksums.txt"; then
        ok "checksums.txt names the asset the installer downloads"
    else
        bad "checksums.txt has no entry for serverkit-agent-${VERSION}-linux-amd64.tar.gz"
    fi
else
    bad "checksums.txt missing for v${VERSION} — installs proceed unverified"
fi

# --------------------------------------------------------------------------
# 5. Download for real and confirm the archive lays out the way the installer
#    expects. `mv ${TMP_DIR}/serverkit-agent-linux-${ARCH}` is a hard dependency
#    on the entry name inside the tarball.
# --------------------------------------------------------------------------
asset="serverkit-agent-${VERSION}-linux-amd64.tar.gz"
if curl -fsSL "https://github.com/${REPO}/releases/download/v${VERSION}/${asset}" \
        -o "$WORK/$asset"; then
    ok "downloaded ${asset}"

    if command -v sha256sum >/dev/null 2>&1 && [ -f "$WORK/checksums.txt" ]; then
        if (cd "$WORK" && sha256sum -c <(grep "$asset" checksums.txt) >/dev/null 2>&1); then
            ok "checksum verifies (the installer would accept this archive)"
        else
            bad "checksum MISMATCH — the installer would abort the install"
        fi
    fi

    expected="$(grep -o 'serverkit-agent-linux-\${ARCH}' "$INSTALLER" | head -1)"
    if tar -tzf "$WORK/$asset" | grep -qx "serverkit-agent-linux-amd64"; then
        ok "archive contains serverkit-agent-linux-amd64, the name the installer moves"
    else
        bad "archive layout changed; installer expects ${expected:-serverkit-agent-linux-<arch>}: $(tar -tzf "$WORK/$asset" | tr '\n' ' ')"
    fi
else
    bad "could not download ${asset} — enrollment would fail here"
fi

printf '\n%d passed, %d failed\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
