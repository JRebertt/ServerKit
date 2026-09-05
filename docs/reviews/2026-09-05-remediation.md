# ServerKit review remediation — 2026-09-05

This records the implementation following [the original review](2026-09-05-serverkit-review.md). The original report describes the pre-fix checkout and remains historical evidence. The changes are committed locally on `dev`; no push or production deployment was performed.

## Local implementation commits

| Commit | Scope |
| --- | --- |
| `c8c93a8e` | Authentication, scoped API keys, passkeys and session revocation |
| `785c5780` | Socket subscriptions and authorized event delivery |
| `6bf34903` | AI resource access, redaction and chat limits |
| `c62358de` | Settings tables, access review and browser regressions |
| `da0f1814` | Security CI coverage and narrow Bandit exceptions |

The review, historical reproduction probes and this handoff are recorded in a separate documentation commit.

## Implemented

| Review item | Change |
| --- | --- |
| MFA/login-link bypass | Pending tokens expire after five minutes and fail the common JWT policy. Login-link management requires a completed browser session, and redemption honors the target account's MFA policy. |
| Scoped API-key escalation | Keys cannot mint browser credentials. Restricted keys fail closed when the endpoint lacks an explicit scope declaration, and declared scopes are checked independently of the owner's role. |
| Socket authentication and room isolation | Require a valid access-token session; authorize user, application, server, deployment and run subscriptions. Revalidate sessions and resource access before delivery, including account/session revocation. Preserve authorized terminal and job streams. |
| AI resource authorization | Built-in tools receive the actual caller, reuse application/workspace visibility, return selected metadata, and recheck authority after write confirmation. Host-wide privileged tools require an administrator. |
| Password changes, disablement and logout | Password changes require the current password, or recent authentication for accounts without a local password. Password changes and account disablement invalidate earlier sessions; logout persistently revokes the current browser's access/refresh family. |
| AI protection gaps | Recursively filter structured read and write results, apply deterministic secret filtering, and return a visible error when enabled protections fail. Sanitize model context and restored conversations too. |
| Settings table backgrounds | Users and Invitations wrappers now own an explicit theme surface. Verified with actual components in Chromium in dark and light themes. |
| Access-review UI | Show MFA, passkey enrollment and sign-in provider; add an active-admins-without-TOTP view; use locale-aware dates, shared deletion confirmation, pending-action guards and visible invitation errors. |
| Regression coverage | Add authentication, API-key, socket, AI and passkey boundary tests; add a browser job for Settings surfaces and interaction states. |

Cross-review also found and repaired passkey compatibility with pinned WebAuthn 2.5.0. Registration and passwordless authentication now require authenticator user verification. Regression tests use real cryptographic signatures with synthetic credentials, including refusal of assertions without user verification.

## Additional hardening

- AI chat accepts at most 128 KiB request bodies and 16,000-character message/context limits. The panel permits one active turn per user and eight panel-wide. Streaming queues are bounded and cancellation-aware. These are concurrency and input limits, not aggregate billing quotas.
- Security CI now includes weekly/manual runs, extension sources and requirement files, a production npm audit, full Bandit report artifacts, and a narrow reviewed exception mechanism. Broad Bandit category skips were removed. Two existing FTP compatibility findings remain explicitly documented and tied to their function fingerprint.
- Browser coverage exercises active/disabled/filtered users, loading, empty/error states, table surfaces in both themes, guarded deletion, and invitation revoke failure with pending controls.

## Upgrade behavior

- Apply Alembic migration `097_user_auth_version` with the normal application upgrade. It adds the user authentication version and persistent revoked-session records; existing-install, fresh-install and downgrade paths have regression coverage.
- Existing JWTs intentionally become invalid. Users must sign in again after upgrading.
- Restricted API keys now return 403 for endpoints without `@require_scope`. Most previously API-key-capable routes have no declaration, so integrations using restricted keys need a reviewed endpoint scope policy. Do not broaden keys to full access as a substitute for defining that policy.
- Wildcard `*` and legacy empty-scope keys retain their existing full-access meaning, subject to the owner's role. JWT-only endpoints remain JWT-only.
- Passkeys that cannot perform authenticator user verification cannot complete passwordless login under the new policy. A verified passkey remains an independent sign-in method; the Users MFA column and saved view specifically reflect TOTP enrollment.

## Validation

- Final combined backend run: **295 passed** across the affected authentication, API-key, passkey, AI, socket, workspace, run, migration and error-shape suites.
- Frontend: 163 Node tests passed; lint and integrity checks passed with zero errors; production build passed. Existing lint and large-chunk warnings remain.
- Browser: Chromium passed the Settings scenarios in both themes. Screenshots are saved to `frontend/test-results/` and uploaded by the new CI job.
- Security scan: full Bandit 1.9.3 report passed the narrowed gate; seven exception-gate tests passed. The production npm lockfile audit reported zero vulnerabilities. The Python advisory audit was not rerun locally.
- Static/backend integration checks: 25 focused migration-inventory, error-shape, crash-reporting and authorization-boundary checks passed without raising ceilings.
- All security tests used local synthetic users, resources and credentials. Real WebAuthn signature verification was exercised; no external AI provider or production service was called. The full repository backend suite was not completed; validation focused on the affected security, workspace, run and migration suites.

## Remaining work and limits

- Aggregate per-user/panel AI spend accounting remains separate work. Starting another conversation can still start another per-conversation budget; the new concurrency limits do not cap daily spend.
- CSP still permits inline scripts and eval. Tightening it requires testing the production import map and extension runtime; no CSP enforcement change is included here.
- Extend browser coverage to API-key management and complete authentication navigation. Current browser tests use synthetic responses; backend authentication tests exercise the real Flask and WebAuthn boundaries.
- Plugin-contributed AI tools still need their own resource-authorization policy. The common wrapper checks the live caller and feature permissions; it cannot infer ownership rules for arbitrary plugin data.
- An existing account-deletion issue involving `audit_logs.user_id` under enforced foreign keys was found during cross-review. The new revoked-session records support account deletion, but this unrelated audit-log relationship still needs a focused fix.
- Existing lint warnings and large build chunks remain. There was no production penetration test, provider-billing test, load test or deployment.

The historical `2026-09-05-security-probes.py` intentionally asserted the old vulnerabilities. Use the new negative regression tests under `backend/tests/` for the fixed behavior.
