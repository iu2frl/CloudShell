# CloudShell — Project Specifications

> A self-hosted, Docker-containerizable web SSH client inspired by ShellNGN.

---

## 🎯 Overview

CloudShell is a lightweight, self-hosted web application that acts as an **SSH gateway/router**. Users connect to the WebUI via their browser; the SSH sessions are established server-side (from within the Docker container), so no SSH traffic ever flows directly from the client's device.

---

## 🛠️ Technology Stack

### Backend

| Component | Choice | Rationale |
|---|---|---|
| Language | **Python 3.12+** | Excellent async support, rich SSH libraries, fast prototyping |
| Web Framework | **FastAPI** | Async, WebSocket-native, automatic OpenAPI docs |
| SSH Library | **AsyncSSH** | Pure-Python, async SSH client with password + key auth |
| WebSocket → SSH bridge | **FastAPI WebSockets** + AsyncSSH | Real-time terminal streaming |
| Database | **SQLite** (via SQLAlchemy + aiosqlite) | Zero-dependency, file-based, easy to volume-mount |
| Auth | **JWT tokens** (python-jose) | Stateless, simple single-user auth |

### Frontend

| Component | Choice | Rationale |
|---|---|---|
| Framework | **React 18 + TypeScript** | Component model fits terminal/device-list UI well |
| Terminal emulator | **xterm.js** | Industry standard, supports full ANSI/VT100 |
| UI Library | **Shadcn/ui + Tailwind CSS** | Clean, modern look with minimal overhead |
| Build tool | **Vite** | Fast HMR, small bundles |
| WebSocket client | Native browser WebSocket API | No extra dependency needed |

### Infrastructure

| Component | Choice |
|---|---|
| Containerization | **Docker** + **Docker Compose** |
| Base image | `python:3.12-slim` |
| Static files | Served by FastAPI (built React bundle copied in) |
| Persistent storage | Docker named volume mounted at `/data` (SQLite DB + SSH keys) |

---

## 📐 Architecture

```
Browser (xterm.js)
      │  WebSocket (ws://host/ws/terminal/{session_id})
      ▼
┌─────────────────────────────────┐
│         FastAPI Backend         │
│                                 │
│  ┌──────────┐  ┌─────────────┐  │
│  │  REST API│  │  WS Handler │  │
│  │ /devices │  │ /ws/terminal│  │
│  └──────────┘  └──────┬──────┘  │
│                        │        │
│              AsyncSSH Client    │
└────────────────────────┼────────┘
                         │  SSH (TCP 22)
                         ▼
               Remote Target Device
```

- The **browser** only speaks HTTP/WebSocket to CloudShell.
- CloudShell **opens and owns** the SSH connection to the target.
- The terminal stream is proxied byte-for-byte between xterm.js and AsyncSSH.

---

## ✨ Features

### MVP (v1.0)

- [ ] **Device Manager** — Add, edit, delete SSH target devices
  - Fields: name, hostname/IP, port, username, auth method (password / SSH key)
  - SSH private keys stored encrypted on disk, referenced by device record
- [ ] **Web Terminal** — Full interactive SSH terminal in the browser
  - xterm.js with proper resize (SIGWINCH propagation)
  - Copy/paste support
  - Reconnect on disconnect
- [ ] **Multi-tab sessions** — Open multiple terminals simultaneously (different devices)
- [ ] **Single-user Auth** — Login page with username + password (JWT session)
  - Credentials configured via environment variables or first-run wizard
- [ ] **Responsive UI** — Works on desktop and tablet
- [ ] **Docker Compose deployment** — Single `docker-compose up` to run

### Future (v2.0+)

- [ ] Multi-user profiles with per-user device ACLs
- [ ] Session recording & playback (asciinema format)
- [ ] SFTP file browser
- [ ] SSH key pair generator built into UI
- [ ] 2FA (TOTP)
- [ ] Dark / light theme toggle
- [ ] Device grouping / tagging

---

## 🗄️ Data Model

### `devices` table

```sql
id          INTEGER PRIMARY KEY
name        TEXT NOT NULL
hostname    TEXT NOT NULL
port        INTEGER DEFAULT 22
username    TEXT NOT NULL
auth_type   TEXT CHECK(auth_type IN ('password','key'))
password    TEXT  -- AES-256 encrypted at rest
key_path    TEXT  -- path to encrypted PEM file on disk
created_at  DATETIME
updated_at  DATETIME
```

### `settings` table

```sql
key   TEXT PRIMARY KEY
value TEXT
```

*(stores admin credentials hash, app config, etc.)*

---

## 🔐 Security Considerations

| Concern | Mitigation |
|---|---|
| Stored passwords | AES-256-GCM encryption with a key derived from `SECRET_KEY` env var |
| SSH private keys | Stored under `/data/keys/`, file permissions `600`, encrypted with same key |
| Web session | Short-lived JWT (configurable TTL, default 8 h) |
| HTTPS | Recommended to run behind a reverse proxy (Nginx / Caddy) with TLS |
| WebSocket hijacking | JWT validated on every WebSocket upgrade request |
| Host key verification | `known_hosts` file persisted in `/data/known_hosts`; UI warns on mismatch |

---

## 📁 Project Structure

```
CloudShell/
├── backend/
│   ├── main.py               # FastAPI app entry point
│   ├── routers/
│   │   ├── auth.py           # Login / token endpoints
│   │   ├── devices.py        # CRUD for SSH targets
│   │   └── terminal.py       # WebSocket SSH proxy
│   ├── models/
│   │   └── device.py         # SQLAlchemy models
│   ├── services/
│   │   ├── ssh.py            # AsyncSSH session manager
│   │   └── crypto.py         # Encrypt/decrypt credentials
│   ├── database.py           # DB init & session factory
│   └── config.py             # Settings from env vars
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Terminal.tsx  # xterm.js wrapper
│   │   │   ├── DeviceList.tsx
│   │   │   ├── DeviceForm.tsx
│   │   │   └── Sidebar.tsx
│   │   ├── pages/
│   │   │   ├── Login.tsx
│   │   │   └── Dashboard.tsx
│   │   ├── api/              # REST + WS client wrappers
│   │   └── App.tsx
│   ├── index.html
│   └── vite.config.ts
│
├── docker/
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── SPECS.md
```

---

## 🐳 Docker Compose (planned)

```yaml
services:
  cloudshell:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - cloudshell_data:/data
    environment:
      - SECRET_KEY=changeme
      - ADMIN_USER=admin
      - ADMIN_PASSWORD=changeme
      - TOKEN_TTL_HOURS=8

volumes:
  cloudshell_data:
```

---

## 🚀 Getting Started (planned)

```bash
git clone https://github.com/youruser/CloudShell
cd CloudShell
cp .env.example .env        # edit credentials
docker compose up -d
# Open http://localhost:8080
```

---

## 📋 Milestones

| Status | Milestone | Scope |
|---|---|---|
| ✅ | **M1** | Project scaffold, Docker image, FastAPI hello-world, React + xterm.js boilerplate |
| ✅ | **M2** | Device CRUD API + UI, SQLite persistence |
| ✅ | **M3** | WebSocket SSH proxy (password auth), working terminal |
| ✅ | **M4** | SSH key auth, credential encryption at rest |
| ❌ | **M5** | Login / JWT auth, session expiry |
| ❌ | **M6** | Polish UI, error handling, reconnect logic, README |
| ❌ | **M7** | Docker Compose single-command deploy, public release |

## Language specification

- Strict NO EMOJI policy
- Test coverage for all new features and bug fixes

### Python

- Always use venv for virtual environments
  - Always activate the virtual environment before installing dependencies
  - Use requirements.txt to manage dependencies
- Use logging library with appropriate log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - Use lazy formatting for log messages (e.g. logging.debug("Message: %s", variable))
- Follow PEP 8 style guide for Python code
- Use type hints for function signatures and variable declarations
- Always add docstrings to all public modules, functions, and classes

### Testing

- Create reusable GitHub workflow templates for common testing scenarios
- Use pytest for unit and integration tests
- Aim for 100% test coverage on new features
- Include tests for edge cases and error conditions
- Run tests on every merge request

