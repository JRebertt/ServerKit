# shellcheck shell=bash
#
# scripts/test/stubs.sh — shared PATH-stub factories for the shell test harness.
#
# Source this from a test suite, then call the factories to materialise
# executable stubs inside a per-test bin directory that gets PATH-prepended.
# Two families live here:
#
#   * generic:   make_stub_ok / make_stub_exit — the exit-0/exit-N one-liners
#                every suite used to re-implement inline.
#   * failing:   make_stub_systemctl_exit5, make_stub_docker_fail,
#                make_stub_docker_empty, make_stub_curl_fail22,
#                make_stub_curl_ratelimited, make_stub_sleep_noop — the
#                degenerate tool behaviours a fresh or broken box presents.
#
# make_fresh_box_fixture builds the EMPTIEST valid world a fresh ServerKit
# install presents to observation/discovery functions (zero apps, zero
# containers, no optional confs, dead network, empty state) — the exact state
# that killed the 2026-07-02 production update.
#
# Keep this file bash-3-portable and shellcheck-clean: CI runs
# `shellcheck --severity=error` and `bash -n` on scripts/test/*.sh across a
# 7-distro matrix.

# files_identical <a> <b> — byte-equality that works on minimal CI images:
# EL9/Fedora containers ship without diffutils (`cmp`), so fall back to a
# checksum compare (sha256sum is coreutils, present everywhere we run).
files_identical() {
    [ -f "$1" ] && [ -f "$2" ] || return 1
    if command -v cmp >/dev/null 2>&1; then
        cmp -s "$1" "$2"
    else
        [ "$(sha256sum < "$1")" = "$(sha256sum < "$2")" ]
    fi
}

# make_stub_exit <bindir> <code> <name...> — each <name> becomes a stub that
# ignores its arguments and exits <code>.
make_stub_exit() {
    local dir="$1" code="$2" name
    shift 2
    for name in "$@"; do
        printf '#!/usr/bin/env bash\nexit %s\n' "$code" > "$dir/$name"
        chmod +x "$dir/$name"
    done
}

# make_stub_stdout <bindir> <name> [exit-code] — a stub whose stdout is read
# from THIS function's stdin, ignoring whatever arguments it is called with.
#
# Firewall detection reads the *text* of `ufw status verbose` and
# `nft list ruleset` — "Status: active", "Default: deny (incoming)", a chain
# policy — so a canned transcript is the only faithful fixture for it. An
# exit-code stub cannot express "the tool ran fine and reported nothing", which
# is exactly the stock-cloud-image case that matters.
make_stub_stdout() {
    local dir="$1" name="$2" code="${3:-0}"
    {
        printf '#!/usr/bin/env bash\ncat <<%s\n' "'STUB_EOF'"
        cat
        printf 'STUB_EOF\nexit %s\n' "$code"
    } > "$dir/$name"
    chmod +x "$dir/$name"
}

# make_stub_ok <bindir> <name...> — happy no-op stubs (exit 0).
make_stub_ok() {
    local dir="$1"
    shift
    make_stub_exit "$dir" 0 "$@"
}

# systemctl on a box where the queried/stopped unit is not loaded: systemd
# answers with exit 5 ("unit not loaded") — what `systemctl stop serverkit`
# returns on a fresh install before the unit exists.
make_stub_systemctl_exit5() {
    make_stub_exit "$1" 5 systemctl
}

# docker present but broken/unreachable: every invocation fails (daemon down,
# permission denied, ...).
make_stub_docker_fail() {
    make_stub_exit "$1" 1 docker
}

# docker installed and the daemon healthy, but the box runs ZERO containers:
# `docker ps ...` prints nothing and succeeds; everything else (inspect, tag,
# cp, compose, ...) fails because nothing exists to operate on.
make_stub_docker_empty() {
    cat > "$1/docker" <<'DOCKER_EOF'
#!/usr/bin/env bash
case "${1:-}" in
    ps) exit 0 ;;
    *)  exit 1 ;;
esac
DOCKER_EOF
    chmod +x "$1/docker"
}

# curl with the network dead (or every URL 404ing under -f): exit 22, the code
# `curl -f` uses for HTTP errors and the shape `curl -sf` callers must survive.
make_stub_curl_fail22() {
    make_stub_exit "$1" 22 curl
}

# curl hitting the GitHub API's unauthenticated rate limit: HTTP 403 whose
# JSON error body is delivered with exit 0 (the no--f shape) — the nastiest
# case for code that greps tag_name out of whatever curl printed.
make_stub_curl_ratelimited() {
    cat > "$1/curl" <<'CURL_EOF'
#!/usr/bin/env bash
out=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        *)  shift ;;
    esac
done
body='{"message":"API rate limit exceeded for 203.0.113.7.","documentation_url":"https://docs.github.com/rest/overview/resources-in-the-rest-api#rate-limiting"}'
if [ -n "$out" ]; then printf '%s\n' "$body" > "$out"; else printf '%s\n' "$body"; fi
exit 0
CURL_EOF
    chmod +x "$1/curl"
}

# sleep that returns immediately — keeps retry/poll loops (quick_health,
# await_health) sub-second inside fixtures where the probe can never succeed.
make_stub_sleep_noop() {
    make_stub_exit "$1" 0 sleep
}

# pg_restore in TOC-listing mode (`pg_restore -l`), the archive check
# verify_pg_dump degrades to when the binary is present. MUST be stubbed:
# otherwise the assertion depends on the HOST. A runner with postgresql-client
# installed runs the real binary, which parses the version bytes after the
# PGDMP magic and rejects the suite's synthetic dumps; a runner without it
# skips the check entirely and accepts anything non-empty. Same fixtures, two
# verdicts. Here a dump is valid iff it carries the PGDMP magic.
make_stub_pg_restore() {
    cat > "$1/pg_restore" <<'PGR_EOF'
#!/usr/bin/env bash
dump=""
for arg in "$@"; do
    case "$arg" in -*) ;; *) dump="$arg" ;; esac
done
if [ -z "$dump" ] || [ ! -s "$dump" ]; then
    echo "pg_restore: error: could not open input file" >&2
    exit 1
fi
if [ "$(head -c 5 "$dump" 2>/dev/null)" != "PGDMP" ]; then
    echo "pg_restore: error: did not find magic string in file header" >&2
    exit 1
fi
printf ';\n; Archive created at 2026-01-01 00:00:00 UTC\n;\n'
exit 0
PGR_EOF
    chmod +x "$1/pg_restore"
}

# make_fresh_box_fixture <root> — lay out the degenerate fresh-box world:
#   <root>/bin                              PATH-prepend stubs: systemctl exit 5,
#                                           docker with zero containers, curl
#                                           exit 22, instant sleep
#   <root>/etc/nginx/serverkit-locations    EMPTY (zero managed apps — the
#                                           default state of every fresh install)
#   <root>/etc/nginx                        no serverkit.conf, no nginx.conf
#   <root>/etc/serverkit                    no ssl-mode / panel-domain, and an
#                                           EMPTY install-state.json
#   <root>/etc/os-release                   minimal Ubuntu-ish identity
#   <root>/opt                              exists, but /opt/serverkit does NOT
#   <root>/var/backups, <root>/var/log      empty
make_fresh_box_fixture() {
    local root="$1"
    mkdir -p "$root/bin" "$root/etc/nginx/serverkit-locations" \
             "$root/etc/serverkit" "$root/opt" "$root/var/backups" "$root/var/log"
    : > "$root/etc/serverkit/install-state.json"
    printf 'ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04 LTS"\n' \
        > "$root/etc/os-release"
    make_stub_systemctl_exit5 "$root/bin"
    make_stub_docker_empty    "$root/bin"
    make_stub_curl_fail22     "$root/bin"
    make_stub_sleep_noop      "$root/bin"
}
