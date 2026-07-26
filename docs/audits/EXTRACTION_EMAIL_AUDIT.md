# Email extraction — boundary audit (Phase 4, #31)

**Status:** ✅ Audit complete AND extraction shipped (#32–#35, `serverkit-email`).
**Verdict:** the mail-**server** stack is cleanly extractable. Notifications SMTP is
independent and keeps working without the extension.

> **Deviations discovered during execution (vs. this audit's first draft):**
> 1. **`postfix_service` stays core.** The audit listed it as "moves (import only)",
>    but `email_relay_service` (core, notifications-side) *actively uses*
>    `PostfixService.configure_relay/disable_relay/get_status`. Postfix is shared
>    outbound-relay infra, so it stays core; the extension imports it (extension→core).
> 2. **Email models stay core.** Kept in `app/models/email.py` (the audit's sanctioned
>    two-speed option). This makes the `DNSProviderConfig` relocation a non-issue
>    (it stays core with the other email models) and avoids a risky data migration —
>    the server stack has no external model importers.
> 3. **Frontend uses the re-export pattern** (page stays in `pages/Email.jsx`, the
>    extension owns the route) — same as serverkit-git/gpu/workflows — rather than
>    physically relocating a 1000-line component and rewriting its imports.
>
> Net moved: `api/email.py` + `email_service`/`dovecot`/`dkim`/`spamassassin`/`roundcube`
> (6 files, intra-extension relative imports; core imports absolute). Core lost the
> mail-server API and 5 services; the "Email" module toggle became the extension itself.

This is the hard gate the plan required before moving any code (#32). It maps
every touchpoint so the move is mechanical.

---

## Cut list — moves into `builtin-extensions/serverkit-email/`

### Backend services (move as a unit — no external importers)
| File | ~Lines | Notes |
|---|---|---|
| `app/api/email.py` | 466 | blueprint `email_bp`; keep `/api/v1/email` prefix (D9) |
| `app/services/email_service.py` | 546 | orchestrator |
| `app/services/postfix_service.py` | 429 | MTA |
| `app/services/dovecot_service.py` | 351 | IMAP/POP |
| `app/services/dkim_service.py` | 270 | OpenDKIM |
| `app/services/spamassassin_service.py` | 253 | |
| `app/services/roundcube_service.py` | 213 | webmail |

Grep confirms **zero non-email backend files import** postfix/dovecot/roundcube/
spamassassin/dkim/email_service — the server stack is isolated.

### Models that move
- `EmailDomain`, `EmailAccount`, `EmailAlias`, `EmailForwardingRule`, and the
  legacy `EmailRelayConfig` from `app/models/email.py`.

### Frontend that moves
- `pages/Email.jsx` + `styles/pages/_email.scss`; remove its route/title/nav/
  palette entries (App.jsx `/email` + `ModuleRoute`, sidebarItems `email` item,
  CommandPalette). Pre-bundle per D5.

---

## STAYS CORE — do not move

| Asset | Why |
|---|---|
| `app/models/email_provider.py` (`EmailProviderConnection`) | Owned by **Notifications** (`notifications/providers.py`, `channels/email.py`). Outbound notification SMTP must work without the mail server. |
| `app/services/email_relay_service.py` | A shim over the notifications provider model, not the MTA. Legacy `EmailRelayConfig` is migrated into `EmailProviderConnection` at boot. Keep with notifications/connections. |
| `DNSProviderConfig` (currently in `app/models/email.py:138`) | A **general DNS-provider** model that the core DNS stack imports (`dns_provider_service.py`, `dns_zone_service`, `services/dns/cloudflare.py`, `cloudflare_service`). **Pre-req: relocate it to a neutral module** (e.g. `models/dns_provider.py`) *before* moving `models/email.py`, or the DNS stack breaks. |
| `pages/DeliveryLog.jsx` (`/admin/notifications`) + `components/EmailProviders.jsx` | Notifications delivery log, not the mail server. |
| `Fail2ban`, firewall, backups, monitoring | grep: no coupling to email services. |

---

## Couplings to invert / guard before the move

1. **Boot migration hook** — `app/__init__.py:487` calls
   `EmailRelayService.migrate_legacy_config()`. This is the *only* core→email
   touch. Since `email_relay_service` stays core (it's notifications-side), this
   is actually fine to keep — confirm it doesn't import the MTA services at import
   time (it imports `postfix_service` at `email_relay_service.py:23`; **that import
   must be made lazy/removed** so core boot doesn't pull the MTA stack).
2. **`DNSProviderConfig` relocation** (above) — the single blocking pre-req.
3. **`email_service` → DNS** (`api/email.py:6,106` → `DNSProviderService.deploy_email_records`)
   is email→core (correct direction): becomes an SDK call from the extension. The
   email-specific method `deploy_email_records` may stay in core DNS or move with
   the extension and call generic record-creation — decide during #32.

---

## Extraction steps (#32–#35), in order

1. **Pre-req:** relocate `DNSProviderConfig` out of `models/email.py`; make
   `email_relay_service`'s `postfix_service` import lazy.
2. **#32 backend move:** create `builtin-extensions/serverkit-email/backend/`;
   move the 7 services + `email_bp` (keep `url_prefix=/api/v1/email`); migrate the
   email models via the #24 `models` entry point (or keep as core tables during a
   two-speed step — the server stack has no external model importers, so either
   works). Remove `email_service` from any eager import path.
3. **#33 frontend move:** `Email.jsx` + SCSS → extension `frontend/`, manifest
   nav/route/title; delete the core entries; pre-bundle.
4. **#34 upgrade auto-install:** add `serverkit-email` to
   `extension_migration.CONVERTED_BUILTIN_SLUGS`, but gate on *actual* mail usage
   — the module toggle (`module_email_enabled`) or presence of postfix state — so
   only boxes that ran mail get it auto-installed; others see it in the Marketplace.
5. **#35 prove it:** assert a fresh panel without the extension loads no email
   blueprint (`/api/v1/docs` route dump has no `/api/v1/email`); install reaches
   parity (the existing email tests run against the extension); uninstall --purge
   leaves no `ext_serverkit-email_*` tables.

**Risk:** LOW. Isolated stack; the only real pre-req is the `DNSProviderConfig`
relocation. Email goes first (before WordPress) precisely because it's this clean.
