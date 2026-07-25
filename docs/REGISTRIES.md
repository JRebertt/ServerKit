# Registries

ServerKit publishes some of its catalogs as standalone repositories that panels
read over the network, so entries can ship without a panel release. Three exist
today:

| Registry | Repo | Bundled in the panel? |
|---|---|---|
| Extensions | [`serverkit-extensions`](https://github.com/jhd3197/serverkit-extensions) | builtins only; the rest install on demand |
| Themes | [`serverkit-themes`](https://github.com/jhd3197/serverkit-themes) | 17 bundled, gallery adds more |
| App templates | [`serverkit-templates`](https://github.com/jhd3197/serverkit-templates) | all 106 bundled, registry adds/updates |

This document exists because "should X be a registry too?" is a question that
otherwise gets re-asked every few months. Most of the time the answer is no.

## The test

A catalog earns a registry only when **all three** hold:

1. **It changes faster than the panel releases.** If new entries naturally
   arrive with the feature work that consumes them, a registry buys nothing.
2. **It is data, not code.** A new entry must work on an *existing* panel with
   no code change. If using it requires a new service method, a new job kind, or
   a new UI surface, it is code wearing a catalog's clothes.
3. **Someone outside the release cycle would contribute.** If only the
   maintainers will ever add entries, a directory in this repo is simpler and
   reviews the same way.

Fail any one, and extraction adds a network dependency, a second release
process, and a version-skew surface in exchange for nothing.

### The failure mode to avoid

The expensive mistake is extracting a catalog that fails test 2. Panels that
have not upgraded keep reading the registry forever. Publish an entry that needs
new panel code, and every old panel either ignores it (best case) or shows a
broken item it cannot install (worst). At that point the registry needs its own
`min_panel_version` gate — which is exactly why `serverkit-extensions` has one,
and exactly the complexity you do not want unless the catalog earns it.

## Why the three qualified

- **Extensions** are independently versioned code artifacts with permissions and
  a `min_panel_version` gate. They are the archetype: third-party authored,
  released on their own cadence, installed at runtime.
- **Themes** are pure token maps — data by construction, contributed by people
  who will never open a panel PR, and worthless if shipping one requires a
  release.
- **App templates** are declarative Compose specs. New self-hosted apps appear
  constantly and each is ~2 KB of YAML that an existing panel already knows how
  to install. `TemplateService` has always resolved
  `<repo_url>/index.json` + `<repo_url>/templates/<id>.yaml`; the registry is
  just the other end of a contract the panel already had.

Note the pattern: **bundled and registry are not exclusive.** Templates and
themes ship inside the panel *and* have a registry. The bundle is the offline
floor — air-gapped installs, fresh installs with no network, and any day
GitHub is unreachable — while the registry is the growth path. Only extensions
lean on the registry as the primary source, because they are large and optional
by nature.

## What was assessed and rejected

| Catalog | Where | Verdict |
|---|---|---|
| Server templates | `ServerTemplateService.TEMPLATE_LIBRARY` | **No.** 12 entries, stable, and operators already create their own via `create_template()` into the DB. The library is a seed, not a catalog. |
| Notification events | `app/notifications/catalog.py` | **No.** Fails test 2 — an event type is only real if panel code emits it. A registry entry with no emitter is a dead row. |
| AI providers | `ai_service.CURATED_PROVIDERS` | **No.** Each entry is bound to a Prompture driver; adding one without the driver produces a provider that cannot connect. |
| DB tuning settings | `db_config_tuner_service.CURATED_SETTINGS` | **No.** Fails test 3 — tuning knobs track the engines the panel supports, and only maintainers will touch them. |
| Sanitization profiles | `models/sanitization_profile.BUILTIN_PROFILES` | **No.** Consumed by code paths that must understand each profile. |
| Agent survey probes | `app/data/survey_probe_catalog.yaml` | **No.** A probe is only meaningful if the agent implements its kind, so it is gated by the agent's release, not the panel's. |
| Build packs | `buildpack_service` | **No.** Not a catalog at all — it generates Dockerfiles and compose from a build plan. That is code. |

## Open candidate: malware signatures

**YARA rules are the one remaining catalog that passes all three tests, and they
have no update path today.**

`YaraScanService.BUILTIN_RULES` (16 curated rules, mirrored in
`yara_rules/webshells.yar`) ships inside the panel and changes only when the
panel is released. Webshell signatures are the textbook case for out-of-band
updates — a new obfuscation family is worth pushing the day it is seen, not the
next release.

This matters more than it used to. The container image now builds **without
ClamAV by default** (`ARG INSTALL_CLAMAV=false` — see the `Dockerfile`), and
ClamAV was the component with a self-updating signature feed via `freshclam`.
In a default container, YARA is the *only* malware detection, and its rules are
frozen at release time.

Operators can already drop custom `.yar` files into
`YaraScanService.CUSTOM_RULES_DIR` (`/var/serverkit/security/yara-custom`, real
`yara` CLI required), so the local extension point exists. What is missing is a
curated upstream feed that updates itself.

Not built. Noted here so the decision is deliberate rather than forgotten.
