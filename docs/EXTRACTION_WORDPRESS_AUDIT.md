# WordPress extraction — boundary audit (Phase 5, #37)

**Status:** ✅ EXTRACTED (plan 52 Phase 5, 2026-08-05). WordPress lives in the
standalone `serverkit-wordpress` repo (backend + runtime-ESM frontend +
extension-owned tests + first-party release pipeline) and distributes through
the registry; the setup wizard offers it from the bundled index entry. Its
schema stays core forever via the documented **core data seam** (D1 — see
EXTENSIONS.md "Data models & policy"). This audit remains as the historical
boundary record.
**Verdict (historical):** extractable, but WordPress had **real core hooks**
that were inverted/guarded first (plan 52 Phase 3, the `core_hooks` seam).

---

## Cut list — moves into `builtin-extensions/serverkit-wordpress/`

### Backend (move together — WP-internal chain is self-contained)
| File | ~Lines |
|---|---|
| `app/api/wordpress.py` | 1634 |
| `app/api/wordpress_sites.py` | 528 |
| `app/api/environment_pipeline.py` (registered under the `wordpress` guard) | — |
| `app/services/wordpress_service.py` | 2676 |
| `app/services/git_wordpress_service.py` | 651 |
| `app/services/wordpress_env_service.py` | 530 |
| `app/services/wordpress_plugin_library_service.py` | 508 |
| `app/services/wp_analytics_service.py` | 262 |
| `app/services/wp_reports_service.py` | 363 |
| `app/services/wp_security_service.py` | 201 |
| `app/services/wp_update_service.py` | 251 |
| `app/services/wp_vulnerability_service.py` | 318 |

Blueprints keep their `/api/v1/wordpress*` prefixes (D9).

### Models
- `WordPressSite`, `WordPressVulnerability`, `WordPressUpdateRun`, `WordPressReport`
  (`models/wordpress_site.py`), `WordPressCustomPlugin` (`models/wordpress_custom_plugin.py`).

### Frontend
- Pages `WordPress.jsx`, `WordPressDetail.jsx`, `WordPressProjects.jsx`,
  `WordPressProject.jsx`, `WordPressPluginLibrary.jsx`; the whole
  `components/wordpress/` dir; SCSS `_wordpress*.scss`. Remove route/title/nav/
  palette entries (they're already `ModuleRoute`-guarded, which eases the swap).

---

## STAYS CORE — do not move

| Asset | Why |
|---|---|
| **Backup/protection engine** (`backup_policy_service.py`, `models/backup_policy.py`) | Engine stays core; it keeps a WP hook (see below). Only the WP *panels* move. |
| **Fail2ban jail engine** (`fail2ban_jail_service.py`) | Generic jail management is core. Only the WP-specific bits move (below). |
| **`DatabaseSnapshot` + `SyncJob`** (currently colocated in `models/wordpress_site.py`) | Generic snapshot/sync models — `db_sync_service.py:941` imports `DatabaseSnapshot`. **Pre-req: relocate to a neutral models module** before the move. |
| **Event catalog** (`event_service.py:51-59,73-74`) | Core catalog hardcodes `wordpress.*` event types — decouple the catalog entries (extension registers its own event types via SDK). |

---

## Couplings to invert / guard BEFORE extraction (the hard gate)

1. **Eager import** — `app/services/__init__.py:8` eagerly imports `WordPressService`.
   Must become lazy or removed, or core boot always pulls the WP stack.
2. **Backup engine WP branch** — `backup_policy_service.py:341,719` +
   `models/backup_policy.py` reference `target_type == 'wordpress_site'`. Invert to
   a registered backup-target hook the WP extension provides (keep the engine core).
3. **Fail2ban WP specifics** — `fail2ban_jail_service.py:53-57` (`FILTER_CONTENT` WP
   login/xmlrpc regex) + `enable_wp_jail()` (line 185). Refactor the core service to
   a generic `enable_jail(filter=...)` and let the WP extension supply the filter,
   OR move `enable_wp_jail` + filter into the extension.
4. **Lazy cross-imports** (already lazy — becomes SDK calls): `preview_service.py:319,361`,
   `webhook_service.py:423`, `environment_pipeline_service.py:1471`, `api/apps.py:2103`,
   `jobs/builtin_handlers.py:176-178`.
5. **`DatabaseSnapshot`/`SyncJob` relocation** (above).
6. **Event catalog decoupling** (above).
7. **`status_page_service.py:141`** references `wordpress_site_id` — a data ref;
   confirm it degrades gracefully when WP is uninstalled.

---

## Extraction steps (#38), in order

1. Land all pre-reqs (1–7 above) as small, individually-tested core refactors that
   keep the app working WITH WordPress still core (invert couplings first).
2. Move backend services + blueprints into the extension (keep prefixes, D9);
   models via #24 (or two-speed as core tables initially).
3. Move frontend + manifest; pre-bundle (D5).
4. Ship it as **bundled + default-installed + uninstallable** (D4): seed-install on
   every panel (fresh and upgrade), unlike niche verticals.
5. Prove parity: existing WP test suites run against the extension unchanged; a
   panel with WordPress uninstalled loads no `wordpress*` blueprint and backups/
   fail2ban/events still function.

**Risk:** HIGH (largest move; 7 couplings to invert). This is why Email (#32) goes
first — it validates the model/jobs/socket/purge machinery on an isolated stack
before WordPress's coupled one.
