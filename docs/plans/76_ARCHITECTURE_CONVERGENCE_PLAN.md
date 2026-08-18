# Plan 76 — Architecture convergence: one contract at every boundary

## Status

In progress on `refactor/architecture-convergence`.

This plan turns the structural review of ServerKit into an executable migration.
It is deliberately incremental: each milestone leaves the repository deployable,
has a focused verification gate, and is committed independently.

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

