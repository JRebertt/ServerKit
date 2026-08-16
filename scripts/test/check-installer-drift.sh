#!/usr/bin/env bash
#
# Fail if the vendored agent installers have drifted from their canonical copies
# in the agent repository.
#
# This is the guard for the second half of issue #101. The agent moved to its own
# repo and kept its own install.sh; the panel kept serving the copy under
# scripts/. Nothing compared them, so when one was fixed and the other was not,
# the panel went on handing every new server an installer that downloaded from
# `agent-v*` tags which exist in no repository. Both copies looked fine on their
# own -- that is the whole problem with two copies of one file.
#
# Unit tests cannot catch this: they exercise whichever copy is in their repo and
# have no idea the other exists. Only a cross-repo comparison can.
#
# Usage:
#   bash scripts/test/check-installer-drift.sh              # sibling checkout, else GitHub
#   bash scripts/test/check-installer-drift.sh <path|url>   # explicit canonical source
#
# Exits non-zero on drift, printing the diff.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_REPO="${SERVERKIT_AGENT_REPO:-jhd3197/serverkit-agent}"
AGENT_REF="${AGENT_REF:-}"
SOURCE="${1:-}"

INSTALLERS=(install.sh install.ps1)

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  \033[32m✔\033[0m %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  \033[31m✘\033[0m %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Ask the repo which branch is its default rather than hardcoding one. The agent
# repo was renamed master -> main; a hardcoded name turns any such rename into a
# 404 that reads as "cannot reach the canonical copy" rather than "wrong branch
# name", which is a genuinely confusing way to fail. AGENT_REF pins it (e.g. to a
# tag) when you want a specific revision.
resolve_agent_ref() {
    if [ -n "$AGENT_REF" ]; then printf '%s' "$AGENT_REF"; return 0; fi

    local declared ref
    declared="$(curl -fsSL "https://api.github.com/repos/${AGENT_REPO}" 2>/dev/null \
        | grep -o '"default_branch": *"[^"]*"' | head -1 | sed -e 's/.*: *"//' -e 's/"$//')"
    if [ -n "$declared" ]; then printf '%s' "$declared"; return 0; fi

    # API unreachable or rate-limited — probe the two plausible names.
    for ref in main master; do
        if curl -fsSL -o /dev/null \
                "https://raw.githubusercontent.com/${AGENT_REPO}/${ref}/install.sh" 2>/dev/null; then
            printf '%s' "$ref"; return 0
        fi
    done
    printf 'main'
}

if [ -z "$SOURCE" ]; then
    if [ -d "${REPO_ROOT}/../serverkit-agent" ]; then
        SOURCE="$(cd "${REPO_ROOT}/../serverkit-agent" && pwd)"
    else
        SOURCE="https://raw.githubusercontent.com/${AGENT_REPO}/$(resolve_agent_ref)"
    fi
fi

printf '\nagent installer drift check\n  canonical: %s\n  vendored:  %s/scripts\n\n' \
    "$SOURCE" "$REPO_ROOT"

for f in "${INSTALLERS[@]}"; do
    vendored="${REPO_ROOT}/scripts/${f}"
    canonical="${WORK}/${f}"

    if [ ! -f "$vendored" ]; then
        bad "${f} is missing from scripts/ — the panel serves this file"
        continue
    fi

    if [ -d "$SOURCE" ]; then
        if [ ! -f "${SOURCE}/${f}" ]; then
            bad "${f} not found in canonical source ${SOURCE}"
            continue
        fi
        cp "${SOURCE}/${f}" "$canonical"
    else
        if ! curl -fsSL "${SOURCE}/${f}" -o "$canonical"; then
            bad "could not fetch canonical ${f} from ${SOURCE}"
            continue
        fi
    fi

    # EOL-insensitive: this repo's .gitattributes checks *.ps1 out as CRLF while
    # the agent repo has no such rule, so a byte comparison would always fail on
    # install.ps1 for a reason that has nothing to do with drift.
    if diff -u <(tr -d '\r' < "$canonical") <(tr -d '\r' < "$vendored") \
            --label "canonical/${f}" --label "vendored/scripts/${f}" > "${WORK}/${f}.diff"; then
        ok "${f} matches the canonical copy"
    else
        bad "${f} has DRIFTED from the canonical copy in ${AGENT_REPO}"
        printf '\n'
        sed 's/^/      /' "${WORK}/${f}.diff" | head -60
        printf '\n      Fix: edit the agent repo, then run scripts/sync-agent-installers.sh\n\n'
    fi
done

printf '\n%d passed, %d failed\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
