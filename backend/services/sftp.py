"""
services/sftp.py — SFTP session manager using asyncssh.

Each SFTP session is identified by a UUID.  The session holds an open SSH
connection and an asyncssh SFTPClient.  Sessions are created via
``open_sftp_session`` and closed via ``close_sftp_session``.
"""
import logging
import uuid
from dataclasses import dataclass

import asyncssh

from backend.services.ssh import _known_hosts_path, _make_accept_new_client

log = logging.getLogger(__name__)

# ── Session store ─────────────────────────────────────────────────────────────

@dataclass
class _SftpSession:
    conn: asyncssh.SSHClientConnection
    sftp: asyncssh.SFTPClient
    device_label: str = ""
    cloudshell_user: str = ""
    source_ip: str | None = None


_sftp_sessions: dict[str, _SftpSession] = {}


# ── Public API ────────────────────────────────────────────────────────────────

async def open_sftp_session(
    hostname: str,
    port: int,
    username: str,
    password: str | None = None,
    private_key_path: str | None = None,
    known_hosts: str | None = "auto",
    device_label: str = "",
    cloudshell_user: str = "",
    source_ip: str | None = None,
) -> str:
    """
    Open an SSH connection, start an SFTP client, and return a session_id.

    Connection/auth errors propagate to the caller (router handles them).
    """
    session_id = str(uuid.uuid4())

    connect_kwargs: dict = {
        "host": hostname,
        "port": port,
        "username": username,
    }

    if known_hosts == "auto":
        kh_path = _known_hosts_path()
        if kh_path:
            connect_kwargs["client_factory"] = _make_accept_new_client(kh_path)
            connect_kwargs["known_hosts"] = None
        else:
            connect_kwargs["known_hosts"] = None
    else:
        connect_kwargs["known_hosts"] = known_hosts

    if password is not None:
        connect_kwargs["password"] = password
    if private_key_path is not None:
        connect_kwargs["client_keys"] = [private_key_path]

    conn = await asyncssh.connect(**connect_kwargs)
    sftp = await conn.start_sftp_client()

    _sftp_sessions[session_id] = _SftpSession(
        conn=conn,
        sftp=sftp,
        device_label=device_label,
        cloudshell_user=cloudshell_user,
        source_ip=source_ip,
    )
    log.info(
        "SFTP session %s opened -> %s@%s:%s",
        session_id[:8], username, hostname, port,
    )
    return session_id


async def close_sftp_session(session_id: str) -> None:
    """Close the SFTP client and underlying SSH connection."""
    entry = _sftp_sessions.pop(session_id, None)
    if entry:
        try:
            entry.sftp.exit()
        except Exception:  # noqa: BLE001
            pass
        try:
            entry.conn.close()
            await entry.conn.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        log.info("SFTP session %s closed", session_id[:8])


def get_sftp_session(session_id: str) -> _SftpSession | None:
    """Return the session entry or None if not found."""
    return _sftp_sessions.get(session_id)


def get_sftp_session_meta(session_id: str) -> tuple[str, str, str | None]:
    """Return (device_label, cloudshell_user, source_ip)."""
    entry = _sftp_sessions.get(session_id)
    if entry:
        return entry.device_label, entry.cloudshell_user, entry.source_ip
    return "", "", None


# ── Filesystem helpers ────────────────────────────────────────────────────────

async def list_directory(session_id: str, remote_path: str) -> list[dict]:
    """
    List the contents of ``remote_path``.

    Returns a list of dicts with keys:
      name, path, size, is_dir, permissions, modified
    """
    entry = _sftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("SFTP session not found")

    items = await entry.sftp.readdir(remote_path)
    result = []
    for item in items:
        if item.filename in (".", ".."):
            continue
        attrs = item.attrs
        is_dir = bool(attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY)
        raw_name = item.filename
        if isinstance(raw_name, bytes):
            filename: str = raw_name.decode("utf-8", errors="replace")
        elif isinstance(raw_name, str):
            filename = raw_name
        else:
            filename = str(raw_name)
        # Build a clean joined path without double-slashes
        if remote_path.endswith("/"):
            full_path = remote_path + filename
        else:
            full_path = remote_path + "/" + filename
        result.append({
            "name": item.filename,
            "path": full_path,
            "size": attrs.size if attrs.size is not None else 0,
            "is_dir": is_dir,
            "permissions": oct(attrs.permissions & 0o7777) if attrs.permissions is not None else None,
            "modified": attrs.mtime if attrs.mtime is not None else 0,
        })

    result.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return result


async def read_file_bytes(session_id: str, remote_path: str) -> bytes:
    """Download a remote file and return its raw bytes."""
    entry = _sftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("SFTP session not found")
    fh = await entry.sftp.open(remote_path, "rb")
    try:
        return await fh.read()
    finally:
        await fh.close()


async def write_file_bytes(
    session_id: str, remote_path: str, data: bytes
) -> None:
    """Upload raw bytes to a remote file (overwrites if exists)."""
    entry = _sftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("SFTP session not found")
    fh = await entry.sftp.open(remote_path, "wb")
    try:
        await fh.write(data)
    finally:
        await fh.close()


async def delete_remote(session_id: str, remote_path: str, is_dir: bool) -> None:
    """Delete a remote file or directory."""
    entry = _sftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("SFTP session not found")
    if is_dir:
        await entry.sftp.rmdir(remote_path)
    else:
        await entry.sftp.remove(remote_path)


async def rename_remote(
    session_id: str, old_path: str, new_path: str
) -> None:
    """Rename/move a remote path."""
    entry = _sftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("SFTP session not found")
    await entry.sftp.rename(old_path, new_path)


async def mkdir_remote(session_id: str, remote_path: str) -> None:
    """Create a remote directory."""
    entry = _sftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("SFTP session not found")
    await entry.sftp.mkdir(remote_path)
