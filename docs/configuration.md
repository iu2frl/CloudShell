# Configuration

All configuration is via environment variables (or a `.env` file):

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | *(required)* | Random secret used to sign JWTs and derive the encryption key for stored credentials. **Change this in production.** |
| `ADMIN_USER` | `admin` | Login username |
| `ADMIN_PASSWORD` | `changeme` | Initial login password. After first login you can change it via the UI. |
| `TOKEN_TTL_HOURS` | `8` | JWT lifetime in hours. The frontend silently refreshes 10 minutes before expiry. |
| `DATA_DIR` | `/data` | Directory where the SQLite database, SSH key files, and known_hosts are stored. Mount this as a Docker volume. |
| `CORS_ORIGINS` | *(unset)* | Comma-separated list of allowed CORS origins. Leave unset when running behind Nginx (same-origin). Set to your frontend URL (e.g. `https://cloudshell.example.com`) when running the backend standalone. |

## Secret key generation

```bash
openssl rand -hex 32
```

## Security notes

| Concern | Mitigation |
| --- | --- |
| Stored passwords | AES-256-GCM, key derived from `SECRET_KEY` via PBKDF2 (260k iterations) |
| SSH private keys | Encrypted `.enc` files, `chmod 600`, never stored in plaintext |
| Web session | Short-lived JWT (HS256), revocation via DB deny-list, silent refresh |
| Token in WebSocket | Passed as `?token=` query param on WS upgrade; use HTTPS/WSS in production |
| Host key verification | `known_hosts` file persisted in `DATA_DIR`; accept-new policy |
| Admin password | bcrypt-hashed in DB after first change; env-var fallback on first boot only |
