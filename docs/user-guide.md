# User Guide

## Logging in

Navigate to the CloudShell URL and log in with your `ADMIN_USER` / `ADMIN_PASSWORD` credentials. The session is valid for `TOKEN_TTL_HOURS` hours; the frontend silently refreshes the token 10 minutes before expiry. The remaining session time is shown in the top-left corner of the dashboard as **Session: Xh Ym**.

## Two-factor authentication (2FA)

CloudShell supports one-time verification codes from authenticator apps (such as Google Authenticator, Microsoft Authenticator, Authy, and similar apps).

### Why enable 2FA

2FA adds an extra verification step after your password, which helps protect your account if your password is exposed.

### Enable 2FA

1. Sign in to CloudShell.
2. Click the lock icon in the top bar to open **Two-Factor Authentication**.
3. Click the setup action to display a QR code.
4. In your authenticator app, add a new account and scan the QR code.
5. Enter the 6-digit code shown by your authenticator app.
6. Save your backup codes in a safe place before closing the dialog.

### Sign in with 2FA enabled

After entering username and password, CloudShell asks for a verification code.

- Enter the current 6-digit code from your authenticator app, or
- Enter one backup code if you do not have access to your authenticator app.

### Backup codes

- Backup codes are for emergency access.
- Each backup code works only once.
- Store them in a secure location that is separate from your everyday devices.
- Regenerate your backup codes by re-running 2FA setup if they are low or exhausted.

### Disable 2FA

1. Open **Two-Factor Authentication** from the lock icon.
2. Enter a current authenticator code.
3. Confirm disable.

### If a code is not accepted

Try the following:

- Check your phone time settings and ensure date and time are set automatically.
- Wait for a new code and try again.
- Use a backup code.
- If needed, disable and set up 2FA again from inside your account.

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
