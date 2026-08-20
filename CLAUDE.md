# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ServerKit is a server control panel for managing web applications, databases, Docker containers, and security on VPS/dedicated servers. Flask backend (Python 3.11+), React frontend (Vite + SCSS), SQLite/PostgreSQL database, real-time updates via Socket.IO.

## Development Commands

```bash
# Backend (launcher default port 47927, hot-reload)
cd backend && python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py

# Frontend (launcher default port 41921, Vite HMR)
cd frontend && npm install && npm run dev

# Both at once (Linux/WSL)
./dev.sh

# Frontend lint
cd frontend && npm run lint

# Frontend production build
cd frontend && npm run build

# Backend tests
cd backend && pytest
cd backend && pytest --cov=app

# Docker (all-in-one panel container; no host management)
docker compose up -d --build
```

Default dev credentials: `admin` / `admin`

## Architecture

### Backend (`backend/`)

Flask app factory in `app/__init__.py` using `create_app()`. Three-layer architecture:

- **`app/api/`** — Flask Blueprints, one file per feature (90+ files). All routes prefixed `/api/v1/`. JWT-protected via `@jwt_required()`.
- **`app/services/`** — Business logic (165+ files). Services are stateless modules called by API routes. Heavy lifting (shell commands, Docker API, file operations) happens here.
- **`app/models/`** — SQLAlchemy ORM models (80+ files). Schema is managed by Alembic migrations in `backend/migrations/versions/` — add a migration for every schema change; the app does not call `db.create_all()`.

Other backend components:
- `app/sockets.py` — Socket.IO event handlers for real-time metrics, logs, terminal
- `app/agent_gateway.py` — Defines the Socket.IO `/agent` namespace for the multi-server agent fleet, backed by the in-memory singleton `app/services/agent_registry.py` (HMAC auth, heartbeat/metrics, command routing); `app/api/agent_poll.py` is the HTTP long-poll fallback. The native agent itself is a Go program maintained in the separate `serverkit-agent` repo (extracted from this repo's former `agent/` dir) — agent-side capability changes ship there, so panel↔agent protocol changes are no longer atomic in one commit.
- `app/middleware/security.py` — Security headers middleware
- `config.py` — Environment-based config (development/production/testing)
- `run.py` — Entry point

> **Agent gateway is single-worker.** All connected-agent state lives in-memory
> in one process, so the panel must run a **single** gunicorn worker process
> (`-w 1 --threads N`, plain threaded worker — NOT the gevent-websocket worker
> class, which double-answers the WS handshake against `async_mode='threading'`);
> multi-worker deployments silently misroute agent commands. See
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [SECURITY.md](SECURITY.md).

### Frontend (`frontend/src/`)

React 18 SPA with client-side routing:

- **`pages/`** — Route-level components (60+ files). Each maps to a route in `App.jsx`.
- **`components/`** — Reusable UI components shared across pages.
- **`contexts/`** — React Context providers: `AuthContext` (JWT auth + token refresh), `ThemeContext`, `ToastContext`, `ResourceTierContext` (feature gating).
- **`services/api.js`** — Centralized `ApiService` class handling all HTTP requests, token management, and auto-refresh.
- **`hooks/`** — Custom React hooks for reusable logic.
- **`styles/`** — SCSS stylesheets with design system variables. Main entry is `main.scss`. Page-specific styles in `styles/pages/`.
- **`layouts/`** — `DashboardLayout` wraps authenticated pages (sidebar + header).

Route guards: `PrivateRoute` (auth check), `PublicRoute` (redirect if logged in), `SetupRoute` (redirect to `/setup` if not configured).

### Request Flow

Browser → Nginx (`:80`/`:443`) → proxy_pass to Docker containers (`:8001-8999`) for managed apps, or to Flask (`:5000`) for the panel API. The 404 handler in Flask serves `index.html` for SPA client-side routing; API routes return JSON errors.

### Production Build

The Dockerfile is multi-stage: Node 20 builds frontend, Python 3.11 serves everything via Gunicorn with a single plain threaded worker (`--workers 1 --threads 100`, no `--worker-class` — see the single-worker note above). Built frontend is served from Flask's static folder.

## Platform & Distro Awareness

ServerKit deploys on Linux (bare metal, VPS, or Docker). Development may happen on Windows/macOS.

- **Service layer is Linux-only** — nginx, systemctl, apt/dnf, PHP-FPM, etc. are inherently Linux. No need to abstract these for Windows.
- **Platform-agnostic code** (config management, storage, API layer) should guard Unix-only calls like `os.chmod` with `if os.name != 'nt'` so the dev server can run locally on any OS.
- **Distro differences matter** — use `backend/app/utils/system.py` helpers (`get_package_manager`, `is_package_installed`, `install_package`) instead of calling `apt`/`dpkg`/`dnf` directly. Not all targets are Debian-based.

## Code Style

### Python
- PEP 8, type hints where helpful
- Service functions are standalone (no classes unless stateful)
- Consistent JSON error responses: `{'error': 'message'}, status_code`

### React/JavaScript
- Functional components with hooks only
- PascalCase for components (`Sidebar.jsx`), camelCase for everything else
- SCSS for styling — use existing design system variables (`$bg-card`, `$primary-color`, `$spacing-md`, etc.) and BEM-like naming (`.block__element--modifier`)
- Context API for global state; props drilling is fine for 2-3 levels
- No inline styles; no Tailwind/CSS-in-JS

### Diffs & Commits
- One logical change per commit
- Minimal, focused diffs — don't silently refactor surrounding code
- Branch naming: `feature/`, `fix/`, `docs/`, `refactor/` prefixes

## Adding a New Feature (Full Stack)

1. **Model**: Add SQLAlchemy model in `backend/app/models/`
2. **Service**: Add business logic in `backend/app/services/`
3. **API**: Create Blueprint in `backend/app/api/`, register it in `app/__init__.py` with `url_prefix='/api/v1/<feature>'`
4. **Frontend API**: Add methods to `ApiService` in `frontend/src/services/api.js`
5. **Page**: Create page component in `frontend/src/pages/`, add route in `App.jsx`
6. **Styles**: Add SCSS file in `frontend/src/styles/pages/`, import in `main.scss`

### Authorization (default-deny, test-enforced)

Every mutating route (POST/PUT/PATCH/DELETE) must carry an explicit
authorization decision — `@jwt_required()` alone is never sufficient
(GHSA-r4q7-x795-vr4j). Use one authentication boundary: the rbac policy
decorators (`@admin_required` / `@developer_required` / `@permission_required`)
already authenticate via `auth_required()`, so never stack `@jwt_required()`
outside one. `backend/tests/test_route_authz_static.py` (coverage),
`test_route_authz_sweep.py` (enforcement) and `test_auth_decorator_boundaries.py`
(one boundary) all fail the build otherwise. See AGENTS.md for the allowlists.

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Flask session signing |
| `JWT_SECRET_KEY` | JWT token signing |
| `DATABASE_URL` | DB connection string (`sqlite:///...` or PostgreSQL) |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `FLASK_ENV` | `development` or `production` |
| `TRUST_PROXY_HEADERS` | Trust the reverse proxy's forwarding headers to derive the real client IP (Werkzeug ProxyFix). `true` behind the shipped nginx; `false`/unset for a directly-exposed dev server. See SECURITY.md. |
| `TRUSTED_PROXY_HOPS` | Number of trusted proxy hops in front of Flask (bundled nginx = `1`). |
| `AUTH_IP_MAX_ATTEMPTS` / `AUTH_IP_WINDOW_MINUTES` / `AUTH_IP_BLOCK_MINUTES` | Per-IP login brute-force throttle (default `10`/`15`/`15`), complementing the per-user lockout. |
