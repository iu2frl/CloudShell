# User Guide

## Logging in

Navigate to the CloudShell URL and log in with your `ADMIN_USER` / `ADMIN_PASSWORD` credentials. The session is valid for `TOKEN_TTL_HOURS` hours; the frontend silently refreshes the token 10 minutes before expiry. The remaining session time is shown in the top-left corner of the dashboard as **Session: Xh Ym**.

## Managing devices

Click **Add device** in the left sidebar to register a new SSH target. Each device requires:

| Field | Description |
| --- | --- |
| Name | A friendly label shown in the sidebar and terminal tab |
| Hostname / IP | The SSH server address |
| Port | SSH port (default `22`) |
| Username | The SSH user to log in as |
| Auth type | `Password` or `SSH Key` |

Devices can be edited or deleted at any time via the pencil / trash icons in the sidebar. Credentials are always encrypted at rest and never returned to the frontend after saving.

## Password authentication

Select **Password** as the auth type and enter the remote user's password. The password is encrypted with AES-256-GCM before being stored.

## SSH key authentication

Select **SSH Key** as the auth type. There are three ways to supply the private key:

### Option 1 — Paste an existing key

Paste the contents of your existing private key (PEM format, e.g. `~/.ssh/id_rsa`) directly into the **Private Key** textarea.

### Option 2 — Load from a file

Click **Load file** next to the textarea. A file picker opens — select any `.pem`, `.key`, `id_rsa`, `id_ed25519`, or `id_ecdsa` file from your local machine. The key content is read in the browser and placed into the textarea; nothing is sent to the server until you click **Save**.

### Option 3 — Generate a new key pair

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

## Opening a terminal

Click any device name in the sidebar to open a terminal tab. Multiple tabs can be open simultaneously, each connected to a different device. The tab toolbar shows:

- **Device name** and `user@host:port`
- **Connection status badge** — Connecting / Connected / Disconnected / Error / Failed
- **Copy** button — copies `user@host:port` to clipboard
- **Reconnect** button — closes the current session and opens a fresh one

Typing `exit` or closing the remote shell ends the session cleanly and the badge switches to **Disconnected**.

## Changing the admin password

Click the **Session** timer badge in the top-left corner to open the change-password dialog. The new password takes effect immediately; the current session remains valid.

## Logging out

Click the **Logout** button in the top-right corner. The current JWT is revoked server-side so it cannot be reused even if intercepted.
