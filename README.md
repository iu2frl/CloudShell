# CloudShell

> A self-hosted, Docker-deployable web SSH gateway — open your SSH sessions right in the browser, no client software required.

Inspired by [ShellNGN](https://shellngn.com/), built to be free, open, and self-hosted.

---

## ✨ Features

- **Web terminal** — full xterm.js terminal emulator with ANSI/VT100 support, copy/paste, and proper resize (SIGWINCH propagation)
- **Multi-tab sessions** — open multiple SSH connections to different devices simultaneously
- **Device manager** — add, edit, and delete SSH targets with name, host, port, and credentials
- **Password & SSH key auth** — store passwords or PEM private keys, both encrypted at rest (AES-256-GCM)
- **Built-in key generator** — generate RSA-4096 key pairs directly from the UI; copy the public key to paste into `authorized_keys`
- **JWT session auth** — login page, configurable session TTL, silent token refresh, and token revocation on logout
- **Change password** — update the admin password at runtime without restarting
- **Session expiry badge** — live countdown in the header turns yellow/red as the session approaches expiry
- **Toast notifications** — non-blocking feedback for every action
- **Error boundary** — graceful recovery screen for unexpected frontend errors
- **Docker Compose deploy** — single command to run in production

---

## 🚀 Quick Start (Docker Compose)

```bash
git clone https://github.com/youruser/CloudShell
cd CloudShell
cp .env.example .env
# Edit .env — set a strong SECRET_KEY and ADMIN_PASSWORD
docker compose up -d
```

Open **<http://localhost:8080>** and log in with your configured credentials.

> [!IMPORTANT]
> Put CloudShell behind a reverse proxy (Nginx, Caddy, Traefik) with TLS. SSH credentials are encrypted at rest but the web traffic should be HTTPS.

---

## ⚙️ Configuration

All configuration is via environment variables (or a `.env` file):

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | *(required)* | Random secret used to sign JWTs and derive the encryption key for stored credentials. **Change this in production.** |
| `ADMIN_USER` | `admin` | Login username |
| `ADMIN_PASSWORD` | `changeme` | Initial login password. After first login you can change it via the UI. |
| `TOKEN_TTL_HOURS` | `8` | JWT lifetime in hours. The frontend silently refreshes 10 minutes before expiry. |
| `DATA_DIR` | `/data` | Directory where the SQLite database, SSH key files, and known_hosts are stored. Mount this as a Docker volume. |

---

## 🛠️ Development Setup

### Prerequisites

- Python 3.12+
- Node.js 18+

### Backend

```bash
cd CloudShell
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run with dev defaults
DATA_DIR=/tmp/cloudshell-dev SECRET_KEY=devsecret ADMIN_USER=admin ADMIN_PASSWORD=admin \
  uvicorn backend.main:app --reload --port 8000
```

API docs: **<http://localhost:8000/docs>**

### Frontend

```bash
cd frontend
npm install
npm run dev   # Vite dev server on :5173, proxies /api → :8000
```

Open **<http://localhost:5173>**

### Build (production bundle copied into `backend/static/`)

```bash
cd frontend && npm run build
```

---

## 🐳 Docker

### Build image

```bash
docker build -t cloudshell .
```

### Run standalone

```bash
docker run -d \
  -p 8080:8000 \
  -v cloudshell_data:/data \
  -e SECRET_KEY=changeme \
  -e ADMIN_USER=admin \
  -e ADMIN_PASSWORD=changeme \
  cloudshell
```

### Docker Compose

```bash
docker compose up -d          # start
docker compose logs -f        # tail logs
docker compose down           # stop
docker compose down -v        # stop + delete data volume
```

---

## 🏗️ Architecture

```text
Browser (xterm.js)
      │  HTTP REST + WebSocket
      ▼
┌─────────────────────────────────────────┐
│          FastAPI Backend (:8000)         │
│                                         │
│  /api/auth/*      JWT login/logout      │
│  /api/devices/*   Device CRUD           │
│  /api/keys/*      SSH key generation    │
│  /api/terminal/*  SSH session + WS      │
│                                         │
│         AsyncSSH Client                 │
└──────────────────┬──────────────────────┘
                   │  SSH (TCP)
                   ▼
         Remote SSH Target(s)
```

- The **browser** only speaks HTTP/WebSocket to CloudShell — SSH traffic never leaves the server
- **WebSocket frames** are binary; resize events are JSON control frames `{"type":"resize","cols":N,"rows":N}`
- **Credentials** are encrypted with AES-256-GCM; the key is derived from `SECRET_KEY` via PBKDF2-HMAC-SHA256 (260 000 iterations)
- **SSH private keys** are stored as encrypted `.enc` files under `DATA_DIR/keys/`, never in plaintext
- **known_hosts** is persisted at `DATA_DIR/known_hosts` with accept-new policy

---

## 📁 Project Structure

```text
CloudShell/
├── backend/
│   ├── main.py               # FastAPI app, lifespan, global error handler
│   ├── config.py             # Settings (pydantic-settings, env vars)
│   ├── database.py           # Async SQLite engine + session factory
│   ├── models/
│   │   ├── device.py         # Device SQLAlchemy model
│   │   └── auth.py           # RevokedToken + AdminCredential models
│   ├── routers/
│   │   ├── auth.py           # Login, refresh, logout, /me, change-password
│   │   ├── devices.py        # Device CRUD
│   │   ├── keys.py           # SSH key pair generation
│   │   └── terminal.py       # SSH session creation + WebSocket proxy
│   └── services/
│       ├── ssh.py            # AsyncSSH session manager
│       └── crypto.py         # AES-256-GCM encrypt/decrypt, key file management
│
├── frontend/
│   └── src/
│       ├── api/client.ts     # Typed REST + WS client, JWT helpers, 401 interceptor
│       ├── components/
│       │   ├── Terminal.tsx          # xterm.js terminal wrapper
│       │   ├── DeviceList.tsx        # Sidebar device list
│       │   ├── DeviceForm.tsx        # Add/edit device modal
│       │   ├── ChangePasswordModal.tsx
│       │   ├── SessionBadge.tsx      # Live session expiry countdown
│       │   ├── Toast.tsx             # Toast notification system
│       │   └── ErrorBoundary.tsx     # React error boundary
│       └── pages/
│           ├── Login.tsx
│           └── Dashboard.tsx         # Multi-tab layout
│
├── Dockerfile                # Multi-stage build (node → python)
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── SPECS.md
```

---

## 🔐 Security Notes

| Concern | Mitigation |
| --- | --- |
| Stored passwords | AES-256-GCM, key derived from `SECRET_KEY` via PBKDF2 (260k iterations) |
| SSH private keys | Encrypted `.enc` files, `chmod 600`, never stored in plaintext |
| Web session | Short-lived JWT (HS256), revocation via DB deny-list, silent refresh |
| Token in WebSocket | Passed as `?token=` query param on WS upgrade; use HTTPS/WSS in production |
| Host key verification | `known_hosts` file persisted in `DATA_DIR`; accept-new policy |
| Admin password | bcrypt-hashed in DB after first change; env-var fallback on first boot only |

---

## 📋 Milestones

| Milestone | Status | Scope |
| --- | --- | --- |
| M1 | ✅ | Project scaffold, Docker, FastAPI, React + xterm.js |
| M2 | ✅ | Device CRUD API + UI, SQLite persistence, CI |
| M3 | ✅ | WebSocket SSH proxy, binary frames, resize, reconnect |
| M4 | ✅ | SSH key auth, AES-256-GCM credential encryption |
| M5 | ✅ | JWT auth, session expiry, token refresh, change-password |
| M6 | ✅ | UI polish, toasts, error boundary, README |
| M7 | ⬜ | Docker Compose single-command deploy, public release |

---

## ✨ Vibecoded?

✨ AF ✨

## 📄 License

MIT
