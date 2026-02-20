"""
SSH session manager.

Each active session is identified by a UUID (session_id).
Sessions are created, streamed over a WebSocket, and torn down on disconnect.
"""
import asyncio
import uuid
from typing import Any

import asyncssh
from fastapi import WebSocket

_sessions: dict[str, Any] = {}


async def create_session(
    hostname: str,
    port: int,
    username: str,
    password: str | None = None,
    private_key_path: str | None = None,
    known_hosts: str | None = None,
) -> str:
    """Open an SSH connection and return a session_id."""
    session_id = str(uuid.uuid4())

    connect_kwargs: dict[str, Any] = {
        "host": hostname,
        "port": port,
        "username": username,
        "known_hosts": known_hosts,  # None = trust all (dev); set path in prod
    }
    if password is not None:
        connect_kwargs["password"] = password
    if private_key_path is not None:
        connect_kwargs["client_keys"] = [private_key_path]

    conn = await asyncssh.connect(**connect_kwargs)
    _sessions[session_id] = {"conn": conn, "process": None}
    return session_id


async def stream_session(session_id: str, websocket: WebSocket) -> None:
    """Bridge a WebSocket to an existing SSH session's interactive shell."""
    entry = _sessions.get(session_id)
    if entry is None:
        await websocket.close(code=4004)
        return

    conn: asyncssh.SSHClientConnection = entry["conn"]

    async with conn.create_process(
        term_type="xterm-256color",
        term_size=(80, 24),
    ) as process:
        entry["process"] = process

        async def ws_to_ssh():
            try:
                while True:
                    data = await websocket.receive_text()
                    if data.startswith("\x1b[8;"):
                        # resize sequence: ESC[8;<rows>;<cols>t
                        parts = data[4:].rstrip("t").split(";")
                        if len(parts) == 2:
                            rows, cols = int(parts[0]), int(parts[1])
                            process.change_terminal_size(cols, rows)
                    else:
                        process.stdin.write(data)
            except Exception:
                pass

        async def ssh_to_ws():
            try:
                async for chunk in process.stdout:
                    await websocket.send_text(chunk)
            except Exception:
                pass

        _, pending = await asyncio.wait(
            [
                asyncio.create_task(ws_to_ssh()),
                asyncio.create_task(ssh_to_ws()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()


async def close_session(session_id: str) -> None:
    entry = _sessions.pop(session_id, None)
    if entry:
        conn: asyncssh.SSHClientConnection = entry["conn"]
        conn.close()
        await conn.wait_closed()
