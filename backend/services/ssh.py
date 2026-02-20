"""
SSH session manager.

Each active session is identified by a UUID (session_id).
Sessions are created, streamed over a WebSocket, and torn down on disconnect.

Wire protocol
─────────────
Browser → Server (binary WebSocket frames):
  • Regular input:  raw bytes forwarded straight to SSH stdin
  • Resize signal:  a single JSON frame  {"type":"resize","cols":<n>,"rows":<n>}

Server → Browser (binary WebSocket frames):
  • Raw bytes from SSH stdout+stderr concatenated
"""
import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncssh
from fastapi import WebSocket

log = logging.getLogger(__name__)

# ── Session store ─────────────────────────────────────────────────────────────

@dataclass
class _Session:
    conn: asyncssh.SSHClientConnection
    process: asyncssh.SSHClientProcess | None = field(default=None)


_sessions: dict[str, _Session] = {}


# ── known_hosts helper ────────────────────────────────────────────────────────

# ── known_hosts / accept-new policy ──────────────────────────────────────────

def _known_hosts_path() -> str | None:
    """Return the known_hosts file path if DATA_DIR is set, else None (trust-all)."""
    data_dir = os.environ.get("DATA_DIR")
    if not data_dir:
        return None
    path = os.path.join(data_dir, "known_hosts")
    os.makedirs(data_dir, exist_ok=True)
    if not os.path.exists(path):
        open(path, "w", encoding="utf-8").close()
    return path


def _make_accept_new_client(known_hosts_path: str) -> type:
    """
    Return an SSHClient subclass implementing OpenSSH's accept-new policy:

    - If the host is already in known_hosts, the key MUST match (strict).
    - If the host is not yet known, the key is accepted and persisted.
    """
    class _AcceptNewClient(asyncssh.SSHClient):
        """SSHClient with accept-new host key policy."""

        def validate_host_public_key(
            self,
            host: str,
            addr: str,
            port: int,
            key: asyncssh.SSHKey,
        ) -> bool:
            """Accept new hosts; enforce stored key for known hosts."""
            try:
                known = asyncssh.read_known_hosts(known_hosts_path)
                trusted, _, _ = known.match(host, addr, port)[:3]
            except Exception:  # noqa: BLE001
                trusted = []

            if trusted:
                # Host is known — check whether the presented key matches
                presented = key.export_public_key().decode()
                for stored_key in trusted:
                    if stored_key.export_public_key().decode() == presented:
                        return True
                log.warning(
                    "Host key mismatch for %s — rejecting connection", host
                )
                return False

            # Host is new — persist the key and accept it
            entry = f"{host} {key.export_public_key().decode().strip()}\n"
            with open(known_hosts_path, "a", encoding="utf-8") as f:
                f.write(entry)
            log.info("Learned new host key for %s — added to known_hosts", host)
            return True

    return _AcceptNewClient


# ── Public API ────────────────────────────────────────────────────────────────

async def create_session(
    hostname: str,
    port: int,
    username: str,
    password: str | None = None,
    private_key_path: str | None = None,
    known_hosts: str | None = "auto",
) -> str:
    """
    Open an SSH connection and return a session_id.

    known_hosts="auto"  → accept-new policy backed by /data/known_hosts
    known_hosts=None    → disable host-key checking entirely (dev only)
    known_hosts=<path>  → strict checking against that file
    """
    session_id = str(uuid.uuid4())

    connect_kwargs: dict[str, Any] = {
        "host": hostname,
        "port": port,
        "username": username,
    }

    if known_hosts == "auto":
        kh_path = _known_hosts_path()
        if kh_path:
            # Use accept-new client: validates known hosts strictly,
            # persists new host keys on first connection.
            connect_kwargs["client_factory"] = _make_accept_new_client(kh_path)
            connect_kwargs["known_hosts"] = None  # validation done in client
        else:
            # No DATA_DIR — disable host-key checking (dev/test only)
            connect_kwargs["known_hosts"] = None
    else:
        connect_kwargs["known_hosts"] = known_hosts

    if password is not None:
        connect_kwargs["password"] = password
    if private_key_path is not None:
        connect_kwargs["client_keys"] = [private_key_path]

    # Let connection errors propagate — the caller (router) will catch them
    # and send a proper error frame to the WebSocket client.
    conn = await asyncssh.connect(**connect_kwargs)
    _sessions[session_id] = _Session(conn=conn)
    log.info("SSH session %s opened → %s@%s:%s", session_id[:8], username, hostname, port)
    return session_id


async def stream_session(session_id: str, websocket: WebSocket) -> None:
    """Bridge a WebSocket to an SSH interactive shell. Frames are binary."""
    entry = _sessions.get(session_id)
    if entry is None:
        await _ws_error(websocket, "Session not found")
        await websocket.close(code=4004)
        return

    conn = entry.conn

    # Wait for an initial resize frame from the browser so the PTY is created
    # with the correct dimensions rather than the hardcoded 80x24 fallback.
    cols, rows = 220, 50  # sensible fallback if no resize frame arrives in time
    try:
        msg = await asyncio.wait_for(websocket.receive(), timeout=3.0)
        raw = msg.get("bytes") or (msg.get("text", "").encode() if msg.get("text") else None)
        if raw:
            try:
                ctrl = json.loads(raw)
                if ctrl.get("type") == "resize":
                    cols = int(ctrl["cols"])
                    rows = int(ctrl["rows"])
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    except asyncio.TimeoutError:
        pass

    try:
        process: asyncssh.SSHClientProcess = await conn.create_process(
            term_type="xterm-256color",
            term_size=(cols, rows),
            encoding=None,   # raw bytes — no codec in the bridge layer
            stderr=asyncssh.STDOUT,  # merge stderr into stdout stream
        )
    except asyncssh.Error as exc:
        await _ws_error(websocket, f"Failed to open shell: {exc}")
        await websocket.close(code=4011)
        return

    entry.process = process

    async def ws_to_ssh() -> None:
        """Read from WebSocket, write to SSH stdin or handle control frames."""
        try:
            while True:
                msg = await websocket.receive()
                # receive() returns {"type": "websocket.receive", "bytes": ..., "text": ...}
                raw = msg.get("bytes") or (msg.get("text", "").encode() if msg.get("text") else None)
                if raw is None:
                    break
                message = raw if isinstance(raw, bytes) else raw.encode()
                # Control frames are valid UTF-8 JSON starting with '{'
                if message[:1] == b"{":
                    try:
                        ctrl = json.loads(message)
                        if ctrl.get("type") == "resize":
                            cols = int(ctrl["cols"])
                            rows = int(ctrl["rows"])
                            process.change_terminal_size(cols, rows)
                        continue
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass  # Not a control frame — fall through and send as-is
                process.stdin.write(message)
        except Exception:  # noqa: BLE001
            log.debug("ws_to_ssh ended for %s", session_id[:8])

    async def ssh_to_ws() -> None:
        """Read from SSH stdout, write binary frames to WebSocket."""
        try:
            while True:
                # Read whatever is available immediately — don't wait to fill a buffer.
                # This ensures character echoes from bash readline arrive without delay.
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                await websocket.send_bytes(chunk)
        except Exception:  # noqa: BLE001
            log.debug("ssh_to_ws ended for %s", session_id[:8])

    log.info("Streaming session %s", session_id[:8])
    _, pending = await asyncio.wait(
        [
            asyncio.create_task(ws_to_ssh()),
            asyncio.create_task(ssh_to_ws()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()

    log.info("Session %s stream ended", session_id[:8])

    # Close the WebSocket cleanly so the browser detects the disconnect.
    try:
        await websocket.close(code=1000)
    except Exception:  # noqa: BLE001
        pass


async def close_session(session_id: str) -> None:
    entry = _sessions.pop(session_id, None)
    if entry:
        try:
            entry.conn.close()
            await entry.conn.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        log.info("SSH session %s closed", session_id[:8])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _ws_error(websocket: WebSocket, message: str) -> None:
    """Send a human-readable error message as a binary frame to the terminal."""
    try:
        text = f"\r\n\x1b[31m[CloudShell error: {message}]\x1b[0m\r\n"
        await websocket.send_bytes(text.encode())
    except Exception:  # noqa: BLE001
        pass
