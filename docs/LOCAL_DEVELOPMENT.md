# Local Development Setup for Windows

This guide explains how to run ServerKit locally on Windows for development and testing.

## Production Server Specs (Reference)

ServerKit is tested on Digital Ocean with these specs:

| Spec | Value |
|------|-------|
| **OS** | Ubuntu 24.04.3 LTS |
| **CPU** | 2 cores (AMD) |
| **RAM** | 4 GB |
| **Disk** | 25 GB |
| **Plan** | Basic Droplet (~$12/mo) |

For local development, similar or lower specs work fine.

## Prerequisites

- **Windows 10/11** with WSL2 enabled
- **Docker Desktop** for Windows (with WSL2 backend)
- **Git** for Windows

## Option 1: Full Local Development (Recommended)

This mimics the production setup where backend runs on host and frontend in Docker.

### Step 1: Install WSL2 + Ubuntu

```powershell
# Run in PowerShell as Administrator
wsl --install -d Ubuntu-24.04
```

Restart your computer, then open Ubuntu from Start menu to complete setup.

### Step 2: Install Dependencies in WSL

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install -y python3 python3-pip python3-venv python3-dev

# Install build tools
sudo apt install -y build-essential libffi-dev libssl-dev

# Install iproute2 (for ss command)
sudo apt install -y iproute2

# Install Docker (inside WSL)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Log out and back in for docker group to take effect
```

### Step 3: Clone and Setup

```bash
# Clone the repo (or navigate to your mounted Windows folder)
cd ~
git clone https://github.com/jhd3197/ServerKit.git
cd ServerKit

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
pip install gunicorn gevent gevent-websocket

# Create .env file
cat > .env << 'EOF'
SECRET_KEY=dev-secret-key-change-in-production
JWT_SECRET_KEY=dev-jwt-key-change-in-production
DATABASE_URL=sqlite:///backend/instance/serverkit.db
CORS_ORIGINS=http://localhost:41921,http://127.0.0.1:41921,http://localhost:47927,http://127.0.0.1:47927
FLASK_ENV=development
PORT=47927
EOF

# Create instance directory
mkdir -p backend/instance
```

### Step 4: Run Backend (Terminal 1)

```bash
cd ~/ServerKit
source venv/bin/activate
cd backend
export $(cat ../.env | xargs)
python run.py
```

Backend will be available at: `http://localhost:47927`

### Step 5: Run Frontend (Terminal 2)

```bash
cd ~/ServerKit/frontend
npm install
npm run dev -- --host 127.0.0.1 --port 41921 --strictPort
```

Frontend will be available at: `http://localhost:41921`

---

## Option 2: Docker Compose (Simpler, but no host system access)

Use this for quick UI testing. Note: System management features (PHP install, firewall, etc.) won't work.

The repository's `docker-compose.yml` already does this — it builds the
all-in-one image from `Dockerfile` (gunicorn serving the API, the SPA and
websockets together) and publishes it on port 5000.

```bash
cp .env.example .env    # set SECRET_KEY / JWT_SECRET_KEY
docker compose up -d --build
```

Then open http://localhost:5000. Override the published port with
`SERVERKIT_HTTP_PORT` in `.env` if 5000 is taken.

```bash
docker compose logs -f          # follow the panel log
docker compose down             # stop, keep the database volume
docker compose down -v          # stop and destroy the database
```

There is no hot reload in this mode — the SPA is a production build baked into
the image, so a frontend change needs `docker compose up -d --build`. For an
edit-refresh loop, use Option 1 (Vite HMR + Flask reloader).

---

## Option 3: VS Code Dev Container

Add this to `.devcontainer/devcontainer.json`:

```json
{
  "name": "ServerKit Dev",
  "dockerComposeFile": "../docker-compose.yml",
  "service": "serverkit",
  "workspaceFolder": "/app",
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "dbaeumer.vscode-eslint"
      ]
    }
  },
  "forwardPorts": [5000],
  "postCreateCommand": "pip install -r backend/requirements.txt"
}
```

---

## Quick Reference

| Component | Production (DO Server) | Local Dev (WSL) |
|-----------|----------------------|-----------------|
| Backend | systemd service | `python run.py` |
| Frontend | Docker + nginx | `npm run dev` |
| Database | SQLite in /opt/serverkit | SQLite in ./backend/instance |
| System Access | Full (sudo, systemctl) | Full (in WSL) |

## Testing System Features

To test PHP installation, firewall, etc. locally:

1. Use **Option 1** (WSL) - this gives you a real Linux environment
2. Install the same packages as production:
   ```bash
   sudo apt install -y firewalld vsftpd
   ```
3. The backend will have real system access

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask secret key | Required |
| `JWT_SECRET_KEY` | JWT signing key | Required |
| `DATABASE_URL` | SQLite path | `sqlite:///serverkit.db` |
| `CORS_ORIGINS` | Allowed origins | `http://localhost` |
| `FLASK_ENV` | development/production | `production` |

## Troubleshooting

### Port already in use
```bash
# Find what's using the port
sudo lsof -i :47927
# Kill it
sudo kill -9 <PID>
```

### Permission denied for Docker
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### Database locked
```bash
# Remove the lock file
rm backend/instance/serverkit.db-journal
```

---

## Exposing Your Local Control Plane (ngrok)

When developing locally on Windows/WSL you may want a remote ServerKit agent (or
a Docker host on another machine) to connect back to your machine. The `dev.sh`
and `dev.ps1` scripts include a `tunnel` mode that starts the backend, frontend,
and an ngrok tunnel pointed at the active backend port printed by the launcher.

### Prerequisites

1. Install ngrok and authenticate once:

   ```bash
   # macOS / Linux / WSL
   brew install ngrok/ngrok/ngrok    # or: snap install ngrok
   ngrok config add-authtoken <YOUR_TOKEN>
   ```

   ```powershell
   # Windows
   choco install ngrok               # or: scoop install ngrok
   ngrok config add-authtoken <YOUR_TOKEN>
   ```

2. (Optional) Reserve a domain in the ngrok dashboard so the URL stays stable
   across restarts.

### Start with a tunnel

```bash
# Linux / macOS / WSL
./dev.sh tunnel
```

```powershell
# Windows
.\dev.ps1 tunnel
```

The public ngrok URL is printed in green once the tunnel is up. Use it as the
`--server` argument when registering an agent:

```bash
serverkit-agent register \
  --token "sk_reg_xxx" \
  --server "https://<your-tunnel>.ngrok-free.app"
```

### Optional environment variables

| Variable | Purpose |
|----------|---------|
| `NGROK_DOMAIN` | Use a reserved ngrok domain (e.g. `my-app.ngrok-free.app`). |
| `NGROK_AUTHTOKEN` | Override the authtoken (otherwise the one stored by `ngrok config` is used). |
| `CORS_ORIGINS` | Override CORS allow-list. The script defaults include `https://*.ngrok-free.app`, `https://*.ngrok.app`, `https://*.ngrok.io`. |

---

## Quick Start with WSL2 (Helper Script)

If you're on Windows and using WSL2 Ubuntu/Debian, you can skip the manual
steps above and use the bundled setup helper:

```bash
# from inside WSL, in the cloned repo
bash scripts/setup-wsl.sh           # full setup
bash scripts/setup-wsl.sh --check   # dry-run / diagnostics only
```

The script will:

- Detect WSL and warn if the repo lives under `/mnt/c` (slow file I/O for hot-reload).
- Verify Ubuntu/Debian and install missing apt packages
  (`python3`, `python3-venv`, `python3-pip`, `nodejs`, `npm`, `git`, `curl`).
- Create `backend/venv` and install Python requirements.
- Run `npm install` in `frontend/`.
- Copy `backend/.env.example` to `backend/.env` if missing.
- Print WSL-specific tips (localhost forwarding, polling reloader, ngrok).

Once it finishes:

```bash
./dev.sh           # start backend + frontend
./dev.sh tunnel    # also expose backend via ngrok (see section above)
```
