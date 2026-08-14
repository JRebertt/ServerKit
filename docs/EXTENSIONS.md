# Extension Author Guide

ServerKit is a small core of primitives plus optional **extensions** installed
from the Marketplace. This document is the honest, single reference for building
one: the manifest schema, the contribution envelope, lifecycle hooks, the backend
SDK, install sources, and — importantly — the constraints you will hit in
production.

> If you only remember one thing: **an extension's frontend must be compiled into
> the panel's Vite bundle to render.** For builtin (in-repo) extensions we handle
> this by pre-bundling (see [The production frontend constraint](#the-production-frontend-constraint)).
> A third-party extension that ships only a backend works everywhere today; one
> that ships a frontend needs the delivery mechanism tracked in Phase 3 of the
> platform plan.

---

## Anatomy of an extension

An extension is a folder (zipped for distribution) with this layout:

```
my-extension/
  plugin.json          # manifest — the only required file
  backend/             # optional: Flask blueprint + services + lifecycle hooks
    blueprint.py
    lifecycle.py
  frontend/            # optional: React components exposed to the host UI
    index.jsx          # entry module — named exports referenced by contributions
    styles/
      my-extension.scss
```

- `backend/` is extracted to `backend/app/plugins/<slug>/` on the panel host and
  its blueprint is hot-loaded (no restart needed for install).
- `frontend/` is extracted to `frontend/src/plugins/<slug>/`. For builtin
  extensions this directory is **checked in** (a build artifact — see below).
- Either half is optional. A pure-frontend extension (like `serverkit-git`, whose
  backend API stays in core) declares only `contributions`; a pure-backend
  extension declares an `entry_point` and no frontend.

---

## `plugin.json` manifest

```jsonc
{
  "name": "serverkit-git",            // required — slug: ^[a-zA-Z0-9_-]+$
  "display_name": "Git Server",       // required
  "version": "1.0.0",                 // required — semver recommended
  "description": "…",
  "author": "ServerKit",
  "homepage": "https://…",
  "repository": "https://…",
  "license": "MIT",
  "category": "deployment",           // ai|monitoring|security|deployment|integration|ui|utility
  "icon": "<svg…>",                   // optional — rendered on the marketplace detail view
  "screenshots": ["https://…/1.png"], // optional — rendered on the detail view

  "permissions": ["docker", "filesystem"],   // docker|filesystem|shell|network|db
  "min_panel_version": "1.7.0",       // optional compat gate (enforced at install)
  "max_panel_version": "2.0.0",       // optional

  "entry_point": "blueprint:git_bp",  // backend: module:bp_var under app.plugins.<slug>
  "url_prefix": "/api/v1/git",        // defaults to /api/v1/<slug>

  "templates": ["gitea"],             // app-template ids to install alongside
  "lifecycle": {                      // module:func hooks under app.plugins.<slug>
    "install":   "lifecycle:on_install",
    "uninstall": "lifecycle:on_uninstall",
    "upgrade":   "lifecycle:on_upgrade"
  },

  "models": ["models:register"],      // optional — plugin-owned tables (see Data models)
  "config_schema": { … },             // optional — rendered as a settings form

  "contributions": { … }              // UI contributions — see below
}
```

The authoritative, machine-readable contract is served at
`GET /api/v1/plugins/manifest-spec` and mirrors what `plugin_service.py` actually
consumes — keep them in sync when extending the schema.

---

## The `contributions` envelope

Everything an extension adds to the host UI is declared here. Each entry is
tagged at runtime with its source `plugin` slug so the frontend can resolve
`component` strings against the right module.

```jsonc
"contributions": {
  "nav": [
    { "id": "git", "label": "Git", "route": "/git",
      "category": "infrastructure", "icon": "<circle …/>",
      "requiresCondition": "gpuAvailable" }          // optional runtime gate
  ],
  "routes": [
    { "path": "git", "component": "GitExtensionPage" },
    { "path": "git/:tab", "component": "GitExtensionPage", "layout": "padded" }
  ],
  "page_titles": { "/git": "Git Repositories" },
  "command_palette": [
    { "label": "Git", "path": "/git", "category": "Pages", "keywords": "repos deploy" }
  ],
  "widgets": [ { "slot": "dashboard.top", "component": "GitStatusWidget" } ],
  "dashboard_widgets": [
    { "id": "git-activity", "name": "Git activity", "component": "GitActivityWidget",
      "category": "Operations", "description": "Recent pushes across repositories",
      "w": 4, "h": 3, "min": [3, 2], "default_cfg": { "limit": 6 } }
  ],
  "layouts": [ { "id": "my-fullscreen", "component": "MyLayout" } ],
  "tabs": [
    { "group": "files", "to": "/ftp", "label": "FTP Server", "icon": "<rect …/>" }
  ],
  "ai": {
    "suggested_prompts": [ { "route": "/git", "label": "…", "prompt": "…" } ],
    "tool_renderers":    [ { "tool": "git__list_branches", "component": "BranchList" } ]
  }
}
```

| Kind | Shape | Notes |
|---|---|---|
| `nav` | `{id,label,route,category,icon,requiresCondition?}` | `icon` is raw inner-SVG markup. `category`: overview/infrastructure/operations/system. Merged into the sidebar; deduped by `id`. |
| `routes` | `{path,component,layout?,group?}` | `component` = a named export of the plugin's `index.{js,jsx}`. `layout`: `padded` (default) / `full` / `bare` / a custom layout id. `group` nests the route inside a core tab group instead — see [Tab-group contributions](#tab-group-contributions). |
| `page_titles` | `{ "/path": "Title" }` | Sets `document.title`. |
| `command_palette` | `{label,path,category,keywords}` | `category` defaults to `Extensions`. |
| `widgets` | `{slot,component}` | Slots: `global` (renders inside DashboardLayout), plus the enrich-core slots (`dashboard.top`, `service.detail.tab`, `domain.drawer.panel`). Fixed position — the host decides where it renders. |
| `dashboard_widgets` | `{id,name,component,icon?,category?,description?,w?,h?,min?,default_cfg?}` | Registers a **placeable** widget type in the dashboard widget library. The user adds, moves, resizes and configures instances on their own boards. `category`: Metrics/Inventory/Operations/Utility (defaults to `Extensions`). `w`/`h` = default span in a 12-column grid; `min` = `[minW,minH]`. The component receives `{ widget, ctx }` — see [Dashboard widgets](#dashboard-widgets). |
| `layouts` | `{id,component}` | Custom wrappers; the component must render `<Outlet/>`. Built-in ids `padded`/`full`/`bare` are reserved. |
| `tabs` | `{group,to,label,icon?,end?,order?}` | Adds a tab to a core-owned tab group. `group` = the group id (`files` / `servers` / `monitoring`). See [Tab-group contributions](#tab-group-contributions). |
| `ai` | `{suggested_prompts,tool_renderers}` | See [AI](#extending-the-ai-assistant). |

### Route layouts

- `padded` (default) — inside `DashboardLayout`, normal padding.
- `full` — inside `DashboardLayout`, no padding (like `/files`, `/docker`).
- `bare` — **outside** `DashboardLayout` (no sidebar), under the auth guard —
  fullscreen authenticated pages.
- `<custom-id>` — wrapped in a `layouts`-contributed component.

### Dashboard widgets

The dashboard is a 12-column grid of user-placed widgets. `dashboard_widgets`
registers a widget **type** so it appears in the widget library and users can
drop instances onto their own boards.

Don't confuse the two widget surfaces:

| | `widgets` | `dashboard_widgets` |
|---|---|---|
| Where it renders | a fixed host slot you name | anywhere the user drags it |
| Who decides position | the host | the user |
| Instances | one per slot | many, each independently configured |
| Use it to | enrich an existing page | offer a new building block |

```jsonc
"dashboard_widgets": [
  { "id": "git-activity",
    "name": "Git activity",
    "component": "GitActivityWidget",   // named export of your index module
    "category": "Operations",           // Metrics|Inventory|Operations|Utility
    "description": "Recent pushes across repositories",
    "w": 4, "h": 3, "min": [3, 2],      // default span / minimum span
    "default_cfg": { "limit": 6 } }
]
```

Ids are namespaced by the panel as `<plugin-slug>:<id>`, so two extensions can
both ship a `activity` widget without colliding.

Your component receives two props:

```jsx
export function GitActivityWidget({ widget, ctx }) {
  // widget.cfg — this instance's config, seeded from default_cfg
  // widget.w / widget.h — its current span, if you want to adapt density
  // ctx.range   — '1h' | '6h' | '24h' | '7d' | '30d' (the board's time range)
  // ctx.tick    — increments on each refresh; put it in your effect deps
  // ctx.serverVar — the board's selected server ('local' or a server id)
  // ctx.isAdmin, ctx.navigate
  return <div className="skw-list">…</div>;
}
```

Render into the space you're given: the frame's header, menu and resize handle
are the host's. A widget that throws is caught and replaced with an error tile
rather than taking the board down, but handle your own loading and empty states
— every core widget does.

### Tab-group contributions

Some core surfaces are **tab groups** (one shared `PageTopbar` + routed tabs,
rendered by `TabGroupLayout`). An extension can add a tab to one of these
groups instead of contributing a standalone page, so its feature sits where
users expect it (e.g. FTP as a tab of Files) and the group's chrome stays.

Two halves, both required:

```jsonc
"tabs":   [ { "group": "files", "to": "/ftp", "label": "FTP Server",
              "icon": "<rect …/>", "order": 1 } ],
"routes": [ { "path": "ftp", "component": "FtpServerPage", "group": "files" },
            { "path": "ftp/:tab", "component": "FtpServerPage", "group": "files" } ]
```

- The `tabs` entry puts the tab in the strip; the `group`-tagged routes render
  the page **inside** that group's `TabGroupLayout` (a `group` route ignores
  `layout`).
- `group` ids match the group's **sidebar item id**: `files`, `servers`,
  `monitoring`. The host also extends that sidebar item's highlight to the
  contributed tab's path, so the group stays lit. (Other groups can accept
  contributions later by passing `groupId` to their `TabGroupLayout` in
  `App.jsx`.)
- `icon` is raw inner-SVG markup (24×24 viewBox, stroked), like nav icons.
  `order` is an optional insertion index; default appends after the core tabs.
  Core tabs always win a `to` collision.
- Pages rendered in a tab group must not render their own top bar; publish
  actions via the `useTopbarActions()` outlet context like core tab pages do.

---

## The production frontend constraint

`frontend/src/plugins/contributions.js` discovers plugin UI modules at **build
time** via `import.meta.glob('../plugins/*/index.{js,jsx}')`. Two consequences you
must design around:

1. **Builtin (in-repo) extensions work in production** because their frontend
   halves are checked into `frontend/src/plugins/<slug>/` and compiled into every
   shipped bundle. "Install" just flips the runtime contribution envelope on.
2. **A third-party extension can now render on a production panel without a
   rebuild** — if it ships a prebuilt **ESM bundle** (see below). The panel serves
   a pre-built bundle and nothing rebuilds Vite, so a checked-in `.jsx` frontend
   still won't appear; but a `dist/index.mjs` bundle is fetched, integrity-checked,
   and blob-imported at runtime by the client loader. Its **backend half loads
   fine** either way.

### Runtime frontend delivery (prebuilt ESM bundle)

An installed extension whose manifest declares a `.mjs` `frontend_entry` is
delivered to the running panel **without a rebuild** (core-slim #39):

```jsonc
// plugin.json
{
  "frontend_entry": "dist/index.mjs",   // an ESM bundle (NOT a .jsx source file)
  "sdk_version": "^1.0.0"                // semver range the panel SDK must satisfy
}
```

How it works: at install time `plugin_service` records the bundle's sha256 (stored
under the panel-managed `_frontend_hashes` config key). The
`/api/v1/plugins/contributions` envelope then advertises a `frontends` descriptor
map — `{ slug: { entry, hashes, sdk_version } }` — plus the panel's `sdk_version`.
The client loader (`frontend/src/plugins/runtime/loader.js`) fetches the bundle
through the JWT-authed assets route, verifies the sha256, refuses it if its
`sdk_version` range doesn't cover the panel, then blob-imports it — resolving the
externalized bare specifiers through the host import map. Failures render a fail-soft
card on the extension's routes, never a white screen.

**Build convention** — externalize exactly the specifiers the host import map
resolves (`react`, `react-dom`, `react/jsx-runtime`, `react-router-dom`,
`serverkit-sdk`) so the extension shares the panel's singleton instances:

```js
// vite.config.js (extension repo)
import { defineConfig } from 'vite';
export default defineConfig({
  build: {
    lib: { entry: 'src/index.jsx', formats: ['es'], fileName: () => 'index.mjs' },
    outDir: 'dist',
    rollupOptions: {
      external: ['react', 'react-dom', 'react/jsx-runtime',
                 'react-router-dom', 'serverkit-sdk'],
    },
  },
});
```

Operators can disable runtime delivery panel-wide with the
`extensions.runtime_frontend` system setting (kill switch, default on); baked
builtins keep rendering via the build-time glob regardless.

### D5 — builtin frontends are pre-bundled (single source of truth)

For an in-repo extension, `builtin-extensions/<slug>/frontend/` is the **source of
truth**; `frontend/src/plugins/<slug>/` is a **generated artifact**. Never edit the
artifact by hand. Regenerate it with:

```bash
node scripts/sync-builtin-frontends.mjs           # source → artifact
node scripts/sync-builtin-frontends.mjs --check    # CI drift gate (fails on drift)
```

The `Extensions CI` workflow runs `--check` on every change to
`builtin-extensions/**` or `frontend/src/plugins/**`, so the two can never
silently diverge.

---

## Backend SDK (`app.plugins_sdk`)

Depend on the SDK, not on host internals — as long as this surface is stable,
core refactors won't break you.

```python
from flask import Blueprint, request, jsonify
from app.plugins_sdk import (
    db, jwt_required, current_user, audit, logger,
    ai, queue, notify, jobs,
)

my_bp = Blueprint('my_ext', __name__)
log = logger(__name__)

@my_bp.route('/things', methods=['GET'])
@jwt_required()
def list_things():
    user = current_user()
    return jsonify({'ok': True})
```

| Name | What it is |
|---|---|
| `db` | SQLAlchemy handle (`db.session`, `db.Model`). |
| `jwt_required`, `get_jwt`, `get_jwt_identity` | Flask-JWT-Extended re-exports. |
| `current_user()` | Resolves the JWT identity to a `User` row (or `None`). |
| `audit(action, target_type, …)` | Write an audit-log entry. |
| `logger(name)` | Module-scoped logger. |
| `ai` | Extend the core assistant (tools, context, prompts). |
| `queue` | Queue Bus SDK (publish/consume). |
| `notify` | Notifications SDK (`notify.send(event, to, data)`). |
| `jobs` | Jobs SDK (schedule/enqueue background work). |
| `sockets` | Register a status-guarded Socket.IO namespace (`/ext/<slug>`). |
| `store` | Per-plugin key/value storage — state without a model and a migration. |
| `deploys` | Register a deployment kind; get the Deploy Console, live logs and retry. |
| `backups` | Register a backup kind; get policies, retention, restore and the Protection panel. |
| `doctor` | Register a health check; it appears on the doctor page, repair button and all. |
| `search` | Register searchable entities; they appear in the command palette. |
| `agents` | Run a command on a managed server (gated by `agent.command:<action>`). |
| `require_permission(slug, cap)` | Capability gate — raises `PermissionDenied` if `cap` isn't declared in `permissions`, and records the call (allowed or refused). Only mediates what routes through it; see [Permissions & compatibility](#permissions--compatibility). |
| `panel_version()` | The panel's version string (for in-plugin compat checks). |

Errors follow the core convention: `return jsonify({'error': 'message'}), status`.

### Contributing to panel surfaces

Six of those surfaces work the same way: you register behaviour, the panel owns
the UI, the persistence and the error handling. Nothing on the frontend needs to
change for your contribution to appear.

```python
from app.plugins_sdk import store, deploys, backups, doctor, search, agents

# State, without adding a model + migration to core.
mine = store.for_plugin('serverkit-minecraft')
mine.set('world:1:seed', 8675309)

# Long-running work that someone will want to watch → the Deploy Console.
deploys.register('minecraft.restart', restart_handler)
deploys.start('minecraft.restart', steps=['Warn players', 'Save', 'Restart'],
              plan={'title': 'Restarting Overworld'})

# Something worth backing up → policies, schedules, retention, restore.
backups.register('minecraft.world', resolve=resolve, execute=execute, restore=restore)

# "Is my thing healthy?" → the doctor page, with a working Repair button.
doctor.register('minecraft', check_worlds, repair=back_up_stale)

# Your objects → the command palette. Scope rows to query.user yourself.
search.register('minecraft.world', find_worlds)

# The fleet. Declare agent.command:<action> in your manifest first.
agents.for_plugin('serverkit-minecraft').run(server_id, 'systemd:restart',
                                             {'unit': 'minecraft'})
```

Namespace whatever you register after your plugin (`minecraft.world`) — bare
names belong to core and are refused. Each registry's module docstring is the
detailed contract; the shapes they hand back are normalised and capped by the
panel, so a malformed contribution degrades rather than breaking the surface it
appears on.

### Blueprint registration & the disable guard

`entry_point` (`module:bp_var`) is imported from `app.plugins.<slug>.<module>` and
registered at `url_prefix`. A `before_request` guard is attached automatically:
when the plugin's DB status isn't `active`, its routes return **503** — so
disabling an extension actually stops serving it, even though Flask can't
unregister a blueprint from a running app.

Keep the same `/api/v1/<feature>` prefix when a feature moves from core into an
extension (decision D9) so existing agents/scripts/UI keep working.

---

## Lifecycle hooks

Declared under `lifecycle`; resolved as `module:func` under `app.plugins.<slug>`.
Each hook receives the `InstalledPlugin` row as its single positional arg.

- `install` — runs **after** files are extracted (e.g. seed default rows).
- `upgrade` — runs when installing a version different from the installed one.
- `uninstall` — runs **before** files are removed. Receives whether the caller
  requested a data purge (see [Data policy](#data-models--policy)).

Hook failures are logged and swallowed — hooks are convenience, not correctness.

---

## Data models & policy

Raw `db` access works, but for tables you own, declare a `models` entry point so
the platform can create/upgrade/clean them up:

```python
# app/plugins/<slug>/models.py
def register(ctx):
    """Return SQLAlchemy model classes owned by this extension.
    Table names are prefixed ext_<slug>_ automatically."""
    ...
```

- Install creates the tables; the `upgrade` hook runs on version change.
- Uninstall offers **keep-data** vs **purge** (mirrors the installer's `--purge`
  semantics); the choice is passed to the `uninstall` hook (`func(plugin, purge=...)`)
  and, on purge, drops the `ext_<slug>_*` tables.

### The core data seam (extension uses CORE tables)

The `ext_<slug>_*` mechanism is for extension-owned schema. The deliberate
exception — **core data seam** (plan 52 D1) — is an extension whose tables are
core Alembic-managed because they carry live data that predates the extraction
and are entangled with core features. Canonical example: **serverkit-wordpress**
— `WordPressSite`, `WordPressVulnerability`, `WordPressUpdateRun`,
`WordPressReport` live in `app/models/wordpress_site.py` (core migrations own
their lifecycle) and the standalone extension imports them:

```python
from app.models.wordpress_site import WordPressSite
```

Rules of the seam: the extension never creates/migrates those tables (no
`models` entry for them, no `ext_` rename); core never imports the extension —
it reaches it through a lazy bridge (`app.services.wordpress_bridge`) or
`get_installed_extension_attr`, and through registration seams the extension
fills (`core_hooks`). Absent extension = feature absent, gracefully. The same
seam covers `StatusPage`, `Tunnel`/`ExposedService`, and `CloudServer` (owned
by their respective extensions' features but schema-core).

## Background jobs & schedules

Declare handlers and recurring jobs in the manifest; they wire into the Jobs SDK
on install and **pause automatically when the plugin is disabled**:

```jsonc
"jobs":      [ { "kind": "myext.reindex", "handler": "jobs:reindex" } ],
"schedules": [ { "name": "myext-nightly", "kind": "myext.reindex", "cron": "0 3 * * *" } ]
```

## Core hooks (`core_hooks`)

Some core features are engines with a registration seam — backup target types
(`app.services.backup_kind_registry`), the event-type catalog
(`app.services.event_service.register_event_types`), provider-owned app
templates (`TemplateService.register_template_provider`). Declare a zero-arg
function that fills them and the platform calls it at install **and on every
boot** while your extension is active (so it must be idempotent):

```jsonc
"core_hooks": "core_hooks:register"
```

Core keeps the engine; your extension supplies the entry. An extension that is
absent/disabled at boot never registers, so its target types, event types, and
template cards simply don't exist — that is the intended graceful degradation
(plan 52 D4), not an error. Reference implementation: the `serverkit-wordpress`
repo's `backend/core_hooks.py` (the `wordpress_site` backup kind, the
`wordpress.*` event types, and the `wordpress`/`wordpress-external-db` template
provider).

## Config (`config_schema`)

Declare a `config_schema` in the manifest and the Marketplace renders a
**Configure** form on the installed plugin (Installed tab). Values persist on
the panel and your backend reads them with `plugins_sdk.config(slug)`:

```jsonc
"config_schema": {
  "api_key":         { "type": "string", "secret": true, "description": "…" },
  "refresh_seconds": { "type": "integer", "default": 60 },
  "mode":            { "type": "string", "enum": ["fast", "thorough"] },
  "enabled":         { "type": "boolean", "default": true }
}
```

- Top-level keys are the field names (a JSON-schema-style `properties` wrapper
  also works). Supported: `string` / `number` / `integer` / `boolean`, `enum`
  (renders a select), `default`, `title`, `description`, and `secret: true`
  (renders a password input).
- Values may hold secrets, so they are **not** part of the plugin's public
  dict — only the admin-gated `GET/PUT /api/v1/plugins/<id>/config` serves
  them, and `plugins_sdk.config()` is read-only.

```python
from app.plugins_sdk import config
key = config('my-extension').get('api_key')
```

## Real-time (Socket.IO)

Declare `"socket_entry": "sockets:register"`; the function returns
`{event: handler}` and the panel registers them on `/ext/<slug>`, status-guarded
(a disabled plugin's namespace refuses new connections):

```python
# app/plugins/<slug>/sockets.py
def register():
    def on_connect():  ...
    def on_subscribe(data):  ...
    return {"connect": on_connect, "subscribe": on_subscribe}
```

## Permissions & compatibility

`permissions` is a **consent signal**, and for most capabilities that is all it is.
Be precise about which half applies, because the difference matters to anyone
deciding whether to trust an extension.

**What is actually mediated.** `require_permission(slug, cap)` raises
`PermissionDenied` unless `cap` is declared. That gate is real, but it only fires
where something *calls* it. Today exactly one capability is routed through it
unavoidably:

| Capability | Mediated? | Why |
|---|---|---|
| `agent.command:<action>` | **Yes** | The SDK is the only way to reach an agent, so every use passes the gate. Uses and refusals are recorded and shown on the extension's detail page. |
| `docker`, `shell`, `filesystem`, `network`, `db` | **No** | The SDK exposes no helper for these (and `db` is raw SQLAlchemy), so an extension imports the host module directly and no in-process check is involved. |

So declaring `docker` does **not** stop an extension from using Docker, and *not*
declaring it does not stop it either. What declaring does is tell the operator, at
install time, what the extension says it needs — and let them refuse.

**Why the panel says "cannot be observed".** The extension detail page compares
declared permissions against observed use. For `agent.command:*` an unused
declaration is real evidence of over-asking. For the five host capabilities the
panel reports that use *cannot be observed* rather than showing a zero: absence of
evidence is not evidence of absence, and a "never used" badge there would imply an
enforcement boundary that does not exist.

Declare honestly regardless. The consent dialog is what the operator agrees to, and
under-declaring to look harmless is the behaviour the curated registry exists to
catch. True out-of-process sandboxing is deliberately out of scope — see ADR 0001 /
plan #42 for the posture.

**Python dependencies.** A `requirements.txt` in your zip is **not** installed by
default: pip would run with the backend's privileges and a `setup.py` hook is
arbitrary code. The file is saved next to the installed extension and surfaced on
its detail page so an operator can review and install it deliberately. Operators
opt in with `SERVERKIT_ALLOW_PLUGIN_PIP=1`. Design your extension to degrade
clearly when an optional dependency is absent rather than crashing on import.

- `min_panel_version` / `max_panel_version` are enforced at install **and** update
  for every source (URL/upload/local/builtin/registry).

---

## Extending the AI assistant

The assistant is core (decision D7) — you never rebuild it, you extend it. Declare
an `ai` block and ship `app/plugins/<slug>/ai.py`:

```python
from app.plugins_sdk import ai

def register(reg):                       # reg is a PluginToolBinder
    @reg.tool(rbac_feature="git", rbac_level="read")
    def list_branches(repo: str) -> list:
        """List branches in a repo. Args: repo: repository slug."""
        from app.services.git_service import GitService
        return GitService.list_branches(repo)
```

Tools are namespaced `<slug>__<name>`, RBAC-gated per tool, and write tools
(`is_write=True`) always route through confirmation.

---

## Install sources

| Source | How | Endpoint |
|---|---|---|
| Builtin (in-repo) | One-click from the Marketplace | `POST /api/v1/plugins/builtin/<slug>/install` |
| GitHub / release / zip URL | Paste a URL | `POST /api/v1/plugins/install` |
| Uploaded zip | Upload (≤ 50 MB) | `POST /api/v1/plugins/install-upload` |
| Local path (dev) | Panel-host path | `POST /api/v1/plugins/install-local` |
| Registry | Curated index (checksum-verified) — see [EXTENSIONS_REGISTRY.md](EXTENSIONS_REGISTRY.md) | via Marketplace Browse |

All sources funnel through one install pipeline (`_install_from_buffer`) so
behavior is identical. Zip-slip is rejected (absolute paths, `..`, escaping
entries). Python `requirements.txt` is **not** installed unless the operator sets
`SERVERKIT_ALLOW_PLUGIN_PIP=1` (installing runs pip with the backend's
privileges).

### Installable straight from GitHub

Your extension is installable from a raw GitHub URL with **no registry entry
required** — that's the "paste a repo, get a safe install" path. Make it work
by honoring this contract:

- **`plugin.json` at the archive root.** The installer reads the manifest from
  the top level (GitHub zipball nesting is handled). No `plugin.json` at the
  root is the single most common failure.
- **Prefer a release with a `.zip` asset.** Tag a release and attach your
  packaged `.zip`; the installer picks the `.zip` asset over the source
  zipball, giving a reproducible, checksum-pinnable download. With no release,
  it falls back to the default-branch source archive and the preview **warns**.
- **Accepted forms:** a repo URL, a release URL, a direct `.zip`, or the
  shorthand `owner/repo` and `owner/repo@tag`.

Before anything lands, the panel **previews** the install: it resolves and
downloads the source, reads your manifest, and shows the user a consent card
with the version, the **declared `permissions`** (the same "This extension
requests:" block registry entries show), panel-version compatibility, and any
warnings (no release found, slug already installed, version-gate mismatch). The
subsequent install is pinned to the exact previewed bytes via `sha256`, so what
is installed is byte-identical to what was previewed. Declaring your
`permissions` honestly is therefore what the user sees and agrees to — under- or
over-declaring both read badly at the consent step.

Private repos and GitHub's anonymous rate limit are handled by the optional
`SERVERKIT_GITHUB_TOKEN` env var (Bearer auth, attached only to GitHub hosts,
never logged). See [`POST /api/v1/plugins/preview`](EXTENSIONS_REGISTRY.md) and
the site's [Installing](https://serverkit.ai/docs/extensions/installing) guide.

### Release signing (ed25519)

Release zips can carry a **detached ed25519 signature** so the panel proves
*origin*, not just integrity (a sha256 in the index only says the bytes match
the index — whoever can edit the index can edit the hash beside it). The scheme
is deliberately minimal (plan 55, D3): no PKI, no key servers.

**Signature format** — a minisign-style envelope, base64 of 74 bytes:

```
"ED" (2 bytes) || key_num (8 bytes) || ed25519 signature (64 bytes)
```

- `ED` marks a *pure* ed25519 signature over the raw zip bytes.
- `key_num` is `sha256(public_key)[:8]`, binding the envelope to the exact
  key that made it — a `publisher_key_id` cannot be pointed at a different
  pinned key than the one that signed.

**Sign a release** with `scripts/sign-extension.mjs`:

```bash
# once per publisher — keep the key file PRIVATE and out of git
node scripts/sign-extension.mjs keygen --key-id my-publisher --out <safe dir>

# per release — writes <bundle>.zip.minisig and prints the index fields
node scripts/sign-extension.mjs sign my-ext-1.0.0.zip --key <safe dir>/my-publisher.signing-key.json
```

Ship the `.minisig` beside the zip as a release asset (the GitHub preview flow
looks for `<zip URL>.minisig` automatically). For registry-listed extensions,
paste the printed `signature` + `publisher_key_id` into the index entry
(schema v3; v1/v2 indexes without them stay valid — those entries are simply
treated as unsigned).

**Key model.** The panel pins publisher public keys in
`backend/app/data/extension_signing_keys.json` (the `serverkit-official`
first-party key ships there). Operators can trust additional publisher keys via
`SERVERKIT_TRUSTED_EXTENSION_KEYS` (path to a JSON file with the same shape) —
that file is also the rotation path: pin the new key, sign new releases with
it, remove the old entry once nothing references it.

**What the panel does with a signature** (verify logic:
`app/services/signing_service.py`):

| Verdict | Meaning | Install behavior |
|---|---|---|
| `verified` | Signature valid under a pinned key | Installs; no extra friction |
| `unsigned` | No signature present | Installs behind the existing consent surfaces (preview card badge, registry risk dialog) — never a hard block. For **first-party** registry entries it is a 409 consent gate (possible downgrade); community **reviewed** entries stay exempt because the review stamp already binds a maintainer verdict to the artifact's exact sha256 |
| `untrusted_key` | Signed, but the publisher key isn't pinned | Registry: 409 consent ("install anyway"); manual: consent card warns |
| `invalid` | Malformed envelope, key-id mismatch, or verify failed | **Hard failure, always.** Acknowledgment can never override a bad signature |

The verdict is stamped on the installed extension (panel-managed `_signature`
config key, surfaced as `signature` in the plugin API dict) so origin
verification stays visible after install. The sha256 runtime-frontend hash
check is unaffected — signatures cover the zip, `_frontend_hashes` still pins
the served `.mjs` bundle bytes.

Honesty note (D2): a signature verifies *when present*. An unsigned
first-party registry entry installs only behind the explicit 409 consent step
(acknowledge-risk), and the same gate covers the update path — but the
acknowledgment itself still rests on the index's integrity (TLS + the
registry repo's PR review) until every first-party release is signed.

### Docker note

A dockerized backend only sees `/app`, not the host's `frontend/` tree. To install
an extension that ships a frontend on such a panel, bind-mount the host's
`frontend/src/plugins` into the container and set
`SERVERKIT_FRONTEND_PLUGINS_DIR`, or run the backend natively for development.

---

## Converting a core page into a builtin extension (recipe)

Proven with `serverkit-git`; automated by the one-shot upgrade auto-install
(so existing users never lose a page). Steps:

1. Create `builtin-extensions/<slug>/plugin.json` with the `contributions`
   (nav / routes / page_titles / command_palette) that reproduce the page.
2. Create `builtin-extensions/<slug>/frontend/index.jsx` — usually a thin
   re-export of the existing host page while the backend API stays in core:
   ```jsx
   import GpuMonitor from '../../pages/GpuMonitor';
   export function GpuMonitorPage() { return <GpuMonitor />; }
   ```
3. Remove the hardcoded entries from `App.jsx` (import + `<Route>` + `PAGE_TITLES`),
   `sidebarItems.js` (or the group `*Tabs.jsx`), and `CommandPalette.jsx`.
4. Pre-bundle: `node scripts/sync-builtin-frontends.mjs`.
5. Lint the manifest: `node scripts/new-extension.mjs --validate
   builtin-extensions/<slug>` — the same shape rules are enforced at install
   time, so catching a malformed contribution here saves a failed install.
6. The backend API stays core for now (two-speed extraction, decision D2). Full
   backend extraction happens only after the Phase 3 primitives exist.

Existing panels auto-install converted builtins once on upgrade (a marker in
settings) so nothing disappears; fresh installs see them in the Marketplace.

### Second speed — moving the backend out too (plan 47)

Once a converted page has settled as a frontend-only extension, its backend
blueprint + service can leave core:

1. `git mv backend/app/api/<feature>.py builtin-extensions/<slug>/backend/<module>.py`
   and the same for its service(s). Rewrite imports: **core** imports stay
   absolute (`from app.middleware.rbac import …`), **sibling** extension modules
   become relative (`from .<sibling> import …`).
2. Add `backend/__init__.py` exposing the blueprint, and set the manifest's
   `entry_point` (`"<module>:<bp>"`) + `url_prefix` (**unchanged** so frontend
   API clients don't move).
3. Deregister it from `backend/app/__init__.py` (drop the import + `register_blueprint`).
4. Keep any **model** used by the extension in `backend/app/models/` (extensions
   can't run migrations — G2). The extension imports it.
5. If a **core** code path calls into the now-extracted service (a job handler,
   the agent gateway), reach it through
   `plugin_service.get_installed_extension_attr(slug, module, attr)` so it
   no-ops cleanly when the extension is absent.
6. Ensure the slug is in `extension_migration.CONVERTED_BUILTIN_SLUGS`. On an
   upgraded panel that installed the extension **frontend-only** (its API used
   to come from core), `run_backend_acquisition()` force-reinstalls once to
   re-acquire the now-extracted backend — otherwise the API would vanish.

Landed this way: `serverkit-ftp`, `serverkit-cloud-provision`,
`serverkit-remote-access`, `serverkit-status`.
