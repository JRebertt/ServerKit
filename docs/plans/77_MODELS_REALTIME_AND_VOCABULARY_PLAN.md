# Plan 77 — One shape: models, realtime, and the shared vocabulary

## Position among the plans

Plan 75 owns the **services/system doors** (subprocess, docker, nginx, SQL
exec — Round 2 §G). Plan 76 owns the **boundary contracts** (auth, errors,
schemas, server state, forms, primitives). This plan owns what neither does:
the **shape of the data itself** — how models serialize, timestamp, encrypt,
and name their states — and the **realtime layer** that carries those shapes
to the browser. Same rule as its siblings:

> For each shape, one definition; migrate writers to it; ratchet so a second
> definition cannot appear.

Source: the 2026-08-18 11-agent duplication audit ("Twenty Doors" artifact;
memory `project_dry_audit_twenty_doors`). All counts grep-verified on
2026-08-18. One finding is a **live bug shipping today** and leads the
ordering (§A).

---

## A. Fix first — the agent handshake fork already shipped a bug

`agent_gateway.on_auth` (WS) and `api/agent_poll.py /connect` (HTTP long-poll
fallback) hand-roll the same ~70-line sequence twice: rate-limit → HMAC verify
→ allowed-IPs + anomaly tracking → new-IP check → version parse → register →
failure handling. `agent_poll.py` even comments "Mirrors the on_auth handler".
Drift has shipped twice:

1. Historically: the `/connect` rate limit was missing (the credential-stuffing
   bypass documented at `agent_poll.py:57-60`, patched back in).
2. **Now, verified:** `TunnelBrokerService.schedule_reconcile` is called from
   exactly one place — `agent_gateway.py:316`, the WS path. A WireGuard-capable
   agent connected via long-poll **never self-heals its tunnels after a
   restart.**

**A1 (immediate, smallest diff):** invoke the tunnel-reconcile capability hook
from the poll path's state ingest. A proving test: capability payload arriving
via poll triggers reconcile exactly as via WS.

**A2 (structural):** extract transport-neutral services on the registry —
`agent_registry.authenticate_and_register(payload, ip, user_agent, transport)`
returning `(session_token, server, error)`, and
`agent_registry.ingest_agent_state(agent, metrics, sysinfo, capabilities)`
owning capability side-effects. `on_auth` and `/connect`+`/poll` become thin
adapters translating errors to emit/disconnect vs jsonify/status. The registry
already proves the pattern with its dual-transport `send_command`.

**Gate:** both transports run the same handshake test matrix (bad HMAC, blocked
IP, rate limit, new-IP anomaly, capability side-effects); a ratchet asserts the
shared sequence has no second implementation.

---

## B. Model mixin suite

`backend/app/models/mixins.py` exists (SoftDeleteMixin lives there). It gains
the mechanical shapes below. **Reconciliation with plan 75 §F, which correctly
ruled "never consolidate `to_dict`":** that ruling protects per-entity
*difference*. What follows removes only the *mechanical fragment* inside those
methods, judged by plan 75's own test — "would a single change otherwise have
to be made in N places?"

| Shape | Measured | The single change that proves it |
|---|---|---|
| B1 `TimestampMixin` | 104 `created_at` + 69 `updated_at` definitions, ~270 `datetime.utcnow` references | `utcnow` is deprecated on Python 3.13 (this repo already fought Trixie/3.13 once); the tz-aware migration becomes a 1-file edit instead of ~270. Columns are byte-identical — **no schema migration needed**, adopt opportunistically |
| B2 `SerializableMixin` | 138 `to_dict()` methods across 90 files; 266 identical `self.X.isoformat() if self.X else None` ternaries | a datetime-format or field-masking convention change lands once. Introspect `__table__.columns`, auto-isoformat DateTime, class-level `__serialize_exclude__` (for `*_encrypted`/token columns), an `extra()` hook for computed fields. **Models with genuinely custom shapes keep their hand-written `to_dict` — the mixin is opt-in, never forced** |
| B3 `uuid_pk()` factory | the String(36) uuid4 lambda pasted 13× across 8 files, plus one incompatible `uuid4().hex` variant (`ai.py` — 32-char, no dashes) | the format decision is made once; a third format that breaks FK joins to String(36) columns cannot appear |
| B4 finish `JsonColumnMixin` | plan 75 §F2 built it (28 adopters) but **21 model files still hand-roll `json.loads`**, most without the mixin's corruption tolerance — a corrupt row 500s every serializing endpoint | pure adoption debt; ratchet: no `json.loads(` in models/ outside the mixin |
| B5 SoftDelete roadmap | 3 adopters (application, domain, saved_view) despite the docstring calling it the one deletion pattern | **not a sweep** — adoption is deliberately per-model (mixin + migration + recycle-bin registration + partial-unique-index, per migration 083). Rank by regret: `Server` (fleet enrollment + HMAC secrets) and `ManagedDatabase` first |

**Gate:** serializer parity tests on converted models (old dict == new dict,
key for key) before each swap; the B4 ratchet.

---

## C. One crypto path — `EncryptedSecret`

17 `*_encrypted` columns across 16 model files, handled three ways:

- hand-rolled accessor pairs — `server.py:208-240` **swallows encrypt failures
  with `print()` and silently stores nothing** (a live data-loss path);
- a completely separate class-level Fernet stack in `env_variable.py:42-83`
  (key derived from `SECRET_KEY`) that `shared_resource.py` reaches into
  cross-model;
- no accessors at all (oauth_identity, cloudflare_tunnel,
  registrar_connection) — pushing crypto calls into 12 service files.

**C1:** one `EncryptedSecret` descriptor (or `encrypted_column(name)` factory)
in `models/mixins.py` wrapping `utils/crypto`: assignment encrypts —
**raising, never printing, on failure** — read decrypts, and it standardizes
the `has_secret` masking already duplicated in three `to_dict`s.

**C2:** fold the parallel Fernet stack into it so there is one key-derivation
path. Migration is dual-read (try new path, fall back to old), encrypt-on-write
— **never a bulk decrypt-all→re-encrypt-all pass**: the PR #94 postmortem
records that exact approach double-wrapping credentials.

**Gate:** round-trip tests per column; a test that an encrypt failure raises;
ratchet: no `import` of `utils/crypto` from services for model-owned columns.

---

## D. One status vocabulary — database to pixels

The same terminal state is spelled four ways across the run-shaped models
(`success` in cron_run/backup_run, `completed` in db_snapshot and
environment_activity, `done` in sandbox runs, `succeeded` once) — 55 free-text
status columns, only ~6 files with constants. The frontend mirrors the chaos:
**19 files define their own status→color map, so "running" renders cyan,
green, or amber depending on the page**, split across two disjoint tone
vocabularies (ds/Pill kinds vs ui/badge variants); SCSS re-rolls the
state-color triple 83× across 32 files.

- **D1** `backend/app/models/status.py`: canonical lifecycle constants
  (PENDING / QUEUED / RUNNING / SUCCESS / FAILED / CANCELLED + a `TERMINAL`
  frozenset). New columns and API filters import it; existing domains migrate
  per-domain with a data migration when stored strings change (see open
  questions).
- **D2** `RunLifecycleMixin`: `mark_running()` / `mark_succeeded()` /
  `mark_failed()` / `mark_cancelled()` setting canonical status +
  started_at/completed_at/duration. Ten run models hand-write these
  transitions today (`deployment_job_service` writes `completed_at` in 11
  places). This is the model half of the already-open runs-consolidation item.
- **D3** frontend `ds/status.js`: one `statusKind(status)` map covering the
  union of job/deploy/service/backup states; StatusBadge, Pill call sites, and
  the connections tones all consume it; unify the two tone vocabularies so one
  table drives both primitives.
- **D4** SCSS `@mixin status-variant($color, $bg, $border)` + one canonical
  pill class; pages position the pill, never recolor it. Deletes the 83
  re-rolled blocks.

**Gate:** a parity test that every status string a run model can write has an
entry in status.py, and every status.py entry has a `statusKind`; ratchet on
per-page STATUS_KIND/getStatusColor definitions.

---

## E. One realtime door

Five parallel log/progress streaming implementations exist: `RunLogStream`
(persist + batch emit + `after_id` resync — the best, but hard-coupled to
`DeploymentJob`), two hand-rolled paths inside `sockets.py` (file logs;
container logs with no persistence/resync), the agent `on_stream` rebroadcast,
and a **dead `pipeline_*` channel with zero callers**. Meanwhile the unified
Job runtime has no live channel at all — Jobs, sandbox runs, site imports, and
backups each poll bespoke REST endpoints. Channel plumbing repeats too: 8
subscribe/unsubscribe pairs with four registry shapes and inconsistent auth
re-checks; room-name grammar lives in ~25 scattered f-strings across
sockets.py, agent_gateway.py, notifications, and is re-derived by hand in
frontend template literals.

- **E1** Generalize `RunLogStream` to a run-scoped envelope keyed by
  `(run_kind, run_id)`: one room grammar `run_<kind>_<id>`, one batched
  persisted `run_log` + `run_status` event pair, one `GET .../logs?after_id`
  polling twin. Accept any model implementing a small RunLike protocol
  (natural fit: anything carrying D2's `RunLifecycleMixin`). Adopt for unified
  Jobs, sandbox runs, site imports, backups. Retire the dead `pipeline_*`
  scaffolding.
- **E2** Declarative channel registry in sockets.py:
  `register_channel(name, room_fn, auth=predicate, on_first_subscribe=...,
  on_last_unsubscribe=...)` generating the handler pairs with one auth model.
- **E3** `backend/app/sockets_rooms.py` (or `rooms.py`) owning every room-name
  builder; mirrored event-name constants (`backend/app/constants.py` ↔
  `frontend/src/constants/events.js`) so a renamed event cannot fail silently.
- **E4** frontend `useServerStream(room, event, handler)` wrapping the
  join/listen/cleanup dance currently hand-rolled in 3 components.
- **E5** `BackgroundLoop` helper (Event-based stop, idempotent start/stop,
  app-context, logger error handling, auto-registration in
  `thread_ownership`): the 13 classified LIFECYCLE_PROCESS_LOOP threads each
  hand-roll the loop today (bool flags vs Event; sockets.py reports errors via
  `print()` — unreadable in prod).

**Gate:** stream contract test (emit → persisted row → `after_id` resync
returns it); channel auth test per registered channel; ratchet on raw
`socketio.on('subscribe_` handler definitions outside the registry.

---

## F. Shared infra utilities — five re-inventions, one home each

| Utility | Measured re-invention | One door |
|---|---|---|
| F1 remote catalog engine | the fetch → TTL → last-good → bundled-fallback pipeline is re-implemented in **4 services** (registry, theme_registry, template remote, security_feed), ~80–150 lines each; this family has already drifted in production (bundled-index and proxy-rewrite incidents) | `utils/remote_index.CachedRemoteIndex(env_var, default_url, bundled_path, ttl, error_ttl, normalize_fn)`; services become thin normalizers; future catalogs get the hardened behavior free |
| F2 TTL caches | 7 services hand-roll module-level TTL dicts despite `CacheService` (one file has two caches *and* imports cache_service) | a `ttl_cached(ttl, key_fn=None)` decorator on CacheService; Redis benefits apply wherever configured |
| F3 sensitive-data redaction | **4 diverging keyword lists** (utils filter, audit_service, middleware/audit — the only one covering totp/otp/csrf/session — telemetry) + 3 extra maskers; a keyword added to one list is silently not redacted by the other three sinks | `utils/sensitive_data_filter.py` exports the union `SENSITIVE_KEY_PARTS`, `is_sensitive_key()`, `mask_payload()`; the four sinks import it |
| F4 env access | 70 call-time `os.environ.get` across 28 app files bypass config.py; truthiness parsed in **3 incompatible variants** — `SERVERKIT_ALLOW_PRIVATE_DOWNLOADS=on` silently reads false in plugin_service | `utils/env.py` with `env_str`/`env_bool`/`env_int` (env_bool = config.py's `_bool`, moved out and imported back) |

**Gate:** per-utility unit tests; ratchet greps (no new module-level
`_cache = {}` + timestamp pairs; no new `SENSITIVE` lists; no
`.lower() in (` truthiness tuples outside utils/env.py).

---

## G. Test one-doors

The seed abstractions already exist in `conftest.py` — underscore-private.

- **G1** Promote `_mk_scope_user`/`_scope_token` to public
  `make_user(db, username, role='developer', **overrides)` and
  `headers_for(user)`; add `viewer_headers`/`developer_headers` persona
  fixtures beside the existing admin `auth_headers`. Today **45 test files
  mint their own JWT headers**; role is written three ways and passwords set
  three ways.
- **G2** `backend/tests/factories.py`: `make_application`, `make_server`,
  `make_workspace` with defaults + `**overrides`. `Application(` is constructed
  directly in **67 files**; `_seed_app` is byte-identical in at least two,
  the server fixture in three. Every schema change is currently absorbed by
  dozens of hand-rolled seed blocks.
- **G3** Guard against direct `create_app()`: **16 files** boot it around the
  plan-64 session-scoped fixture (one carries a justifying comment that is now
  false), re-exposing the state-leak classes conftest documents. Add a
  session-scoped `route_rules` fixture so no test boots an app just to read
  `url_map`, and extend `test_fixture_scope_guard.py` to assert no module
  calls `create_app` outside conftest without the `fresh_app` pattern.
- **G4** Promote `assert_requires_auth` / `assert_admin_only` (the shape exists
  file-private in `test_raw_infra_authz.py`) so per-endpoint 401/403 micro-tests
  (45 functions across 36 files) become one-liners.

The shared **subprocess stub kit is plan 75 G7**, not here — it must move in
lockstep with the `run_checked` migration.

**Gate:** the G3 guard test; migrate byte-identical helper files first as the
proof, then ratchet new-file usage via a conftest-level grep test.

---

## Ordering

| # | Workstream | Effort | Why |
|---|---|---|---|
| 1 | A1 — poll-path tunnel reconcile | trivial | **live bug**; a WireGuard agent on the fallback transport does not self-heal |
| 2 | C1 — `EncryptedSecret`, `server.py` first | low | the `print()`-swallowed encrypt failure is silent data loss |
| 3 | G1/G2 — personas + factories | low | enabler: every later migration writes tests through them |
| 4 | B1/B3/B4 — Timestamp, uuid_pk, JsonColumn finish | low | mechanical, no schema migrations, utcnow debt shrinks |
| 5 | D1/D2 — status constants + RunLifecycleMixin | medium | unblocks runs-consolidation and E1's RunLike protocol |
| 6 | A2 — transport-neutral handshake | medium | makes A1 structural instead of patched |
| 7 | E1–E4 — stream envelope + channels | high | the largest piece; lands on top of D2 |
| 8 | B2 — SerializableMixin, opportunistic | medium | parity-tested swaps, never forced |
| 9 | F1–F4 — infra utilities | low each | independent; F3 (redaction) first for the security surface |
| 10 | D3/D4 — frontend status map + SCSS variant | medium | after D1 so the vocabulary is settled |
| 11 | C2 — Fernet fold-in | medium | dual-read migration, scheduled alone |
| 12 | B5 — SoftDelete per-model adoptions | per-model | each is a deliberate product decision |

## Deliberately not in scope

- API/validation/auth boundary contracts — plan 76.
- Subprocess/docker/nginx/SQL-exec doors — plan 75 Round 2.
- Consolidating `to_dict` bodies that express genuine per-entity shape (plan 75
  §F's ruling stands; B2 removes only the mechanical fragment, opt-in).
- A generic runs UI — D2/E1 make one *possible*; building it is its own plan.
- Changing stored status strings wholesale — per-domain, with data migrations.

## Open questions

- **D1 stored-string migration:** map legacy spellings at the read edge
  (cheap, but the lie persists in the DB) or data-migrate per domain (clean,
  but each is a migration + deploy consideration)? Leaning per-domain
  migrations, smallest tables first.
- **C2 key derivation:** env_variable's Fernet derives from `SECRET_KEY`;
  `utils/crypto` has its own scheme. Which survives? Rotating `SECRET_KEY`
  must not brick stored env vars — the dual-read window may need to be
  permanent for rows never rewritten.
- **B2 field-selection interplay:** `api/_query.py` already does response
  field selection. Does `SerializableMixin` feed it (mixin produces the full
  dict, _query filters) or replace part of it? Decide before converting the
  first model.
- **E1 event compatibility:** existing `deploy_log`/`deploy_status` listeners
  ship in the frontend today. Dual-emit during migration, or migrate the
  deploy console in the same commit?

---

## Completion record — 2026-08-19

Executed in full (one session, ~30 commits on `dev`, +131 collected tests →
BASELINE_COUNT 4591). Every workstream landed with its gate; every ratchet
named below is a live test.

**Open questions, resolved:**
- *D1 stored strings*: read-edge `normalize()` shipped; per-domain data
  migrations remain deliberate follow-ups. `RunLifecycleMixin` carries
  per-model spelling overrides (DeploymentJob keeps `succeeded`) so adoption
  never silently rewrites a domain's vocabulary.
- *C2 key derivation*: `SERVERKIT_ENCRYPTION_KEY` (utils/crypto) survives.
  env_variable + sso_service write through it and dual-read (one path first,
  legacy `SECRET_KEY` Fernet second). The dual-read window is permanent —
  rows never rewritten decrypt forever; no bulk re-encrypt pass exists.
- *B2 field selection*: the mixin produces the full dict; `api/_query.py`
  keeps owning response shaping. (Hook is `serialize_extra()` — ServerMetrics
  has a column literally named `extra`.)
- *E1 event compatibility*: dual-emit. `run_log`/`run_status` are canonical;
  the deploy kind also emits legacy `deploy_log`/`deploy_status` until the
  Deploy Console migrates to the envelope.

**Deliberate scope calls (with owners for the tail):**
- B5: ManagedDatabase adopted (migration 088; delete keeps content+policy,
  purge never drops data, `?drop=true` stays destructive). **Server (~99
  query sites, fleet enrollment + HMAC secrets) is the next ranked adoption
  and needs its own pass.**
- F1: registry + themes ride `CachedRemoteIndex`; template_service (keyed
  per-repo cache w/ targeted invalidation) and security_feed (DB-durable
  last-good for a daily job) are documented non-adopters.
- E2: `subscribe_logs`/`subscribe_container_logs` stay raw (per-sid OS
  resources), frozen by the channel-registry ratchet until they migrate.
- D3: `running` is cyan for run-shaped surfaces; `serviceStatusKind` (in the
  same file) keeps steady-state surfaces green. Status-page/WAF/metric-series
  maps are domain vocabularies, allowlisted in `check-status-one-door.mjs`.

**Known pre-existing failures (not from this plan, all Windows-env):**
sbin resolution (×26), host_inventory (×7), firewall_detection (×3),
fleet_doctor DNS, getloadavg. Full Windows runs must
`--deselect tests/test_micro_cache.py::test_purge_wipes_and_recreates_cache_dirs`
(fails on `os.geteuid` under a patched `os.name` and aborts pytest).
