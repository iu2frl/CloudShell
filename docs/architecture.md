# Architecture

## Overview

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

## Project structure

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
├── docs/                     # Extended documentation
├── scripts/
│   └── smoke-test-docker.sh  # Two-container Docker smoke test
│
├── Dockerfile.backend        # FastAPI backend image
├── Dockerfile.frontend       # Node build → nginx:alpine image
├── docker-compose.yml
├── requirements.txt
└── .env.example
```
