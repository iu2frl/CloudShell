# CloudShell

> A self-hosted, Docker-deployable web SSH gateway — open your SSH sessions right in the browser, no client software required.

[![License: GPL v3](https://img.shields.io/badge/license-GPL--v3-blue.svg)](https://github.com/iu2frl/CloudShell/blob/main/LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-yellow.svg)](https://www.python.org/)
[![Node 18+](https://img.shields.io/badge/node-18%2B-green.svg)](https://nodejs.org/)
[![React 18](https://img.shields.io/badge/react-18-61DAFB.svg?logo=react&logoColor=white)](https://react.dev/)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED.svg?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

I really liked the idea behind [ShellNGN](https://shellngn.com/), but I did not like having to pay to self host something, so CloudShell was built to be free, open, and self-hosted.

---

## Features

- **Web terminal** — full xterm.js terminal emulator with ANSI/VT100 support, copy/paste, and proper resize (SIGWINCH propagation)
- **Multi-tab sessions** — open multiple SSH connections to different devices simultaneously
- **Device manager** — add, edit, and delete SSH targets with name, host, port, and credentials
- **Password & SSH key auth** — store passwords or PEM private keys, both encrypted at rest (AES-256-GCM)
- **Built-in key generator** — generate RSA-4096 key pairs directly from the UI; copy the public key to paste into `authorized_keys`
- **Key file upload** — load an existing private key from a local `.pem` / `id_rsa` file instead of copy-pasting
- **JWT session auth** — login page, configurable session TTL, silent token refresh, and token revocation on logout
- **Change password** — update the admin password at runtime without restarting
- **Session expiry badge** — live countdown in the header turns yellow/red as the session approaches expiry
- **Toast notifications** — non-blocking feedback for every action
- **Error boundary** — graceful recovery screen for unexpected frontend errors
- **Docker Compose deploy** — single command to run in production

---

## Quick Start (Docker Compose)

### Building locally

```bash
git clone https://github.com/iu2frl/CloudShell
cd CloudShell
cp .env.example .env
# Edit .env — set a strong SECRET_KEY and ADMIN_PASSWORD
docker compose up -d
```

Open **<http://localhost:8080>** and log in with your configured credentials.

> [!IMPORTANT]
> Put CloudShell behind a reverse proxy (Nginx, Caddy, Traefik) with TLS. SSH credentials are encrypted at rest but the web traffic should be HTTPS.

### Using prebuilt images

```yaml
services:

  # ── Backend: FastAPI + AsyncSSH ─────────────────────────────────────────────
  backend:
    image: ghcr.io/iu2frl/cloudshell-backend:latest
    restart: unless-stopped
    expose:
      - "8000"
    volumes:
      - cloudshell_data:/data
    environment:
      SECRET_KEY: "changeme-generate-with-openssl-rand-hex-32"
      ADMIN_USER: "admin"
      ADMIN_PASSWORD: "changeme"
      TOKEN_TTL_HOURS: "8"
      # CORS_ORIGINS: "https://cloudshell.example.com"  # only needed when NOT behind Nginx
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3
    networks:
      - internal

  # ── Frontend: Nginx + React bundle + reverse proxy ──────────────────────────
  frontend:
    image: ghcr.io/iu2frl/cloudshell-frontend:latest
    restart: unless-stopped
    ports:
      - "8080:80"
    depends_on:
      backend:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-qO", "/dev/null", "http://127.0.0.1/"]
      interval: 5s
      timeout: 3s
      start_period: 5s
      retries: 5
    networks:
      - internal

volumes:
  cloudshell_data:

networks:
  internal:
    driver: bridge
```

---

## Configuration

All configuration is via environment variables (or a `.env` file):

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | *(required)* | Random secret used to sign JWTs and derive the encryption key for stored credentials. **Change this in production.** |
| `ADMIN_USER` | `admin` | Login username |
| `ADMIN_PASSWORD` | `changeme` | Initial login password. After first login you can change it via the UI. |
| `TOKEN_TTL_HOURS` | `8` | JWT lifetime in hours. The frontend silently refreshes 10 minutes before expiry. |
| `DATA_DIR` | `/data` | Directory where the SQLite database, SSH key files, and known_hosts are stored. Mount this as a Docker volume. |
| `CORS_ORIGINS` | *(unset)* | Comma-separated list of allowed CORS origins. Leave unset when running behind Nginx (same-origin). Set to your frontend URL (e.g. `https://cloudshell.example.com`) when running the backend standalone. |

### Secret key generation

```bash
openssl rand -hex 32
```

---

## User Guide

### Logging in

Navigate to the CloudShell URL and log in with your `ADMIN_USER` / `ADMIN_PASSWORD` credentials. The session is valid for `TOKEN_TTL_HOURS` hours; the frontend silently refreshes the token 10 minutes before expiry. The remaining session time is shown in the top-left corner of the dashboard as **Session: Xh Ym**.

### Managing devices

Click **Add device** in the left sidebar to register a new SSH target. Each device requires:

| Field | Description |
| --- | --- |
| Name | A friendly label shown in the sidebar and terminal tab |
| Hostname / IP | The SSH server address |
| Port | SSH port (default `22`) |
| Username | The SSH user to log in as |
| Auth type | `Password` or `SSH Key` |

Devices can be edited or deleted at any time via the pencil / trash icons in the sidebar. Credentials are always encrypted at rest and never returned to the frontend after saving.

### Password authentication

Select **Password** as the auth type and enter the remote user's password. The password is encrypted with AES-256-GCM before being stored.

### SSH key authentication

Select **SSH Key** as the auth type. There are three ways to supply the private key:

#### Option 1 — Paste an existing key

Paste the contents of your existing private key (PEM format, e.g. `~/.ssh/id_rsa`) directly into the **Private Key** textarea.

#### Option 2 — Load from a file

Click **Load file** next to the textarea. A file picker opens — select any `.pem`, `.key`, `id_rsa`, `id_ed25519`, or `id_ecdsa` file from your local machine. The key content is read in the browser and placed into the textarea; nothing is sent to the server until you click **Save**.

#### Option 3 — Generate a new key pair

Click **Generate key pair**. The backend generates a fresh RSA-4096 key pair and:

1. Populates the **Private Key** textarea automatically
2. Displays the corresponding **Public Key** in a green box below, with a **Copy** button

Copy the public key and add it to `~/.ssh/authorized_keys` on the remote server before saving:

```bash
echo "<paste public key here>" >> ~/.ssh/authorized_keys
```

Then click **Save**. From that point on, CloudShell authenticates to that device using the generated key.

> [!NOTE]
> The private key is encrypted with AES-256-GCM and stored as an `.enc` file under `DATA_DIR/keys/`. It is never stored in plaintext.

### Opening a terminal

Click any device name in the sidebar to open a terminal tab. Multiple tabs can be open simultaneously, each connected to a different device. The tab toolbar shows:

- **Device name** and `user@host:port`
- **Connection status badge** — Connecting / Connected / Disconnected / Error / Failed
- **Copy** button — copies `user@host:port` to clipboard
- **Reconnect** button — closes the current session and opens a fresh one

Typing `exit` or closing the remote shell ends the session cleanly and the badge switches to **Disconnected**.

### Changing the admin password

Click the **Session** timer badge in the top-left corner to open the change-password dialog. The new password takes effect immediately; the current session remains valid.

### Logging out

Click the **Logout** button in the top-right corner. The current JWT is revoked server-side so it cannot be reused even if intercepted.

---

## Development Setup

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

### Build (production bundle)

```bash
cd frontend && npm run build   # output goes into the Nginx image via Dockerfile.frontend
```

---

## Manual Docker setup

### Build both images

```bash
make build
# or individually:
docker build -f Dockerfile.backend  -t cloudshell-backend  .
docker build -f Dockerfile.frontend -t cloudshell-frontend .
```

### Docker Compose

```bash
docker compose up -d          # start
docker compose logs -f        # tail logs
docker compose down           # stop
docker compose down -v        # stop + delete data volume
```

### Makefile shortcuts

```bash
make build            # build both Docker images
make build-backend    # build the backend image only
make build-frontend   # build the frontend image only
make smoke-test       # run the two-container Docker smoke test locally
make up               # build images + start stack (copies .env.example if no .env exists)
make down             # stop the stack
make logs             # tail container logs
make restart          # restart all containers
make shell            # open a shell inside the running backend container
make dev              # start backend + frontend dev servers locally (no Docker)
make test             # run backend integration tests locally
```

---

## Architecture

```text
Browser (xterm.js)
      │  HTTP REST + WebSocket (:8080)
      ▼
┌─────────────────────────────────────────┐
│         Nginx Frontend (:80)            │
│                                         │
│  /              React SPA (static)      │
│  /api/*         proxy → backend:8000    │
│  /api/terminal/ws/*  WebSocket proxy    │
└──────────────────┬──────────────────────┘
                   │  HTTP (internal Docker network)
                   ▼
┌─────────────────────────────────────────┐
│          FastAPI Backend (:8000)        │
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

- The **browser** only speaks HTTP/WebSocket to the Nginx container — the backend is never exposed to the host
- **WebSocket frames** are binary; resize events are JSON control frames `{"type":"resize","cols":N,"rows":N}`
- **Credentials** are encrypted with AES-256-GCM; the key is derived from `SECRET_KEY` via PBKDF2-HMAC-SHA256 (260 000 iterations)
- **SSH private keys** are stored as encrypted `.enc` files under `DATA_DIR/keys/`, never in plaintext
- **known_hosts** is persisted at `DATA_DIR/known_hosts` with accept-new policy

---

## Project Structure

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
├── nginx/
│   └── default.conf          # Nginx config: SPA serving, /api/ proxy, WebSocket proxy
│
├── scripts/
│   └── smoke-test-docker.sh  # Two-container Docker smoke test
│
├── Dockerfile.backend        # FastAPI backend image
├── Dockerfile.frontend       # Node build → nginx:alpine image
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── SPECS.md
```

---

## Security Notes

| Concern | Mitigation |
| --- | --- |
| Stored passwords | AES-256-GCM, key derived from `SECRET_KEY` via PBKDF2 (260k iterations) |
| SSH private keys | Encrypted `.enc` files, `chmod 600`, never stored in plaintext |
| Web session | Short-lived JWT (HS256), revocation via DB deny-list, silent refresh |
| Token in WebSocket | Passed as `?token=` query param on WS upgrade; use HTTPS/WSS in production |
| Host key verification | `known_hosts` file persisted in `DATA_DIR`; accept-new policy |
| Admin password | bcrypt-hashed in DB after first change; env-var fallback on first boot only |

---

## Vibecoded?

✨ AF ✨

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for the full text.


