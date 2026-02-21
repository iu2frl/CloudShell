# Configuration

All configuration is via environment variables (or a `.env` file):

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | *(required)* | Random secret used to sign JWTs and derive the encryption key for stored credentials. **Change this in production.** |
| `ADMIN_USER` | `admin` | Login username |
| `ADMIN_PASSWORD` | `changeme` | Initial login password. After first login you can change it via the UI. |
| `TOKEN_TTL_HOURS` | `8` | JWT lifetime in hours. The frontend silently refreshes 10 minutes before expiry. |
| `AUDIT_RETENTION_DAYS` | `7` | Number of days to retain audit log entries. Entries older than this are pruned automatically on startup. |
| `DATA_DIR` | `/data` | Directory where the SQLite database, SSH key files, and known_hosts are stored. Mount this as a Docker volume. |
| `CORS_ORIGINS` | *(unset)* | Comma-separated list of allowed CORS origins. Leave unset when running behind Nginx (same-origin). Set to your frontend URL (e.g. `https://cloudshell.example.com`) when running the backend standalone. |

## Secret key generation

```bash
openssl rand -hex 32
```

## Security notes

CloudShell is designed with defense-in-depth for the sensitive data it handles:

- **Secrets at rest**: Device passwords and uploaded SSH private keys are encrypted
  using AES-256-GCM. The encryption key is derived from the `SECRET_KEY`
  environment variable via PBKDF2 with 260 000 iterations. Encrypted files live in
  `DATA_DIR` (a Docker volume by default) and are never stored in plaintext.

- **JWT sessions**: Tokens are signed with HS256 using `SECRET_KEY` and carry a
  `jti` (unique ID) that is recorded in a revocation table when the user logs out
  or refreshes. On each server start a fresh `boot_id` is generated and embedded
  in every token; if the process restarts, all prior tokens are rejected
  immediately, forcing a new login.

- **Token handling**: The JWT is stored in browser `localStorage` and appended to
  the terminal WebSocket URL as a query parameter. In production always run
  behind HTTPS/WSS so the token is protected in transit.

- **Admin credentials**: The admin password is bcrypt‑hashed in the database after
  first change. Until then the value from `ADMIN_PASSWORD` is compared directly
  (use a strong initial password and change it on first login).

- **Configuration**: `SECRET_KEY` should be a random 32‑byte hex string
  (`openssl rand -hex 32`). Treat it like a master key; if it is leaked all
  encrypted data and sessions can be compromised.
  
### Summary

| Concern | Mitigation |
| --- | --- |
| Stored passwords | AES-256-GCM, key derived from `SECRET_KEY` via PBKDF2 (260k iterations) |
| SSH private keys | Encrypted `.enc` files, `chmod 600`, never stored in plaintext |
| Web session | Short-lived JWT (HS256), revocation via DB deny-list, silent refresh |
| Token in WebSocket | Passed as `?token=` query param on WS upgrade; use HTTPS/WSS in production |
| Host key verification | `known_hosts` file persisted in `DATA_DIR`; accept-new policy |
| Admin password | bcrypt-hashed in DB after first change; env-var fallback on first boot only |
