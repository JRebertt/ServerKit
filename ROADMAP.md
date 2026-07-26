# ServerKit Roadmap

> **Status: core phases complete — actively developed.** All original core phases below have shipped. Development now focuses on three tracks: the **deployment experience** (a live deploy console with streaming logs), the **extension platform** (runtime loading, signed releases, standalone extension repos), and **new capability areas delivered as installable extensions** through the built-in Marketplace — plus stability fixes and UI/UX polish from community reports. See **Active Development** below for what's in flight; the phase list is kept as the historical record of how the core was built out.

This document outlines the development roadmap for ServerKit. Features are organized by phases and priority.

---

## Current Version: v1.7.x (In Development)

### Recently Completed (v1.7.x)

- **Themes & Theme Studio** - A gallery of color themes in Settings → Appearance (Paper, Nord Deep, Gruvbox, Phosphor, High Contrast, and the stock look), applied instantly and previewed live, kept as each user's personal choice on top of the dark/light toggle. Themes are data, not code — a small map of color tokens — so a built-in Theme Studio lets anyone edit colors over the live panel and export a shareable file, admins can set a panel-wide default or import a theme, and a public community registry installs themes with one click.
- **Deploy Console & Live Run Logs** - Every install and deploy lands on one full-page live console: streaming build output, a step timeline with per-step durations and a live elapsed timer, and failure cards showing the real error tail with plain-language hints and one-click retry. Backed by a unified batched run-log layer (database persistence + WebSocket push with a polling fallback).
- **New Service Wizard & Template Catalog** - Three-step service creation (Source / Connect / Review) backed by a server-side template catalog with one-click compose templates and Git-repo templates.
- **Extensions Platform Maturation** - Marketplace registry backed by standalone extension repos (Kubernetes, Automations, Analytics, Mail, GPU, CrowdSec, DNS server, and more), with built-in features progressively extracted to keep the default panel lean. Installed extensions that ship a prebuilt bundle now render their UI on a production panel with no rebuild.
- **Privacy-First Web Analytics** - Cookieless, self-hosted analytics extension with WordPress and nginx integration and optional geo lookup.
- **Agent Fleet & Peering** - ServerKit-to-ServerKit peering (embedded agent mode), fleet doctor tooling, and agent capability upgrades.
- **Auth & Proxy Hardening** - Trusted reverse-proxy client-IP handling and per-IP login brute-force throttling.
- **UI Polish** - Skeleton loading states, unified tab groups and segmented bars, drawer-based flows, modal-based env var management.

### Earlier (v1.5.0)

- **New UI & Services Page** - Integrated full Services page with detail views, metrics, logs, and shell.
- **Environment Pipeline** - Multi-environment management for WordPress (Prod/Staging/Dev) with promotion/sync.
- **Visual Infrastructure Designer** - Node-based visual canvas for stack deployment and server overview.
- **Advanced Monitoring UI** - Real-time log streaming and terminal integration in the dashboard.
- **Template Library Expansion** - Over 60+ one-click deployment templates (Immich, Authelia, Ghost, etc.).
- **Team & Permissions** - RBAC with admin/developer/viewer roles, invitations, audit logging
- **SSO & OAuth Login** - Google, GitHub, OIDC, SAML with account linking

---

## Phase 1: Core Infrastructure (Completed)

- [x] Flask backend with SQLAlchemy ORM
- [x] React frontend with Vite
- [x] JWT-based authentication
- [x] Real-time WebSocket updates
- [x] System metrics (CPU, RAM, disk, network)
- [x] Docker and Docker Compose support
- [x] SQLite/PostgreSQL database support

---

## Phase 2: Application Management (Completed)

- [x] PHP/WordPress application deployment
- [x] Python (Flask/Django) application support
- [x] Node.js application management with PM2
- [x] Docker container management
- [x] Environment variable management
- [x] Application start/stop/restart controls
- [x] Log viewing per application

---

## Phase 3: Domain & SSL Management (Completed)

- [x] Nginx virtual host management
- [x] Domain configuration interface
- [x] Let's Encrypt SSL integration
- [x] SSL certificate auto-renewal
- [x] Redirect management (HTTP → HTTPS)

---

## Phase 4: Database Management (Completed)

- [x] MySQL/MariaDB database support
- [x] PostgreSQL database support
- [x] Database creation/deletion
- [x] User management per database
- [x] Basic query interface

---

## Phase 5: File & FTP Management (Completed)

- [x] Web-based file manager
- [x] File upload/download
- [x] File editing with syntax highlighting
- [x] vsftpd FTP server integration
- [x] FTP user management

---

## Phase 6: Monitoring & Alerts (Completed)

- [x] Real-time system metrics
- [x] Server uptime tracking
- [x] Customizable alert thresholds
- [x] Discord webhook notifications
- [x] Slack webhook notifications
- [x] Telegram bot notifications
- [x] Generic webhook support
- [x] Alert history and logging

---

## Phase 7: Security Features (Completed)

- [x] Two-factor authentication (TOTP)
- [x] Backup codes for 2FA recovery
- [x] ClamAV malware scanning
- [x] Quick scan / Full scan options
- [x] File quarantine management
- [x] File integrity monitoring
- [x] Failed login detection
- [x] Security event logging

---

## Phase 8: Scheduled Tasks (Completed)

- [x] Cron job management
- [x] Visual cron expression builder
- [x] Job execution history
- [x] Enable/disable jobs

---

## Phase 9: Firewall Management (Completed - Merged into Security)

- [x] UFW firewall integration
- [x] Visual rule management
- [x] Common port presets
- [x] Rule enable/disable
- [x] Consolidated into Security page for unified security management

---

## Phase 10: Multi-Server Management (Completed)

**Priority: High**

- [x] Agent-based remote server monitoring (Go agent)
- [x] Centralized dashboard for multiple servers
- [x] Server grouping and tagging
- [x] Cross-server metrics comparison
- [x] Remote Docker management via agents
- [x] Server health overview
- [x] Agent WebSocket gateway
- [x] HMAC-SHA256 authentication
- [x] GitHub Actions for agent releases (Linux/Windows)
- [x] Installation scripts endpoint
- [x] Agent auto-update mechanism
- [x] Agent download page in UI
- [x] Container logs streaming for remote servers

---

## Phase 11: Git Deployment (Completed)

**Priority: High**

- [x] GitHub/GitLab webhook integration
- [x] Automatic deployment on push
- [x] Branch selection for deployment
- [x] Rollback to previous deployments
- [x] Deployment history and logs
- [x] Pre/post deployment scripts
- [x] Zero-downtime deployments

---

## Phase 12: Backup & Restore (Completed)

**Priority: High**

- [x] Automated database backups
- [x] File/directory backups
- [x] S3-compatible storage support
- [x] Backblaze B2 integration
- [x] Backup scheduling
- [x] One-click restore
- [x] Backup retention policies
- [x] Offsite backup verification

---

## Phase 13: Email Server Management (Completed)

**Priority: Medium**

- [x] Postfix mail server setup
- [x] Dovecot IMAP/POP3 configuration
- [x] Email account management
- [x] Spam filtering (SpamAssassin)
- [x] DKIM/SPF/DMARC configuration
- [x] Webmail interface integration
- [x] Email forwarding rules

---

## Phase 14: Visual Infrastructure Designer (Completed)

**Priority: High**

The visual canvas for designing and deploying entire infrastructure stacks.

- [x] Node-based Visual Canvas (`WorkflowBuilder.jsx`) using React Flow
- [x] Infrastructure component nodes (Docker, Database, Domain, Service)
- [x] Smart connection rules (link apps to DBs, domains to apps)
- [x] One-click stack deployment from the canvas
- [x] Template-based stack generation
- [x] Server overview mode (visualize existing infrastructure)

---

## Phase 15: Team & Permissions (Completed)

**Priority: Medium**

- [x] Multi-user support
- [x] Role-based access control (RBAC)
- [x] Custom permission sets
- [x] Audit logging per user
- [x] Team invitations
- [x] Activity dashboard

---

## Phase 16: API Enhancements (Completed)

**Priority: Medium**

- [x] API key management
- [x] Rate limiting
- [x] Webhook event subscriptions
- [x] OpenAPI/Swagger documentation
- [x] API usage analytics

---

## Phase 17: Advanced Security (Completed)

**Priority: High**

- [x] Unified Security page with all security features
- [x] Firewall tab with UFW/firewalld management
- [x] Fail2ban integration
- [x] SSH key management
- [x] IP allowlist/blocklist
- [x] Brute force protection
- [x] Security audit reports
- [x] Vulnerability scanning (Lynis)
- [x] Automatic security updates (unattended-upgrades/dnf-automatic)

---

## Phase 18: SSO & OAuth Login (Completed)

**Priority: High**

- [x] Google OAuth 2.0 login
- [x] GitHub OAuth login
- [x] Generic OpenID Connect (OIDC) provider support
- [x] SAML 2.0 support for enterprise environments
- [x] Social login UI (provider buttons on login page)
- [x] Account linking (connect OAuth identity to existing local account)
- [x] Auto-provisioning of new users on first SSO login
- [x] Configurable SSO settings (enable/disable providers, client ID/secret management)
- [x] Enforce SSO-only login (disable password auth for team members)
- [x] SSO session management and token refresh

---

## Phase 19: Database Migrations & Schema Versioning (Completed)

**Priority: High**

- [x] Flask-Migrate (Alembic) integration
- [x] Migration wizard UI (Completed)
- [x] CLI fallback support

---

## Phase 20: New UI & Services Page (Completed)

**Priority: Critical**

Integrated full Services page with detail views, metrics, logs, shell, settings, and package management.

- [x] Services list page with status indicators and quick actions
- [x] Service detail page with tabbed interface (Metrics, Logs, Shell, Settings, Commands, Events, Packages)
- [x] Git connect modal for linking services to repositories
- [x] Gunicorn management tab for Python services
- [x] Service type detection and type-specific UI (Node, Python, PHP, Docker, etc.)

---

## Phase 21: Environment Pipeline (Completed)

**Priority: High**

- [x] WordPress multi-environment pipeline (Prod/Staging/Dev)
- [x] Code and Database promotion between environments
- [x] Production syncing and environment locking

---

## Phase 22: Container Logs & Monitoring UI (Completed)

**Priority: High**

- [x] Real-time log streaming via WebSocket with ANSI color support
- [x] Web-based terminal (`Terminal.jsx`) with shell access
- [x] Per-app resource usage charts (CPU, RAM)
- [x] Log search and filtering

---

# Later Phases (Completed)

The phases below were the second wave of core development, ordered by priority at the time.
All have since shipped.

---

## Phase 23: Workflow & Automation Engine — Core (Completed)

**Priority: Critical**

Moving beyond static design to dynamic, event-driven automation. This turns ServerKit into a powerful automation hub.

- [x] **Visual Workflow Builder:** Node-based canvas with drag-and-drop nodes, connection validation, and config panels
- [x] **Cron Integration:** Schedule workflows to run on recurring intervals (e.g., "Every Sunday at 2 AM, backup all DBs and rotate logs")
- [x] **Manual Execution:** Trigger workflows on demand with optional context data
- [x] **Execution History:** Track workflow execution status, per-node results, and timestamped logs
- [x] **Script Nodes:** Custom Shell script execution nodes with output capture
- [x] **Notification Nodes:** Send alerts via configured notification channels
- [x] **One-Click Stack Deployment:** Deploy full infrastructure (databases, apps, domains) from a workflow diagram

---

## Phase 24: Customizable Sidebar & Dashboard Views (Completed)

**Priority: High**

Let users personalize what they see. Not everyone runs email servers or manages Docker — the sidebar should adapt to each user's needs.

- [x] Sidebar configuration page in Settings
- [x] Preset view profiles (Full, Web Hosting, Email Admin, Docker/DevOps, Minimal)
- [x] Custom view builder — toggle individual sidebar items on/off
- [x] Per-user preference storage (saved to user profile)

---

## Phase 25: Workflow Engine — Triggers & Completion (Completed)

**Priority: High**

Complete the workflow engine with proper execution logic, missing triggers, and production-grade reliability.

- [x] **DAG Execution:** Full directed acyclic graph traversal with parallel branch support (replace current linear BFS)
- [x] **Logic Node Evaluation:** If/Else condition evaluation with true/false branching
- [x] **Variable Interpolation:** Pass data between steps using `${node_id.field}` and `{{placeholder}}` syntax in node configs
- [x] **Webhook Triggers:** Register `/hooks/<webhook_id>` endpoint to fire workflows on incoming HTTP requests
- [x] **Event Triggers:** Run workflows on system events (health check failure, high CPU/memory, git push, app stopped)
- [x] **Notification Templating:** Message placeholder substitution (`${node_id.stdout}`, `{{workflow_name}}`) in notification nodes
- [x] **Execution Timeouts:** Configurable timeout per node (1–3600s) to prevent hung workflows
- [x] **Retry on Failure:** Configurable retry count (0–5) and delay per node
- [x] **Circular Dependency Detection:** Kahn's algorithm validates graph on save and before execution
- [x] **Script Sandboxing:** Timeout enforcement, output size limits, explicit `bash -c`/`python3 -c` execution

---

## Phase 26: Agent Fleet Management (Completed)

**Priority: High**

Level up agent management from "connect and monitor" to full fleet control.

- [x] Agent version tracking and compatibility matrix (panel version ↔ agent version)
- [x] Push agent upgrades from the panel (single server or fleet-wide rollout)
- [x] Staged rollout support — upgrade agents in batches with health checks between waves
- [x] Agent health dashboard — connection uptime, heartbeat latency, command success rate per agent
- [x] Auto-discovery of new servers on the local network (mDNS/broadcast scan)
- [x] Agent registration approval workflow (admin must approve before agent joins fleet)
- [x] Bulk agent operations — restart, upgrade, rotate keys across selected servers
- [x] Agent changelog and release notes visible in UI
- [x] Offline agent command queue — persist commands and deliver when agent reconnects
- [x] Command retry with configurable backoff for failed/timed-out operations
- [x] Agent connection diagnostics — test connectivity, latency, firewall check from panel

---

## Phase 27: Cross-Server Monitoring Dashboard (Completed)

**Priority: High**

Fleet-wide visibility — see everything at a glance and catch problems early.

- [x] Fleet overview dashboard — heatmap of all servers by CPU/memory/disk usage
- [x] Server comparison charts — overlay metrics from multiple servers on one graph
- [x] Per-server alert thresholds (CPU > 80% for 5 min → warning, > 95% → critical)
- [x] Anomaly detection — automatic baseline learning, alert on deviations
- [x] Custom metric dashboards — drag-and-drop widgets, save layouts per user
- [x] Metric correlation view — spot relationships between metrics across servers
- [x] Capacity forecasting — trend-based predictions (disk full in X days, memory growth rate)
- [x] Metrics export — Prometheus endpoint (`/metrics`), CSV download, JSON API
- [x] Grafana integration guide and pre-built dashboard templates
- [x] Fleet-wide search — find which server is running a specific container, service, or port

---

## Phase 28: Agent Plugin System (Completed)

**Priority: High**

Make the agent extensible — let users add custom capabilities without modifying agent core. This is the foundation for future integrations (Android device farms, IoT fleets, custom hardware monitoring, etc.).

### Plugin Architecture
- [x] Plugin specification — standard interface (init, healthcheck, metrics, commands)
- [x] Plugin manifest format (YAML/JSON) — name, version, dependencies, capabilities, permissions
- [x] Plugin lifecycle management — install, enable, disable, uninstall, upgrade
- [x] Plugin isolation — each plugin runs in its own process/sandbox with resource limits
- [x] Plugin communication — standardized IPC between plugin and agent core

### Plugin Capabilities
- [x] Custom metrics reporters — plugins can push arbitrary metrics to the panel
- [x] Custom health checks — plugins define checks that feed into the status system
- [x] Custom commands — plugins register new command types the panel can invoke
- [x] Scheduled tasks — plugins can register periodic jobs (cron-like)
- [x] Event hooks — plugins can react to agent events (connect, disconnect, command, alert)

---

## Phase 29: Server Templates & Config Sync (Completed)

**Priority: Medium**

Define what a server should look like, apply it, and detect when it drifts.

- [x] Server template builder — define expected state (packages, services, firewall rules, users, files)
- [x] Template library — save and reuse templates (e.g., "Web Server", "Database Server", "Mail Server")
- [x] Apply template to server — install packages, configure services, set firewall rules via agent
- [x] Config drift detection — periodic comparison of actual vs. expected state
- [x] Drift report UI — visual diff showing what changed and when
- [x] Auto-remediation option — automatically fix drift back to template (with approval toggle)
- [x] Template versioning — track changes to templates over time
- [x] Template inheritance — base template + role-specific overrides
- [x] Bulk apply — roll out template changes across server groups
- [x] Compliance dashboard — percentage of fleet in compliance per template

---

## Phase 30: Multi-Tenancy & Workspaces (Completed)

**Priority: Medium**

Isolate servers by team, client, or project. Essential for agencies, MSPs, and larger teams.

- [x] Workspace model — isolated container for servers, users, and settings
- [x] Workspace CRUD — create, rename, archive workspaces
- [x] Server assignment — each server belongs to exactly one workspace
- [x] User workspace membership — users can belong to multiple workspaces with different roles
- [x] Workspace switching — quick-switch dropdown in the header
- [x] Per-workspace settings — notification preferences, default templates, branding
- [x] Workspace-scoped API keys — API keys restricted to a single workspace
- [x] Cross-workspace admin view — super-admin can see all workspaces and usage
- [x] Workspace usage quotas — limit servers, users, or API calls per workspace
- [x] Workspace billing integration — track resource usage per workspace for invoicing

---

## Phase 31: Advanced SSL Features (Completed)

**Priority: Medium**

- [x] Certificate expiry monitoring
- [x] Wildcard SSL certificates via DNS-01 challenge
- [x] Multi-domain certificates (SAN)
- [x] Custom certificate upload (key + cert + chain)
- [x] Certificate expiry notifications (email/webhook alerts before expiration)
- [x] SSL configuration templates (modern, intermediate, legacy compatibility)
- [x] SSL health check dashboard (grade, cipher suites, protocol versions)

---

## Phase 32: DNS Zone Management (Completed)

**Priority: Medium**

Full DNS record management with provider API integration.

- [x] DNS zone editor UI (A, AAAA, CNAME, MX, TXT, SRV, CAA records)
- [x] Cloudflare API integration (list/create/update/delete records)
- [x] Route53 API integration
- [x] DigitalOcean DNS integration
- [x] DNS propagation checker (query multiple nameservers)
- [x] Auto-generate recommended records for hosted services (SPF, DKIM, DMARC, MX)
- [x] DNS template presets (e.g., "standard web hosting", "email hosting")
- [x] Bulk record import/export (BIND zone file format)

---

## Phase 33: Nginx Advanced Configuration (Completed)

**Priority: Medium**

Go beyond basic virtual hosts — full reverse proxy and performance configuration.

- [x] Visual reverse proxy rule builder (upstream servers, load balancing methods)
- [x] Load balancing configuration (round-robin, least connections, IP hash)
- [x] Caching rules editor (proxy cache zones, TTLs, cache bypass rules)
- [x] Rate limiting at proxy level (per-IP, per-route)
- [x] Custom location block editor with syntax validation
- [x] Header manipulation (add/remove/modify request/response headers)
- [x] Nginx config syntax check before applying changes
- [x] Config diff preview before saving
- [x] Access/error log viewer per virtual host

---

## Phase 34: Status Page & Health Checks (Completed)

**Priority: Medium**

Public-facing status page and automated health monitoring.

- [x] Automated health checks (HTTP, TCP, DNS, SMTP) with configurable intervals
- [x] Public status page (standalone URL, no auth required)
- [x] Status page customization (logo, colors, custom domain)
- [x] Service grouping on status page (e.g., "Web Services", "Email", "APIs")
- [x] Incident management — create, update, resolve incidents with timeline
- [x] Uptime percentage display (24h, 7d, 30d, 90d)
- [x] Scheduled maintenance windows with advance notifications
- [x] Status page subscribers (email/webhook notifications on incidents)
- [x] Historical uptime graphs
- [x] Status badge embeds (SVG/PNG for README files)

---

## Phase 35: Server Provisioning APIs (Completed)

**Priority: Medium**

Spin up and manage cloud servers directly from the panel.

- [x] DigitalOcean API integration (create/destroy/resize droplets)
- [x] Hetzner Cloud API integration
- [x] Vultr API integration
- [x] Linode/Akamai API integration
- [x] Server creation wizard (region, size, OS, SSH keys)
- [x] Auto-install ServerKit agent on provisioned servers
- [x] Server cost tracking and billing overview
- [x] Snapshot management (create/restore/delete)
- [x] One-click server cloning
- [x] Destroy server with confirmation safeguards

---

## Phase 36: Performance Optimization (Completed)

**Priority: Low**

- [x] Redis caching for frequently accessed data (metrics, server status)
- [x] Database query optimization and slow query logging
- [x] Background job queue (Celery or RQ) for long-running tasks
- [x] Lazy loading for large datasets (paginated API responses)
- [x] WebSocket connection pooling and reconnection improvements
- [x] Frontend bundle optimization and code splitting

---

## Phase 37: Mobile App (Completed)

**Priority: Low — v3.0+**

- [x] React Native or PWA mobile application
- [x] Push notifications for alerts and incidents
- [x] Quick actions (restart services, view stats, acknowledge alerts)
- [x] Biometric authentication (fingerprint/Face ID)
- [x] Offline mode with cached server status

---

## Phase 38: Marketplace & Extensions (Completed)

**Priority: Low — v3.0+**

- [x] Plugin/extension system with API hooks
- [x] Community marketplace for plugins
- [x] Custom dashboard widgets
- [x] Theme customization (colors, layout, branding)
- [x] Extension SDK and developer documentation

---

# Active Development (H2 2026)

Current focus areas on the `dev` branch. Core work centers on the deploy experience and
platform infrastructure; new capability areas ship as Marketplace extensions.

## Deploy Console & Live Run Logs

The publish pipeline is becoming ServerKit's signature experience: deploy anything, watch it
happen live, and debug failures entirely from the UI.

- [x] Full-page live deploy console for every install and deploy (templates, Git repos, uploads, redeploys)
- [x] Streaming build output with a step timeline, per-step durations, and live elapsed time
- [x] Failure cards showing the real error tail with plain-language hints and one-click retry
- [x] Unified batched run-log layer (database persistence + WebSocket push, polling fallback)
- [x] Extensions can put their own long-running work on the same console — WordPress environment promotions are the first, with live steps, logs and retry

## Extension Platform

- [x] Runtime frontend loading — installed extensions render without rebuilding the panel
- [x] Extensions plug into the panel's own surfaces — their work shows up in the deploy console, their data in backups and restore, their health on the doctor page, their objects in search, and they can run commands across the fleet
- [ ] Signed extension releases, with explicit install consent for unsigned or third-party code
- [ ] Remaining built-ins extracted to standalone repos (including the WordPress flagship)
- [ ] Security suite (Fail2ban, ClamAV, Lynis, auto-updates, image scanning) as installable extensions for a leaner default panel

## Game Server Hosting (new extension family)

- [ ] Minecraft server extension: guided setup, live console, player management, world backups, scheduled restarts with in-game warnings
- [ ] "Share with friends" connect card, with optional domain (SRV record) support
- [ ] Reusable game-server framework (console, players, saves, schedules) enabling future titles

## Fleet & Agents

- [ ] Live command-output streaming from remote agents into the deploy console

## Release Engineering

- [ ] End-to-end verification sweep and publishing round for pending releases and extension repos

---

## Version Milestones

| Version | Target Features | Status |
|---------|-----------------|--------|
| v0.9.0 | Core features, 2FA, Notifications, Security | Completed |
| v1.0.0 | Production-ready stable release, DB migrations | Completed |
| v1.1.0 | Multi-server, Git deployment | Completed |
| v1.2.0 | Backups, Advanced SSL, Advanced Security | Completed |
| v1.3.0 | Email server, API enhancements | Completed |
| v1.4.0 | Team & permissions, SSO & OAuth login | Completed |
| v1.5.0 | New UI, Visual Designer, Services Page | Completed |
| v1.6.0 | Workflow triggers & completion, fleet management | Completed |
| v1.7.0 | Cross-server monitoring, agent plugin system | Completed |
| v1.8.0 | Server templates, multi-tenancy | Completed |
| v1.9.0 | Advanced SSL, DNS management, Nginx config | Completed |
| v2.0.0 | Status pages, server provisioning, performance | Completed |
| v3.0.0 | Mobile app, Marketplace | Completed |

Current released line: **v1.7.x** — see **Active Development** above for what's in flight.

---

## Contributing

Want to help? See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Priority areas for contributions:**
- New extensions and Marketplace templates
- Extension SDK improvements and example plugins
- UI/UX polish and fixes for reported issues
- Documentation
- Test coverage

---

## Feature Requests

The core is no longer taking on new features. The best way to propose new functionality is as an **extension** — open an issue on GitHub with the `extension-idea` label, or build it yourself with the extension SDK. Core issues (bugs, UI polish) are always welcome with the `bug` label.

---

<p align="center">
  <strong>ServerKit Roadmap</strong><br>
  Last updated: July 2026
</p>
