# Plan 76 — Architecture convergence: one contract at every boundary

## Status

Foundation implemented on `refactor/architecture-convergence`; broad domain
adoption remains incremental. The first execution wave completed the shared
doors and ratchets below without attempting a risky repository-wide rewrite.

## Execution ledger

| Boundary | Delivered in this wave | State |
|---|---|---|
| Authentication | One policy decorator per route; redundant-stack AST guard | Complete |
| API errors | Typed application errors, centralized mapping, request IDs | Complete foundation |
| Schemas and envelopes | Marshmallow endpoint contracts, real OpenAPI metadata, compatibility envelopes | Reference endpoints complete |
| List queries | Typed `ListQuery` over the shared query helper | Complete foundation |
| App composition | Curated 108-blueprint registry with parity guard | Complete |
| Transactions | Unit-of-work convention and subscription use-case extraction | Reference domain complete |
| Durable work | Image and Lynis scans on `JobService`; all remaining raw threads classified | Reference jobs complete |
| Remote execution | One agent-command transport boundary for all remote feature services | Complete transport seam |
| Controller boundaries | Exact owned inventory plus invitations service extraction | Ratchet active; legacy debt remains |
| Browser boundaries | Shared confirms, clipboard, blob/auth fetches, and lint ratchet | Complete foundation |
| Workspace context | One store/provider with cross-tab sync and API injection | Complete |
| Server state | Workspace-aware query lifecycle and Workspaces list/create migration | Reference domain complete |
| Navigation | 96-route manifest, title parity, lazy page registry | Complete |
| Forms | Shared lifecycle and create/edit user migration | Reference domain complete |
| Extension styles | Remote-access page style moved behind its extension entry point | Reference extension complete |

The commits are intentionally domain-sized. “Reference domain complete” means
the convention is executable, tested, and used by a real flow; older domains
should migrate when touched rather than being mechanically rewritten.

## Final verification for the first wave

- Frontend Node tests: 61 passed.
- Frontend lint and architecture checks: 0 errors; 955 pre-existing warnings.
- Frontend production build: 2,910 modules transformed with route-level page chunks.
- Backend full Windows run: 3,859 passed and 79 skipped. One stale error-contract
  assertion found by that run was corrected and its combined error suites then
  passed 27 tests.
- The remaining 37 Windows failures were confined to five Linux service-layer
  test files (`/usr/sbin`, fstab/POSIX path, `gaierror`, and `getloadavg`
  assumptions). The complete set passed 98 tests under WSL/Linux, ServerKit's
  supported host-management platform.
- Focused gates for authentication, typed API contracts, transactions,
  blueprint parity, jobs, controller debt, remote dispatch, workspace state,
  routing, forms, and extension sync all passed.

This plan turns the structural review of ServerKit into an executable migration.
It is deliberately incremental: each milestone leaves the repository deployable,
has a focused verification gate, and is committed independently.

---

## Second wave — measured adoption debt (2026-08-18 audit)

An 11-agent duplication audit (2026-08-18; full report in the "Twenty Doors"
artifact, memory `project_dry_audit_twenty_doors`) measured exactly how much
legacy traffic still walks around each door the first wave built. These numbers
were re-verified by direct grep on 2026-08-18 and are the baselines the second
wave ratchets against. "Migrate when touched" remains the rule for most
domains; the rows marked **drift/bug** justify proactive migration because the
bypass is not merely repetition — it behaves differently.

| Milestone | Door built | Measured bypass (baseline) | Note |
|---|---|---|---|
| A (auth) | `auth_required()` policy layer | **605 `@jwt_required()` vs 5 files on `auth_required`** | decorator-stack work is complete; the raw decorator population remains |
| A (auth) | `rbac.get_current_user()` | **70 inline `User.query.get(get_jwt_identity())` + 8 private `_current_user()` defs** (dns_cutover, environments, modules, projects, queue_bus, registrars, secrets_webhooks, themes) | **drift/bug: these return `None` for API-key callers** — only rbac checks `g.api_key_user`, so bypassing routes 404/401 API-key requests and misattribute actions. Violates invariant 2 today |
| A (auth) | `@admin_required` | 5 private `_require_admin()` defs with **three incompatible return contracts** (jobs.py's is inverted vs dns_cutover's); 28 inline role checks; `is_admin` vs `role != 'admin'` truth-source drift | add `require_admin_user()` (raises typed PermissionDenied) for mid-route gating, delete the five |
| B (errors) | `app/exceptions.py` + global handler | **2 of 103 api files import it; 1,211 hand-shaped `jsonify({'error': ...})`; 125 blanket `except Exception` (75 leak `str(e)`)** | drift/bug: locally-swallowed exceptions skip the 500 handler's logging **and the error tracker added 2026-08-17** — those crashes never appear in /monitoring/errors |
| B (errors) | typed raises in services | **238 `raise ValueError` in 43 service files → 83 per-route `except ValueError` with drifting codes** (same class → 400/403/404 by file) | `ValidationError` already subclasses `ValueError`, `NotFoundError` subclasses `LookupError` — incremental conversion is safe by design |
| C (schemas) | `@api_contract` + `api/schemas/` | **2 adopter files; 241 hand-rolled "X is required" 400s in 54 files; bool coercion in 3 incompatible variants** (`?enabled=yes` truthy on 11 endpoints, falsy on 24) | add interim `require_fields()` + `parse_bool_arg`/`parse_int_arg` next to contracts.py for low-churn routes |
| C (envelopes) | one failure/success shape | **84 services return `{'success': bool}` dicts; 383 `result.get('success')` translations in 30 api files, with status codes chosen by error-string sniffing** (`files.py:62`: `403 if 'denied' in error else 400`) | this tunneling protocol was not named in the first wave; converging it is what makes milestone B's contract reachable — services raise, routes return data |
| C (list queries) | `_query.py` / `ListQuery` | 6 files still hand-parse `page`/`per_page` (admin, source_connections, telemetry, error_logs, git, views) | small; the envelope's last bypass routes |
| Remote execution | `dispatch_agent_command` seam | **24 direct `agent_registry.send_command` callers outside the dispatcher** (api/servers.py ×4, terminal_service ×4, fleet services, tunnel broker/publish) | the seam exists; ratchet it to exactly the dispatcher + queued-delivery path |
| E1 (server state) | `useServerQuery`/`useServerMutation` + queryClient | **1 of 63 pages adopted; 44 pages hand-roll the identical fetch scaffold; the mutate→toast→reload triple hand-written ~90×; 148 per-page `toast.error(err.message)` extractions** | convert Vaults, Monitors, Projects, CronJobs as templates, then ratchet |
| E2 (live resources) | visibility-aware polling convention | **45 `setInterval` sites, zero pages with an in-flight guard, `visibilitychange` in one file repo-wide** | drift/bug: this is the documented poller-stampede shape; a `refetchInterval` on useServerQuery gets dedupe for free |
| F2 (forms) | `useForm`/`formState` + `FormField` | **1 adopter vs 330 `form-group` blocks in 59 files; 66 local saving/busy flags**; Modal's `footer` prop bypassed by 28 files (submit must live inside `<form>`); native `<select>` ×114 vs `ui/select` in 20 files | give Modal a form/onSubmit mode first — it removes the reason the footer is bypassed |
| F3 (primitives) | clipboard/confirm/blob helpers | 25 files still call `navigator.clipboard` raw (**undefined on HTTP-served panels — SSL is optional by policy**, so those copy buttons are broken there); blob-download ritual pasted in 15 components | the lint ratchet exists; extend it to these two APIs |
| C4-interim (bindings) | — | **~800 of 1,262 functions in `services/api/*` are 1–3-line CRUD wrappers; PUT-vs-PATCH drift (73 vs 11); 57 hand-rolled URLSearchParams blocks + 102 raw `?k=${v}` interpolations with an encoded-vs-raw lottery; dead 494-line `services/wordpress.js` (zero importers)** | until C4's generated bindings land, a `crudResource(basePath)` factory + `buildQuery()` + encoding `apiPath` template in client.js is the cheap interim; delete the dead file now |
| G (styles) | mixins/tokens | card surface hand-rolled 107× vs 7 `card-base` includes; ~300 color literals outside the token files (each one a spot runtime skins cannot recolor); 176 raw media queries vs 2 `respond-to`; `.empty-state` defined 3 competing times; `@keyframes spin` ×8 | mechanical sweeps + stylelint/CI greps per recipe |

Two second-wave rules:

1. **Every row above gets a ratchet before its migration starts** — a count
   that can only go down, in the style of the existing controller-boundary and
   error-contract ratchets. A migration without a ratchet regrows.
2. **The drift/bug rows (API-key identity, swallowed exceptions, status-code
   sniffing, unguarded pollers, raw clipboard) are not "when touched" — they
   are behavior differences shipping today** and should be scheduled like
   fixes, not like refactors.

Out of scope for this plan (owned elsewhere): the services-layer subprocess /
docker / nginx / SQL-exec doors are plan 75 Round 2 (§G); model mixins,
encrypted-secret handling, the status vocabulary, realtime stream/channel
convergence, and shared infra utilities are plan 77.

### Second-wave execution — milestone A identity and admin rows (2026-08-18)

Both rows are closed. They were taken first because rule 2 classes them as
fixes rather than refactors, and the audit turned out to have *understated*
them.

| Row | Baseline | Now | Commit |
|---|---|---|---|
| `rbac.get_current_user()` | 70 inline + 8 private helpers | 0 direct; 87 indirect ratcheted; **0 API-key-capable** | `fe02ce8e` |
| `@admin_required` mid-route | 5 private `_require_admin()`, 3 contracts | 0; one `require_admin_user()` | `6cd2ee6b` |

Corrections to the audit's measurements, all verified by test:

- **The API-key failure is a 500, not a `None`.** `auth_required()` skips
  `verify_jwt_in_request()` once the key middleware has authenticated, so
  `get_jwt_identity()` has no context to read and *raises*. Nine handlers
  behind API-key-capable policy decorators returned 500 to every API-key
  caller. Where a blanket `except Exception` wrapped the lookup (three service
  helpers) the raise degraded silently to `user_id=None` instead — the write
  landed and the audit trail lost the actor.
- **The inline population has two shapes, not one.** Beyond the 73 direct
  `User.query.get(get_jwt_identity())` sites there are 87 of the two-line
  `uid = get_jwt_identity()` variant. All 87 remaining are on
  `@jwt_required()`-only routes, where reading the JWT is correct today — they
  are ratcheted rather than migrated, because they are exactly what breaks when
  the rest of milestone A moves those routes onto policy decorators.
- **There is a sixth `_require_admin()`**, in the cloudflare-ops extension
  source (29 gates, jobs.py's inverted contract). It was invisible to a
  `backend/app/` census because the extension has no installed live copy.
- **12 of the 19 private helpers were named `get_current_user`** — shadowing
  the real door, so the call sites already read as if they were correct.

Ratchets added: `tests/identity_door_census.py` +
`tests/test_identity_door_ratchet.py` (ceiling 87, and a separate assertion
holding the API-key-capable population at zero). The first wave's
controller-boundary baseline dropped 593 -> 519 persistence crossings as a
side effect.

Still open on milestone A: the 605 `@jwt_required()` routes that have not moved
to `auth_required()`, and the 28 inline role checks.

### Second-wave execution — milestone F3 clipboard row (2026-08-18)

| Row | Baseline | Now | Commit |
|---|---|---|---|
| clipboard helper | 25 files / 33 raw `navigator.clipboard` sites | 0; ratchet baseline emptied | `a75f435f` |

The row was scheduled as a fix for the reason the audit gave — `navigator.
clipboard` is undefined in an insecure context and SSL is optional by policy,
so those copy buttons did nothing on an HTTP-served panel — and the shape
matched milestone A's exactly: **two of the bypasses were local functions named
`copyToClipboard`**, so their call sites read as already-converged. The
frontend boundary ratchet already carried an exact per-file baseline; it is now
`new Map()` and documented as needing to stay empty.

Note for the remaining F3 work: `.then(onOk, onErr)` chains cannot be
mechanically repointed at the helper. `copyToClipboard` resolves `false` rather
than rejecting, so the error callback silently stops running; four sites needed
`.then(ok => ...)` instead.

### Second-wave execution — milestone B crash-reporting row (2026-08-18)

| Row | Baseline | Now | Commit |
|---|---|---|---|
| swallowed exceptions | 43 API handlers answering 500 with no report; 35 leaking `str(exc)` | 0; ratchet held at **0** | `a7d5a0b9` |

The row's premise checked out and is worth stating precisely: the global 500
handler was the **only** caller of
`error_log_service.record_error(source='backend')`. Catching `Exception` in a
route did not merely skip logging — it removed the endpoint from
`/monitoring/errors` entirely, and did so invisibly, because the endpoint still
answered.

The fix was not to rewrite error bodies but to make the recorder importable:
`app/error_reporting.py` now owns logging + rollback + recording, and the 500
handler calls it too, so there is one recorder instead of one recorder and 43
routes opted out of it.

Corrections to the audit's measurement:

- **The blanket-`except` population is 1,404 in 243 files, not 125** — the
  audit's number was the `app/api` subset (129). The vast majority (1,058) are
  in `app/services`, where catching an exception and returning a value is a
  domain decision, not an HTTP answer. Converging those through an HTTP-shaped
  door would be the wrong move, so the ratchet is scoped to `app/api`.
- **The leak was worse than `str(e)` in two places**: `templates.py` returned
  the full traceback to the caller and `print()`ed it.
- **Three sites had invented a second correlation id** — a local
  `uuid.uuid4().hex[:8]` "ref" that appeared in a log line and nowhere else,
  while `X-Request-ID` already existed from milestone B's first wave.

Measured and deliberately left open: **56 API handlers swallow a crash and
answer 200.** A failure reported as success is a worse bug than a 500 nobody
logged, but converging it means deciding the response envelope, which is
milestone C. It is called out here so the plan cannot claim B is finished.

### Second-wave execution — milestone E2 polling row (2026-08-18)

| Row | Baseline | Now | Commit |
|---|---|---|---|
| visibility-aware polling | 45 raw `setInterval` in 35 files; 1 with a visibility check, 1 with an in-flight guard | door + 4 reference migrations; 41 in 31 files ratcheted | `f21abe7a` |

`utils/pollScheduler.js` (pure, testable without a DOM) + `hooks/usePolling.js`
+ `refetchInterval` on `useServerQuery`, all one implementation.

The audit's framing needs one correction that matters for the remaining
migrations: **the in-flight guard is not what stops the schedule from
stacking.** Arming the next tick from the previous run's *completion* is. With
`setInterval` the gap is measured tick-to-tick regardless of how long the work
took, so a 5s poller against a 30s request has no gap at all — the guard alone
would still leave a request starting every 5s and being dropped, which is
wasted work rather than a fixed poller. The guard's real job is the out-of-band
paths: a manual `refresh()` and the visibility catch-up.

Also worth knowing before migrating the remaining 41: several sites use the
interval effect's dependency array as an out-of-band "reload now" trigger
(`MonitorsSummary`'s `refreshKey`). Moving to `usePolling` drops that unless it
is re-expressed as an explicit refresh — a silent loss of a working feature, not
a compile error.

Remaining E2 work is the other 41 sites, of which a minority are genuine
non-fetching timers (clock ticks, countdowns) that can stay listed rather than
migrated.

## Thesis

ServerKit does not mainly suffer from missing abstractions. It has good shared
primitives, but older and newer ways of doing the same job coexist. Every extra
way to authenticate a route, shape a list response, execute a host command,
fetch frontend data, or store the active workspace is another boundary that can
drift.

The convergence rule is:

> For each cross-cutting concern, choose one public door, migrate callers to it,
> and add a guard that prevents a second door from appearing.

This continues the approach established by plans 69 and 75. It does not create
generic CRUD repositories, universal serializers, a god `BaseService`, or a
blanket subprocess wrapper. Repetition that expresses genuinely different
operational semantics stays explicit.

---

## Baseline measured before implementation

| Surface | Approximate size | Main signal |
|---|---:|---|
| Backend API | 101 modules / 23k lines | Large route modules and manual boundary work |
| Backend services | 206 modules / 72k lines | Multiple result, transaction, and execution conventions |
| Backend models | 93 modules / 8k lines | Not the primary duplication source |
| Frontend pages | 70 modules / 34k lines | Page-level fetching, forms, and dialogs repeated |
| Frontend components | 326 modules / 58k lines | Strong primitives exist, but adoption is incomplete |
| Frontend SCSS | 128 files / 51k lines | Repeated layout recipes and raw breakpoints |

High-value examples:

- `backend/app/api/servers.py`: more than 3,000 lines and about 126 routes.
- `backend/app/api/apps.py`: more than 2,500 lines and about 54 routes.
- `backend/app/__init__.py`: about 108 explicit blueprint registrations mixed
  with startup responsibilities.
- About 390 manual `request.get_json()` calls and 380 manual query-argument
  reads across API modules.
- About 1,260 handwritten frontend API functions.
- More than 40 frontend polling intervals and hundreds of local loading/error
  state transitions.

These numbers are navigation aids, not targets to reduce blindly.

---

## Invariants for the migration

1. Existing external API behavior is preserved unless a compatibility note and
   migration are included in the same milestone.
2. API-key-capable policy routes must remain API-key capable.
3. A list capability is not removed until its replacement is present and
   verified.
4. Route handlers authenticate, parse, invoke a use case, and map a response;
   they do not become a second service layer.
5. Lower-level services do not commit a transaction owned by a top-level use
   case.
6. Remote and local execution report the same semantic result without forcing
   all host capabilities through one god interface.
7. Frontend server state is keyed by workspace and cancelled or invalidated
   when that context changes.
8. New architecture rules ship with an executable guard where practical.
9. Migrations are by domain or touched surface, never repo-wide mechanical
   rewrites without behavioral tests.
10. Each commit has one architectural purpose and passes its focused gate.

---

## Milestone A — Authentication has one door

**Maps to review recommendation:** 1.

- Remove redundant `@jwt_required()` wrappers from routes whose policy
  decorator already authenticates through `auth_required()`.
- Preserve explicitly JWT-only routes and document the reason at exceptional
  sites.
- Establish one policy decorator per handler: authenticated, admin, developer,
  app member, or another resource capability.
- Add an AST conformance test that rejects redundant authentication stacks.
- Add API-key and JWT behavioral coverage for representative policy routes.

**Gate:** focused RBAC tests, API error-shape tests, backend collection.

**Commit:** `refactor(auth): enforce one authentication policy per route`

---

## Milestone B — API failures have one contract

**Maps to review recommendations:** 5 and the observability part of 20.

- Add a small typed exception taxonomy for validation, not-found, conflict,
  permission, and unavailable dependency failures.
- Map exceptions centrally to the existing JSON error contract.
- Generate or accept a request ID, return it in `X-Request-ID`, include it in
  error responses, and make it available to logs/jobs/agent calls.
- Migrate representative endpoints first; expand only when a domain is touched.
- Add contract tests for status, body, headers, and unexpected exceptions.

**Gate:** API error-shape and representative endpoint tests.

**Commit:** `feat(api): centralize typed errors and request correlation`

---

## Milestone C — Endpoint schemas and response envelopes

**Maps to review recommendations:** 2, 3, and 4.

### C1. Schema foundation

- Choose one Python request/response schema mechanism that works with Flask and
  the existing dependency budget.
- Provide a decorator/helper that validates JSON, path, and query inputs and
  passes a typed value to the handler.
- Record schema metadata on the Flask view for OpenAPI generation.
- Migrate one read endpoint, one mutation, one upload-adjacent endpoint, and one
  paginated list as reference implementations.

### C2. Stable envelopes

- New single-resource response: `{ "data": { ... } }`.
- New list response: `{ "data": [ ... ], "meta": { ... } }`.
- New mutation response: `{ "data": ..., "message": ... }`, omitting unused
  keys rather than inventing null placeholders.
- Maintain compatibility adapters for existing endpoints until their consumers
  migrate; do not silently change hundreds of endpoints at once.

### C3. List-query convention

- Promote `apply_query` behind a typed `ListQuery` input.
- Require explicit filter/search/sort allowlists and maximum page sizes.
- Converge offset and cursor metadata without pretending they are interchangeable.

### C4. Useful OpenAPI and frontend bindings

- Generate request bodies, parameters, response envelopes, and error schemas
  from endpoint metadata rather than generic `object` placeholders.
- Generate JavaScript bindings/JSDoc types for conventional endpoints.
- Keep thin handwritten bindings for streaming, uploads, and other intentionally
  custom transports.

**Gate:** schema tests, OpenAPI snapshot/validation, generated-client drift test,
and a frontend build using a representative generated binding.

**Commits:** one foundation commit, followed by domain-sized migration commits.

---

## Milestone D — Backend use-case boundaries

**Maps to review recommendations:** 6, 7, 8, 9, 10, and 11.

### D1. Thin controllers and vertical feature packages

- Define a dependency rule: routes may import schemas, policies, and public
  feature services, but not perform filesystem/subprocess work or own domain
  persistence.
- Split `apps.py` and `servers.py` by capability as those domains are touched.
- Prefer `features/<domain>/<capability>/` for new large domains while keeping
  compatibility imports during migration.
- Do not convert every stateless service class mechanically; change organization
  when it creates a real public boundary.

### D2. Transaction ownership

- Add a documented unit-of-work convention around the existing SQLAlchemy
  session.
- Top-level use cases commit once; nested operations flush or return changes.
- Make post-commit external effects explicit and retryable where appropriate.
- Add rollback tests for representative multi-step operations.

### D3. One capability-policy engine

- Consolidate owner, workspace, grant, and role decisions behind
  `can(actor, action, resource)` or an equivalent typed policy API.
- Resource decorators resolve the entity once and expose it through request
  context.
- Deprecate local route helpers only after parity tests cover their semantics.

### D4. Local/remote host capability ports

- Introduce narrow protocols such as command execution, file transport,
  container runtime, and service management.
- Select local or agent-backed adapters at the composition boundary.
- Migrate one domain end to end before generalizing the adapter surface.

### D5. Durable jobs versus live workers

- Classify every raw thread site as durable one-shot work or a true long-lived
  listener/stream.
- Move scans, imports, provisioning, and other durable work to `JobService`.
- Keep listeners as managed workers with explicit startup/shutdown ownership.
- Standardize progress, cancellation, retry, and correlation metadata.

### D6. Feature registration

- Introduce an explicit core feature registry describing blueprints, startup
  hooks, workers, and shutdown hooks.
- Keep the registry curated; do not use filesystem auto-discovery.
- Reduce the app factory to composition and environment wiring.

**Gate:** dependency/conformance tests plus domain behavior tests for each migrated
slice.

**Commits:** one commit per D sub-milestone or migrated domain.

---

## Milestone E — Frontend data and application context

**Maps to review recommendations:** 12, 13, and 15.

### E1. Server-state foundation

- Introduce TanStack Query or a deliberately small internal query layer over
  `ApiClient`; choose based on bundle/dependency evaluation.
- Standardize workspace-aware keys, cancellation, deduplication, retry policy,
  mutation invalidation, and error presentation.
- Migrate a representative list/detail/mutation flow before broader adoption.

### E2. Live-resource convention

- Prefer Socket.IO updates with visibility-aware polling fallback.
- Prevent overlapping requests and stop polling at terminal states.
- Expose one `useLiveResource` lifecycle contract while keeping resource-specific
  event interpretation explicit.

### E3. Workspace and preferences

- Establish `WorkspaceProvider/useWorkspace` as the only active-workspace owner.
- Inject workspace access into `ApiClient` rather than reading storage in
  unrelated modules.
- Add a versioned preference helper for persistent UI settings and migrations.

**Gate:** hook tests covering workspace changes, cancellation, cache isolation,
polling cleanup, and invalidation.

---

## Milestone F — Frontend navigation, forms, and primitives

**Maps to review recommendations:** 14, 16, 17, and 18.

### F1. Route manifest

- Define route descriptors for path, lazy component, title, guard, feature flag,
  navigation group, and command-palette metadata.
- Generate router/title/navigation consumers while allowing extension
  contributions.
- Code-split route pages and preserve current guard behavior.

### F2. Form convention

- Converge on `FormField` and a shared form lifecycle: values, client schema,
  dirty state, submit state, field errors, and server-error mapping.
- Keep complex forms composed in code; do not create a universal JSON form
  renderer.
- Migrate repeated create/edit dialogs by domain.

### F3. Primitive enforcement

- Replace raw authenticated fetch, clipboard access, `window.confirm`, and
  ordinary low-level dialogs with established helpers.
- Extend ESLint/conformance checks so new bypasses fail locally and in CI.
- Retain native or low-level primitives where a documented accessibility or
  transport need makes them intentional.

### F4. Large-page decomposition

- Treat a route page as a controller plus composition root.
- Extract data hooks, column definitions, drawers/forms, and feature views.
- Add a soft size warning, not a hard line-count gate; cohesion is the real test.

**Gate:** lint, focused component/hook tests, production build, and route smoke
coverage.

---

## Milestone G — Extension and styling ownership

**Maps to review recommendations:** 19 and the ownership part of 20.

- Move built-in extension UI and SCSS behind extension-owned entry points.
- Finish the Application-to-Service detail migration and remove old components
  only after import-graph and visual parity checks.
- Keep core responsible for stable SDK and design-system primitives.
- Break oversized page SCSS into component-owned partials as components move.
- Add semantic layout recipes and breakpoint tokens; do not outlaw legitimate
  brand or data-visualization colors.
- Prevent core `main.scss` from accumulating extension-specific imports.

**Gate:** extension drift tests, import-graph checks, production build, and visual
smoke checks for affected routes.

---

## Milestone H — Conformance and migration closure

**Maps to review recommendation:** 20 and protects all preceding milestones.

- Check redundant auth stacks and route schema coverage.
- Validate OpenAPI and generated-client freshness.
- Check raw frontend boundary APIs and deprecated grid props.
- Move the list-preset browser prober into checked-in CI.
- Add Vitest and React Testing Library coverage for shared hooks, forms, routing,
  grids, workspace switching, and permissions.
- Keep backend contract tests for probes, transactions, errors, and policies.
- Publish a remaining-migration inventory generated from the same checks, so the
  plan cannot claim completion while known legacy doors remain.

**Gate:** backend suite, frontend lint/tests/build, extension checks, and the
architecture-conformance suite.

---

## Recommended execution order

1. A — auth boundary.
2. B — errors and request correlation.
3. C1/C2 — schemas and envelopes.
4. F3 — frontend primitive guards.
5. C3/C4 — list queries, OpenAPI, generated bindings.
6. E — frontend server state and workspace context.
7. D — one backend domain at a time, starting with applications.
8. F1/F2/F4 — navigation, forms, and page decomposition.
9. G — extension and SCSS ownership.
10. H — closure gates and remaining migrations.

The ordering establishes boundary contracts before moving large amounts of code.
Milestones can overlap only when they do not edit the same public surface.

---

## Commit discipline

- One milestone or one domain migration per commit.
- No drive-by formatting or unrelated cleanup.
- Commit messages state the architectural contract being established.
- Focused tests run before every commit; broader suites run at milestone closure.
- If a migration needs compatibility code, the compatibility path and its removal
  condition are documented in the same commit.
- This document is updated as milestones complete, including commit hashes and
  intentionally deferred cases.

## Definition of done

The plan is complete when:

- every cross-cutting concern above has one documented public entry point;
- legacy bypasses are either migrated or explicitly registered exceptions;
- executable checks prevent new bypasses;
- representative core and extension domains use the new paths end to end;
- remaining compatibility adapters have owners and removal conditions;
- backend tests, frontend tests/lint/build, and architecture checks pass; and
- the completion record names the commits and any intentionally retained
  semantic duplication.
