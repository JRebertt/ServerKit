# ServerKit Agent Subsystem — Security & Completeness Audit

> **Migration note:** The Go agent source code has moved to its own repository at
> [`github.com/jhd3197/serverkit-agent`](https://github.com/jhd3197/serverkit-agent).
> This audit remains historically accurate but the file paths it references under
> `agent/` no longer exist in the ServerKit monorepo.

**Date:** 2026-06-12
**Scope:** The multi-server agent fleet end-to-end — Go agent (`agent/`), panel
gateway/registry/long-poll (`backend/app/agent_gateway.py`,
`services/agent_registry.py`, `api/agent_poll.py`), pairing/enrollment, the
panel→agent command APIs (`api/servers.py`, `fleet.py`, `agent_plugins.py`),
install/packaging, the fleet UI, and docs/CI.
**Method:** Direct read of the security-critical paths plus four parallel
breadth scans. Every load-bearing finding below was verified in source; one
widely-reported claim (committed MSI bloat) was checked and **rejected** as a
false positive (see Appendix B).

---

## TL;DR

The agent's **core security primitives are genuinely well built** — HMAC+nonce
replay protection on both transports, fail-closed signature verification on the
panel, symlink-resolved file allowlisting, shell-metacharacter rejection on
every command validator, exec/terminal gated off by default, a localhost-bound
IPC API with a constant-time bearer check, and a solid pairing flow
(Ed25519 proof-of-possession, lockout, one-shot credential delivery).

The problems are concentrated in **three areas**:

1. **The self-update path is the weakest link** and bypasses every other
   control — no code-signing, and checksum verification is optional and
   fail-open. Whoever can send a command to an agent can run code as root on it,
   even with exec and package management disabled.
2. **An entire advertised feature surface is non-functional** — the Agent Plugin
   system and Server Template drift/remediation call a panel function that does
   not exist, and the agent has no handlers for them. The API, DB, and UI imply
   a working sandboxed-plugin capability that silently does nothing.
3. **Authorization is thinner at the edges than in the core** — the Socket.IO
   layer has no per-object/role checks, and a few state-changing endpoints are
   under-gated.

No agent code is exercised by CI.

Severity counts: **3 High, 5 Medium, 7 Low/Informational.**

---

## Remediation status (2026-06-12)

- **M1 — fixed.** `sockets.py` now resolves the JWT to a live, active user at
  connect and records the role; `subscribe_terminal` and the generic
  `join_room` (for `_terminal:` rooms) require admin/developer, matching the
  REST `@developer_required` on terminal creation. Job/cloudflared streaming is
  unaffected.
- **M2 — corrected + hardened.** The compose half was a **false alarm**: every
  compose handler already runs the symlink-resolved AllowedPaths check
  (`a.validateFileAccess`) before calling the docker client (see the corrected
  M2 entry below). Added a doc-contract comment on `validateProjectPath` so a
  future caller can't bypass it. Cron is intentionally **not** AllowedPaths-
  restricted (that would break legitimate jobs like `/usr/bin/certbot renew`);
  its blast radius is addressed by M3 instead.
- **M4 — fixed.** Added `.github/workflows/agent-ci.yml` (go vet + go test +
  cross-compile build matrix for linux amd64/arm64 and windows/amd64 — darwin
  excluded because the tray dep can't cross-compile from Linux) and
  `backend-ci.yml` (full pytest suite). Also added
  `backend/tests/test_agent_poll_e2e.py`, an end-to-end test that drives the
  real panel↔agent command loop (HMAC auth → register → queue → poll → result →
  the synchronous waiter resolves) over the poll transport, which shares the
  WebSocket path's auth/registry/routing code. This is the "prove it actually
  works" net the subsystem lacked.
- **M5 — fixed.** The `register` command now reads the token (and
  connection-string / server URL) from the environment
  (`SERVERKIT_REGISTRATION_TOKEN`, etc.) when the flags aren't given, so the
  installers pass the token via env instead of argv — env is owner/root-only
  (`/proc/<pid>/environ`), whereas argv is world-readable (`ps`,
  `/proc/<pid>/cmdline`). `install.sh` (env-passed register, `eval` removed) and
  `install.ps1` (token via env, made optional) updated accordingly, and both
  accept the token from the environment so it need not appear in the
  `curl | bash -s -- --token …` line / shell history. Verified: the agent reads
  the env token at runtime, both scripts pass syntax checks.
- **M3 — fixed.** The DEB/RPM units now run as the dedicated unprivileged
  `serverkit-agent` account with the same hardening as `install.sh`
  (`NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`,
  `PrivateTmp=yes`). **Tradeoff:** packaged agents now match the script
  installer's capability set — Docker + metrics + file access — and no longer
  do systemd/package management or agent self-update by default (both need
  root). Self-update being disabled also blunts H1 for packaged installs:
  updates flow through the OS package manager's signed path. To keep
  system-management by default, run as root deliberately (revert `User=` in the
  build scripts) or configure passwordless sudo for the account.

### Highs

- **H1 — fixed (verification side).** `updater.go` now fails closed: an update
  with no checksums URL is refused; `matchChecksum` errors when no entry matches
  this platform (was a silent skip); the checksums fetch checks HTTP status; and
  `requireSecureURL` rejects non-HTTPS update/checksum URLs (dev override via
  `SERVERKIT_INSECURE_TLS`). Covered by `internal/updater/updater_test.go`
  (6 tests). **Still recommended:** cryptographic release signing
  (minisign/cosign) with a public key pinned in the agent — that needs the
  project's signing key + a release-pipeline change, so it's the remaining H1
  step. (Packaged installs are already protected: non-root agents can't
  self-update, so updates go through the OS package manager.)
- **H2 — fixed (made honest).** Removed the dead `get_agent_gateway()` calls in
  `agent_plugin_service.py` and `server_template_service.py`. Plugin install now
  reports `STATUS_ERROR` ("Agent-side plugin support is not implemented yet")
  instead of hanging in `installing`; template drift-check/remediate report
  `unknown` + an explanatory `drift_report.error`; local-only ops (disable,
  uninstall, configure) just drop the dead dispatch. Covered by
  `tests/test_agent_features_honest.py` (3 tests). Implementing the feature for
  real (agent handlers + sandbox) remains future work, but it no longer lies.
- **H3 — fixed** (earlier this session): `POST /<id>/agent/update` is now
  `@developer_required`; test in `tests/test_agent_update_authz.py`.

### Lows

- **L1 — fixed.** Pairing `/claim` and `/lookup` now require developer role
  (`tests/test_pairing_authz.py`), matching `POST /servers`.
- **L2 — documented.** `SECURITY.md` now states explicitly that `agent.key`
  encryption is off-host/tamper protection, not confidentiality against local
  root, and that the `0600` perms are the real control.
- **L3 — fixed.** Removed the dead "Add Version" / per-row Edit / Delete buttons
  from `AgentFleet.jsx` (no backend edit/delete route exists); version list
  intact, unused imports cleaned, no new lint errors.
- **L4 — accepted (by design).** Capabilities are OR-merged and not cleared
  until restart on purpose, to avoid feature flicker from transient probe
  failures; reverting would reintroduce that bug.
- **L5 — accepted (documented).** The single-worker requirement is stated in
  `SECURITY.md`/`ARCHITECTURE.md`/`CLAUDE.md` and enforced by `run.py`'s
  `-w 1`; reliable in-process detection of a multi-worker misconfig isn't
  practical, so it stays a documented operational constraint.
- **L6 — accepted (low).** The Windows updater builds a `.bat` via `fmt.Sprintf`
  with local, non-attacker-controlled paths; not worth the churn.
- **L7 — clarified.** The `verify_agent_auth` "TODO" is reworded to an accepted
  limitation (per-message token validation is defence-in-depth, not a bug; the
  channel is TLS-authenticated and connect is HMAC+nonce verified).

---

## HIGH

### H1 — Agent self-update has no code-signing and checksum verification is fail-open (supply-chain RCE)

The update path is the single highest-leverage hardening target because it runs
**as the agent process itself (root on packaged installs)** and is reachable
even when `Features.Exec=false` and package handlers are unavailable — it
bypasses every other feature gate.

Three independent weaknesses in `agent/internal/updater/updater.go`:

- **Checksum is optional.** `DownloadUpdate` only verifies when a URL is present:
  ```go
  // updater.go:167
  if info.ChecksumsURL != "" {
      if err := u.verifyChecksum(ctx, archivePath, info.ChecksumsURL); err != nil { ... }
  }
  ```
  Empty `checksums_url` → install with **no** verification.
- **Verification is fail-open.** When no checksum line matches the file, it
  logs a warning and returns success:
  ```go
  // updater.go:367-370
  if expectedHash == "" {
      u.log.Warn("Could not find checksum for downloaded file, skipping verification")
      return nil
  }
  ```
- **The checksum fetch ignores HTTP status** (`updater.go:316-320`). A 404 HTML
  body parses into an empty map → `expectedHash == ""` → skipped.

Even when it runs, the checksum file is fetched over the **same channel** as the
binary with **no signature** (no GPG/cosign/minisign), so anyone who can swap
the binary can swap the checksums to match. The download URL is **fully
attacker-controlled** — `handleAgentUpdate` takes it straight from the command:

```go
// agent/internal/agent/agent.go:1755-1785
var p struct { Version, DownloadURL, ChecksumsURL string; Force bool }
...
err := u.UpdateTo(context.Background(), p.Version, p.DownloadURL, p.ChecksumsURL)
```

(The stale comment at `agent.go:1781-1783` — "In a real implementation, we would
use the provided URLs … For now, we'll let the updater handle it" — contradicts
the code, which already uses them.)

**Blast radius:** A compromised or malicious panel, or an on-path attacker when
`SERVERKIT_INSECURE_TLS=true`, installs an arbitrary binary as root on every
connected server. The checksum gives a false sense of integrity.

**Fix:** Sign release archives (minisign/cosign), pin the public key in the
agent binary, and verify the signature over the binary **before** install. Make
checksum verification mandatory and fail-closed. Constrain `download_url` to the
expected panel/GitHub origin. Check the HTTP status on the checksum fetch.

---

### H2 — Agent Plugin system & Server Template remediation are non-functional stubs (missing function + missing handlers)

Two backend services dispatch agent commands through a helper that **does not
exist anywhere in the codebase**:

```python
# agent_plugin_service.py:159,189,218,254  and  server_template_service.py:324,366
from app.agent_gateway import get_agent_gateway   # ← no such symbol
gw = get_agent_gateway()
gw.send_command(server.agent_id, 'plugin_install', {...})
```

`agent_gateway.py` exports `init_agent_gateway` and `AgentNamespace` — there is
no `get_agent_gateway`. Every call raises `ImportError`, which is swallowed by a
bare `except Exception` and logged as a warning. Compounding it:

- The agent registers **no** `plugin_install` / `plugin_uninstall` /
  `plugin_configure` / `plugin_disable` / `config_drift_check` /
  `config_remediate` handlers (grep: zero matches in `agent/`).
- The call passes `server.agent_id` where the real `agent_registry.send_command`
  expects `server_id` — wrong argument even if the symbol existed.

**Effect:** Plugin install/uninstall/configure and template drift-check/remediate
are silent no-ops; DB rows are set to `STATUS_INSTALLING` / `CHECKING` /
`REMEDIATING` and **never progress**. Yet the API (`api/agent_plugins.py`), the
models, the marketplace `ai`/plugin category, and the AgentFleet UI
(install + bulk-install buttons) all present this as a working,
permission-scoped (`filesystem`/`network`/`docker`/`process`/`system`) sandboxed
capability. It is entirely hollow below the API layer.

**Fix:** Either implement the panel glue + agent handlers + sandbox, or remove
the UI/API and mark the feature explicitly "planned." At minimum, surface the
failure to the user instead of swallowing it, and stop stranding DB rows in a
pending state.

---

### H3 — `trigger_agent_update` lets any authenticated user (including read-only viewers) update/restart the fleet

```python
# backend/app/api/servers.py:2116-2117
@servers_bp.route('/<server_id>/agent/update', methods=['POST'])
@jwt_required()                       # ← no @developer_required / @admin_required
def trigger_agent_update(server_id):
```

Every other state-changing server route is `@developer_required` or
`@admin_required`; this one is authentication-only. A `viewer` (the explicit
read-only role) can force agent binary updates and the consequent restarts
across every server. In this endpoint the URL is panel-derived from GitHub
(so not arbitrary-binary RCE on its own), but it is an unintended privileged
action for a read-only account and an availability lever over the whole fleet.

**Fix:** Gate behind `@developer_required` (or `@admin_required`, matching
`/fleet/*`).

---

## MEDIUM

### M1 — Socket.IO layer has no authorization beyond "the JWT decodes"

`backend/app/sockets.py` authenticates the connection but performs **no role or
object-level checks** thereafter:

- **Connect only decodes the token** — no `is_active`, no role
  (`sockets.py:49-58`). A deactivated user keeps socket access until JWT expiry.
- **Generic `join_room` joins any room by name** (`sockets.py:199-205`):
  ```python
  @socketio.on('join_room')
  def handle_join_room(data):
      room = data.get('room')
      if room:
          join_room(room)        # no check that the caller may see this room
  ```
  Room names are discoverable (`server_<id>_metrics`, `logs_<app_id>`,
  `build_<app_id>`; server IDs come straight from `GET /servers`).
- **`subscribe_terminal` doesn't gate on role/ownership** (`sockets.py:120-144`)
  — any authenticated socket (including a `viewer`) can join a remote terminal's
  output room given the session id, even though *creating* a terminal is
  `@developer_required`. Output can include a root shell's contents.

Bounded today by role homogeneity and unguessable session UUIDs, but it's a
defense-in-depth gap inconsistent with the REST authz and a real cross-role
information-exposure path. **Fix:** validate room ownership/required role inside
the join/subscribe handlers; re-check `is_active`+role at connect; restrict
terminal subscription to the role that can create one.

### M2 — Compose path allowlisting (compose already enforced; cron intentionally not) — CORRECTED

The original finding overstated this. On closer review the **compose half was
already mitigated**: every compose handler in `internal/agent/agent.go`
(`handleDockerComposePs/Up/Down/Logs/Restart/Pull`, lines 1285/1300/1333/1361/
1388/1415) calls `a.validateFileAccess(p.ProjectPath)` — the same
symlink-resolved `AllowedPaths` allowlist used by `file:read/write/list` — and
that is the **only** call path to the docker client's `Compose*` methods. The
weaker `validateProjectPath` in `docker/client.go` is reached only *after* that
check passes, so it isn't a vulnerability; it was just inspected in isolation.
A doc-contract comment was added there so a future caller can't mistake it for
the allowlist boundary.

**Cron** (`cron/cron_linux.go validateCommand`) requires an absolute path and
rejects shell metacharacters but is **deliberately not** restricted to
`AllowedPaths` — doing so would break legitimate jobs (`/usr/bin/certbot
renew`, `/usr/bin/apt …`). Its real risk is "runs as whatever the agent runs
as," which M3 addresses by moving packaged agents off root (cron entries then
land in the unprivileged account's crontab, limiting blast radius).

### M3 — Packaged DEB/RPM run the agent as root with hardening disabled, contradicting install.sh

`agent/packaging/deb/build.sh` and `rpm/build.sh` ship a unit with `User=root`
and `NoNewPrivileges=false`, while `agent/scripts/install.sh` lays down a
dedicated `serverkit-agent` user with `NoNewPrivileges=yes`,
`ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`. The packaged path is
both inconsistent and maximizes the H1 update-RCE blast radius (root, no
privilege containment). **Fix:** align the packaged units with the hardened
install.sh posture, or document why root is required and tighten the sandbox
directives.

### M4 — No CI runs agent Go tests, `go vet`, or any Go SAST

`.github/workflows/agent-release.yml` only builds. `security-scan.yml` is
Python/Bandit over `backend/**`; nothing runs `go test`/`go vet`. Five agent
test files exist and cover the most security-sensitive logic
(`security_test.go` — command-blocking, exec-timeout, file-access allowlist &
symlink escape; `file_handlers_test.go`; `connstring_test.go`;
`ipc/auth_test.go`; `jobs/jobs_test.go`) but **never run in CI**, so a
regression in path-allowlisting or exec-blocking would ship unverified.
**Fix:** add a workflow running `go vet ./...` + `go test ./...` (and ideally
`govulncheck`/`golangci-lint`) on PRs touching `agent/`.

### M5 — Install flow exposes the registration token in the process table / shell history

`agent/scripts/install.sh` passes the token as a CLI argument to
`serverkit-agent register --token "$TOKEN"` (visible in `ps` during
registration), and the documented `curl … | sudo bash -s -- --token sk_reg_…`
one-liner lands the token in shell history. Tokens are single-use and
short-TTL, which limits exposure, but a captured token is usable until consumed.
**Fix:** accept the token via env var or stdin; note `HISTFILE` hygiene in the
docs.

---

## LOW / Informational

- **L1 — Pairing claim and a few reads are authentication-only.**
  `pairing.py` `/claim` and `/lookup` are `@jwt_required()` (not
  `@developer_required`), so a viewer who has the physically-displayed pair code
  + passphrase can enroll a server. Minor authz-consistency item; the two-factor
  physical secret is the real gate.
- **L2 — `agent.key` "encryption" is host-derived obfuscation, not a secret.**
  `config.go:380-396` derives the AES-GCM key from `hostname + machine-id` /
  `COMPUTERNAME` — values available to anything on the host. Real protection is
  the `0600` perms; the encryption only resists off-host exfil (e.g. a leaked
  backup). Worth documenting as such so it isn't mistaken for at-rest secrecy
  against local root.
- **L3 — Dead/placeholder UI.** `AgentFleet.jsx` version-table Edit/Delete and
  "Add Version" buttons have no handlers; `Terminal.jsx` shows "isn't available
  yet" for remote log/journal/process listing (feature-gated, not implemented).
  Honest placeholders, but they read as working controls.
- **L4 — Capabilities are OR-merged and never cleared until restart**
  (`recapabilities.go`). An agent that briefly saw Docker advertises `docker=true`
  for the rest of its run even if Docker goes away — intentional, but can mislead
  the target picker.
- **L5 — Single-worker requirement is enforced only by convention.** The
  registry, nonce store, and anomaly service are per-process in-memory
  singletons; running the panel with `-w >1` silently misroutes commands and
  desyncs nonces/rooms. Documented in CLAUDE.md/SECURITY.md but nothing fails
  loudly at runtime if misconfigured.
- **L6 — Windows update writes a `.bat` via `fmt.Sprintf` with binary paths**
  (`updater.go:254-261`). Local-only and not attacker-influenced today; would
  break on paths containing quotes. Low risk.
- **L7 — Stale TODO in `verify_agent_auth`** (`agent_registry.py:846`):
  per-message session-token validation is noted as unimplemented. The session
  token is issued but not verified per message; auth currently rests on the
  TLS channel + initial HMAC. Acceptable given the model; track it.

---

## What's done well (don't "fix" these)

- **Agent auth** signs `agent_id:timestamp:nonce` with a fresh random nonce on
  **both** WS (`ws/client.go:287`) and poll (`poll/client.go:173`) transports;
  the panel verifies HMAC **before** consuming the nonce and **fails closed** when
  the secret is missing/undecryptable (`agent_registry.py:789-851`), with a 60 s
  skew window and per-IP rate limiting shared across both transports.
- **TLS verification is on by default**; `InsecureSkipVerify` is uniformly
  env-gated (`SERVERKIT_INSECURE_TLS`) across all five dial sites and logged
  loudly at startup.
- **File access** is symlink-resolved against an allowlist, denies all when
  unconfigured, masks SUID/SGID/sticky on write, and re-validates parents for
  `create_dirs` (`file_handlers.go`).
- **Command validators** reject shell metacharacters for packages, systemd
  units, container/image/volume/network names, cron specs, and tunnel
  names; container create bans `privileged`/`cap_add`/`devices`; exec requires
  an absolute path + blocklist check; output is bounded; jobs are capped.
- **exec and terminal are off by default** — `system:exec` isn't registered
  unless `Features.Exec`, and the terminal manager is only constructed when
  `Features.Exec` is true (`agent.go:133`), so the terminal isn't an exec bypass.
- **Local IPC** binds to localhost (forced), requires a `0600` bearer token with
  a constant-time compare, and exempts only `/health` (`ipc/server.go`).
- **Pairing** uses Ed25519 proof-of-possession over the enrollment id,
  per-agent lockout with exponential backoff, bcrypt-hashed passphrase, code
  TTL/rotation/freeze, and one-shot encrypted credential delivery
  (`pairing_service.py`).
- **Registry reconnect/heartbeat handling** re-validates socket identity before
  eviction and fails in-flight commands on reconnect — the subtle races are
  handled.

---

## Recommended priority order

1. **H1** — sign agent releases + make update verification mandatory/fail-closed
   (highest leverage; neutralizes the one RCE primitive that bypasses every gate).
2. **H2** — implement or remove the Plugin/Template features; stop swallowing the
   missing-function error and stranding DB rows.
3. **H3** + **M1** — close the authz gaps (update endpoint role; socket
   room/role checks).
4. **M3** — align packaged service hardening with install.sh.
5. **M4** — wire agent tests into CI so the good validators don't silently rot.
6. **M2 / M5 / L-series** — allowlist compose+cron paths; runtime guard or louder
   doc for single-worker; clean up placeholders and the obfuscation-vs-encryption
   wording.

---

## Appendix A — Authorization map (server routes)

Reads are `@jwt_required()` (any active user incl. viewer); writes are
`@developer_required`; fleet ops are `@admin_required`. **Unauthenticated by
design:** `/register` (token-gated, `5/min`), `/install.sh`, `/install.ps1`,
`/agent/version`, `/agent/version/check`, `/agent/download/<os>/<arch>` (302 →
GitHub), `/agent/checksums`. **Authz outliers:** `/<id>/agent/update` is
auth-only (H3); pairing `/claim` + `/lookup` are auth-only (L1).

## Appendix B — Claims checked and rejected

- **"~370 MB of committed MSI binaries in `agent/packaging/msi/output/`."**
  **False.** `git ls-files` shows zero tracked `.msi`/`.wixpdb`, and
  `git check-ignore` confirms the directory is ignored. They are local build
  artifacts, correctly untracked. The only committed binaries under `agent/` are
  small required assets (`.syso` resource objects, tray/setup `.ico`/`.png`).
- **"Agent defines HMAC/nonce/timestamp helpers but never calls them."**
  **False.** Both transports call `SignMessageWithNonce` with a fresh nonce; the
  panel verifies and records it. (The helper-only view came from grepping
  definitions without call sites.)
