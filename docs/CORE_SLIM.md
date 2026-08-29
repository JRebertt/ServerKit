# Core-slim: which core pages become extension-delivered

> Decision doc — plan 25 Phase 6 (#18 / Extensions Platform #39).
> **No code moves in this document.** It classifies the surfaces, fixes the order,
> and gives a per-page migration checklist. Each move is its own small follow-up
> slice, tracked against this doc.

## Why now

Plan 25 landed the last missing rail: an extension can ship a **prebuilt runtime
frontend bundle** that the panel loads **without a rebuild**, integrity-verified.
Combined with the already-proven install / update / survival / config / socket /
jobs rails, a vertical no longer has to live in `core` to have a real UI. So the
question is no longer *"can* a page be an extension" but *"which ones should move,
in what order, and how far"*.

Two speeds already exist (decision D2): a **thin-wrapper builtin** owns the
route/nav/palette via its manifest while its page component + backend stay in
`core` (e.g. `serverkit-gpu`'s `frontend/index.jsx` is just
`import GpuMonitor from '../../pages/GpuMonitor'`). Core-slim is about finishing
the extraction: moving the **UI into the extension dir** so the extension is
self-contained — and, where it makes sense, shipping it as a **runtime bundle**
so it can leave the repo entirely.

## Tiers

### Tier A — already self-contained (done)

Frontends already live in the extension dir; nothing to move.

| Extension | Notes |
|---|---|
| `serverkit-crowdsec` | Reference implementation of the sanctioned page skeleton. |
| `serverkit-dns-server` | Self-contained. |
| `serverkit-mail` | Self-contained (Stalwart mail engine). |
| `serverkit-gui` | Self-contained; **first runtime-bundle migration** (plan 25 Phase 4). |

These are the template to copy. `serverkit-gui` specifically proves the
runtime-bundle path (externalized build, CSS inlined) — Tier B/C follow it.

### Tier B — thin wrappers whose UI still lives in `core/pages`

Each has an extracted backend + a manifest that owns its route, but its page
component (and helpers/styles) still lives under `frontend/src/pages/`. Ordered
**smallest / least-coupled first** so the early moves establish the pattern
cheaply. Sizes are the core page's current line count (the UI to relocate).

| # | Extension | Core page | ~lines | Coupling notes |
|---|---|---|---:|---|
| 1 | ✅ `serverkit-gpu` | ~~`GpuMonitor.jsx`~~ | 199 | **DONE (plan 32 #7, 2026-07-06).** Backend moved to `builtin-extensions/serverkit-gpu/backend` (`entry_point gpu:gpu_bp`, `url_prefix /api/v1/gpu`); page moved to `frontend/components/GpuMonitor.jsx` (SDK imports); core page + core `app/api/gpu.py` + `app/services/gpu_service.py` deleted; `sdk_version ^1.0.0` declared. Shipped **baked** (dual-path per guardrail below); runtime-ESM build scaffold added, live runtime-loader render deferred with plan 32 #9. |
| 2 | `serverkit-cloud-provision` | `CloudProvision.jsx` | 239 | One page; leans on connection APIs already in core. |
| 3 | ✅ `serverkit-cloudflare-ops` | ~~`CloudflareZoneSettings.jsx`~~ | 469 | **DONE (plan 52 Ph2 prep, 2026-08-29).** Page + WAF/Workers/Tunnels/Storage panels + own API client + SCSS moved into `builtin-extensions/serverkit-cloudflare-ops/frontend/`; DNS records + CF connection stay core. Standalone repo prepared (operator publishes). |
| 4 | `serverkit-remote-access` | `RemoteAccess.jsx` | 516 | WireGuard pairing UI; agent-fleet coupling via SDK. |
| 5 | `serverkit-ftp` | `FTPServer.jsx` | 687 | Accounts CRUD; self-contained once helpers move with it. |
| 6 | `serverkit-status` | `StatusPages.jsx` | 747 | Has a **public** status route (`/status/:slug`) that must stay reachable — verify the public path still resolves post-move. |
| 7 | ✅ `serverkit-email` | ~~`Email.jsx`~~ | 1086 | **DONE (plan 52 Ph2 prep, 2026-08-29).** Page + own API client + SCSS moved into `builtin-extensions/serverkit-email/frontend/`; DNS-provider + relay methods stay core (Settings surfaces). Standalone repo prepared (operator publishes). |
| 8 | `serverkit-workflows` | `WorkflowBuilder.jsx` | 1092 | Largest Tier B; pulls in `@xyflow/react` — externalize it or bundle it into the extension (it is NOT a host-shared lib). |
| 9 | `serverkit-git` | Git page group | — | Already plugin-contributed self-rendering (`sk-tabgroup` shell). Mostly a file-move; last in Tier B because its tab-group wiring is the closest analog to Tier C. |

**Shared-lib caution (Decision 2):** only `react`, `react-dom`,
`react/jsx-runtime`, `react-router-dom`, `serverkit-sdk` are externalized by the
host import map. Anything else a page uses today from `core` (charts via
`recharts`, flow via `@xyflow/react`, icons via `lucide-react`) must either be
**bundled into the extension** or first **promoted into the SDK**. Workflows
(`@xyflow/react`) and any chart-heavy page are the ones this bites.

### Tier C — WordPress ✅ DONE (plan 52 Phases 4-5, 2026-08-05)

`serverkit-wordpress` is fully extracted: Phase 4 moved the frontend (5 pages,
40 components, 3 SCSS files) into the extension and onto the `serverkit-sdk`
surface; Phase 5 took it out of the tree into the standalone
`serverkit-wordpress` repo as a runtime-ESM bundle (SDK 1.2.0). It distributes
through the registry and is offered during onboarding from the bundled index
entry; its schema stays core via the documented core data seam (D1).

## Per-page migration checklist

For each Tier B/C page, one slice:

1. **Move the UI** from `frontend/src/pages/<Page>.jsx` (+ its private
   components/styles) into `builtin-extensions/<slug>/frontend/`. Replace the
   thin `import … from '../../pages/<Page>'` re-export with the real component.
2. **Rewrite imports to the SDK**: swap deep `@/components/ds`, contexts, and
   `api` for `serverkit-sdk` imports (the lint flags deep `@/` for external
   extensions). Keep the same `/api/v1/<feature>` prefix (decision D9).
3. **Handle non-shared deps**: bundle them into the extension, or promote a
   genuinely common one into the SDK (a deliberate SDK **minor** bump).
4. **Delete the core copy**: remove the page import + `<Route>` + `PAGE_TITLES`
   entry from `App.jsx`, the `sidebarItems.js`/group-tabs entry, and the
   `CommandPalette.jsx` entry. The manifest already owns these.
5. **Pre-bundle**: `node scripts/sync-builtin-frontends.mjs` (baked path) — the
   CI drift gate (`--check`) keeps source/artifact in sync.
6. **(Optional) runtime bundle**: to ship it as an external (non-baked)
   extension, add the `--template frontend-esm` build (`vite.config.mjs`
   externalizing the shared libs → `dist/index.mjs`), set
   `frontend_entry: dist/index.mjs` + `sdk_version`, and validate with
   `new-extension.mjs --validate`. See [EXTENSIONS_CI.md](EXTENSIONS_CI.md).
7. **Verify**: `npm run lint && npm run build`; the screenshots skill renders the
   page; for `serverkit-status` confirm the **public** `/status/:slug` route
   still resolves; backend suite green.
8. **Keep it brand-neutral** and free/OSS (project policy).

## Migration log

### slice 1 — `serverkit-gpu` (2026-07-06, plan 32 #7)

Checklist status:

1. **Move the UI** ✅ — `builtin-extensions/serverkit-gpu/frontend/components/GpuMonitor.jsx`
   (index.jsx renders it instead of re-exporting the core page).
2. **Rewrite imports to the SDK** ✅ — `PageTopbar, KpiBand, api, useToast` from
   `serverkit-sdk`; `EmptyState` + `Button` via the `@/` alias (not yet on the
   SDK surface — tolerated for the baked path; a runtime-ESM build must bundle
   them or the SDK must promote them, a deliberate minor bump).
3. **Handle non-shared deps** ✅ — only `lucide-react` (bundled on the baked
   path). GPU styles (`_gpu.scss`) stay in core design-system SCSS for the baked
   slice; a runtime-ESM build would inline them into the bundle (as gui does).
4. **Delete the core copy** ✅ — core page, `app/api/gpu.py`,
   `app/services/gpu_service.py`, and the core `gpu_bp` registration removed.
   The manifest already owned nav/route/palette/title.
5. **Pre-bundle** ✅ — `node scripts/sync-builtin-frontends.mjs`; CI `--check`
   drift gate green.
6. **(Optional) runtime bundle** 🚧 — `frontend/vite.config.mjs` + `package.json`
   scaffold added (externalizes the shared libs → `dist/index.mjs`), `sdk_version`
   declared. Kept **baked** for this release (dual-path guardrail); flipping
   `frontend_entry` to `dist/index.mjs` + cutting a registry release is deferred
   to plan 32 #9 (needs push/publish + a test box).
7. **Verify** ✅ — `npm run lint && npm run build` clean; backend suite green
   (`test_gpu_extension.py` bridge tests + pipeline runtime-builtin SDK-gate
   fixture). No public route to re-check (gpu has none).
8. **Brand-neutral + free/OSS** ✅.

## Non-goals / guardrails

- **No big-bang.** One page per slice; the app stays shippable between slices.
- **Backend stays put** unless a slice explicitly extracts it — most Tier B
  backends are already extracted; the UI is the remaining half.
- **SDK is the throttle.** Every "promote a dep into the SDK" is a versioned
  contract change (`SDK_VERSION` bump) — do it deliberately, not per-page.
- **Dual-path during any runtime move**: keep the baked frontend for one release
  before deleting it, so panels mid-upgrade never lose the page.

## Sequence summary

Tier A (done) → Tier B in the numbered order above (gpu → cloud-provision →
cloudflare-ops → remote-access → ftp → status → email → workflows → git) →
Tier C (wordpress). Reassess after `serverkit-git` whether WordPress moves as one
slice or several sub-tab slices.
