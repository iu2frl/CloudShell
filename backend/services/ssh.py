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

def _known_hosts_path() -> str | None:
    """Return the known_hosts file path if DATA_DIR is set, else None (trust-all)."""
    data_dir = os.environ.get("DATA_DIR")
    if not data_dir:
        return None
    path = os.path.join(data_dir, "known_hosts")
    # Touch the file so asyncssh can read/write it
    os.makedirs(data_dir, exist_ok=True)
    if not os.path.exists(path):
        open(path, "w").close()
    return path


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

    known_hosts="auto"  → use /data/known_hosts (accept-new policy)
    known_hosts=None    → disable host-key checking entirely (dev only)
    known_hosts=<path>  → use that file explicitly
    """
    session_id = str(uuid.uuid4())

    if known_hosts == "auto":
        known_hosts = _known_hosts_path()

    connect_kwargs: dict[str, Any] = {
        "host": hostname,
        "port": port,
        "username": username,
        # asyncssh accepts a path string, None (no check), or asyncssh.KnownHostsPolicy
        "known_hosts": known_hosts,
    }
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

    try:
        process: asyncssh.SSHClientProcess = await conn.create_process(
            term_type="xterm-256color",
            term_size=(80, 24),
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
                message = await websocket.receive_bytes()
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
            pass

    async def ssh_to_ws() -> None:
        """Read from SSH stdout, write binary frames to WebSocket."""
        try:
            async for chunk in process.stdout:
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                await websocket.send_bytes(chunk)
        except Exception:  # noqa: BLE001
            pass

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
