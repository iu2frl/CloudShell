"""
services/ftp.py — FTP/FTPS session manager using aioftp.

Each session is identified by a UUID.  The session holds an open aioftp
Client connection.  Sessions are created via ``open_ftp_session`` and
closed via ``close_ftp_session``.

Supported protocols:
  - ftp  : plain FTP (RFC 959)
  - ftps : explicit FTPS — connects in plain text, then sends AUTH TLS to
           upgrade (RFC 4217).  This is what virtually all real-world servers
           on port 21 expect.  aioftp's ``upgrade_to_tls()`` implements this
           via the ``AUTH TLS`` + ``PBSZ 0`` + ``PROT P`` command sequence.

           Do NOT pass ssl= to the Client constructor for FTPS — that enables
           implicit TLS (wraps the control socket in TLS from the very first
           byte, typically port 990) and will cause a
           ``[SSL: WRONG_VERSION_NUMBER]`` error on standard port-21 servers.

Note on encoding:
  Many FTP servers (especially older or non-English ones) send their banner
  and directory listings in ISO-8859-1 / Latin-1 rather than UTF-8.  aioftp
  defaults to UTF-8 and will raise a UnicodeDecodeError on those servers.
  We default to ``latin-1`` because it is a strict superset of ASCII and
  never raises a decode error (every byte 0x00–0xFF is valid Latin-1).
"""
import asyncio
import logging
import ssl
import uuid
import hashlib
from typing import Callable, Optional
from dataclasses import dataclass, field

import aioftp

log = logging.getLogger(__name__)

# -- Session store -------------------------------------------------------------


@dataclass
class _FtpSession:
    """Holds an active aioftp client and associated metadata."""

    client: aioftp.Client
    device_label: str = ""
    cloudshell_user: str = ""
    source_ip: str | None = None
    use_tls: bool = False
    _cwd: str = field(default="/", init=False)
    # Per-session lock to serialize control/data channel operations. Lazily
    # created to avoid creating an asyncio.Lock at import time.
    lock: asyncio.Lock | None = field(default=None, init=False)


_ftp_sessions: dict[str, _FtpSession] = {}


class FTPSCertificateUnavailableError(RuntimeError):
    """Raised when no peer TLS certificate is available from an FTPS connection."""


class FTPSCertificateMismatchError(RuntimeError):
    """Raised when the presented FTPS certificate thumbprint does not match the expected one."""

    def __init__(self, expected: str, presented: str):
        super().__init__("FTPS certificate thumbprint mismatch")
        self.expected = expected
        self.presented = presented


# -- Helpers -------------------------------------------------------------------


def _make_ssl_context() -> ssl.SSLContext:
    """
    Return an SSL context for FTPS thumbprint validation.

    X.509 trust is intentionally disabled here because CloudShell validates the
    presented certificate by explicit per-device SHA-256 thumbprint pinning.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _format_thumbprint_sha256(cert_der: bytes) -> str:
    """Return uppercase colon-separated SHA-256 certificate thumbprint."""
    digest = hashlib.sha256(cert_der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def get_ftps_peer_thumbprint(ftp_client: aioftp.Client) -> str:
    """Read the active FTPS peer certificate and return its SHA-256 thumbprint."""
    ssl_obj = ftp_client.stream.writer.get_extra_info("ssl_object")
    if ssl_obj is None:
        raise FTPSCertificateUnavailableError("TLS socket does not expose ssl_object")

    cert_der = ssl_obj.getpeercert(binary_form=True)
    if not cert_der:
        raise FTPSCertificateUnavailableError("Peer certificate is unavailable")

    return _format_thumbprint_sha256(cert_der)


async def probe_ftps_thumbprint(hostname: str, port: int) -> str:
    """Connect using explicit FTPS (AUTH TLS), return server cert thumbprint, and close."""
    ftp_client = aioftp.Client(
        encoding="latin-1",
        connection_timeout=15,
    )
    try:
        await ftp_client.connect(hostname, port)
        ssl_ctx = _make_ssl_context()
        await ftp_client.upgrade_to_tls(sslcontext=ssl_ctx)
        return get_ftps_peer_thumbprint(ftp_client)
    finally:
        try:
            await ftp_client.quit()
        except Exception:  # noqa: BLE001
            pass


# -- Public API ----------------------------------------------------------------


async def open_ftp_session(
    hostname: str,
    port: int,
    username: str,
    password: str | None = None,
    use_tls: bool = False,
    device_label: str = "",
    cloudshell_user: str = "",
    source_ip: str | None = None,
    expected_ftps_thumbprint: str | None = None,
) -> str:
    """
    Open an FTP (or explicit-FTPS) connection and return a session_id.

    For FTPS we connect in plain text first and then call ``upgrade_to_tls()``
    which sends ``AUTH TLS`` and upgrades both the control and data channels.
    This is the correct approach for the vast majority of FTPS servers on
    port 21 and avoids the ``[SSL: WRONG_VERSION_NUMBER]`` error that occurs
    when TLS is applied to the raw socket before any FTP greeting is received.

    We use ``encoding="latin-1"`` so that servers whose banners / directory
    listings are in ISO-8859-1 (a common case for non-English servers) don't
    raise a ``UnicodeDecodeError``.  Latin-1 is a strict superset of ASCII
    and is always decodable without error.

    Connection/auth errors propagate to the caller (the router handles them).
    """
    session_id = str(uuid.uuid4())

    # Always create a plain client — no ssl= here, even for FTPS.
    # For FTPS, TLS is negotiated *after* the initial greeting via AUTH TLS.
    ftp_client = aioftp.Client(
        encoding="latin-1",
        connection_timeout=15,
    )

    await ftp_client.connect(hostname, port)

    if use_tls:
        # Explicit FTPS: send AUTH TLS over the plain connection, then upgrade.
        ssl_ctx = _make_ssl_context()
        await ftp_client.upgrade_to_tls(sslcontext=ssl_ctx)
        presented_thumbprint = get_ftps_peer_thumbprint(ftp_client)
        if expected_ftps_thumbprint and presented_thumbprint != expected_ftps_thumbprint:
            try:
                await ftp_client.quit()
            except Exception:  # noqa: BLE001
                pass
            raise FTPSCertificateMismatchError(
                expected=expected_ftps_thumbprint,
                presented=presented_thumbprint,
            )

    await ftp_client.login(username or "anonymous", password or "")

    _ftp_sessions[session_id] = _FtpSession(
        client=ftp_client,
        device_label=device_label,
        cloudshell_user=cloudshell_user,
        source_ip=source_ip,
        use_tls=use_tls,
    )
    log.info(
        "FTP%s session %s opened -> %s@%s:%s",
        "S" if use_tls else "",
        session_id[:8],
        username,
        hostname,
        port,
    )
    return session_id


async def close_ftp_session(session_id: str) -> None:
    """Close the FTP connection and remove the session from the store."""
    entry = _ftp_sessions.pop(session_id, None)
    if entry:
        try:
            await entry.client.quit()
        except Exception:  # noqa: BLE001
            pass
        log.info("FTP session %s closed", session_id[:8])


def get_ftp_session(session_id: str) -> _FtpSession | None:
    """Return the session entry or None if not found."""
    return _ftp_sessions.get(session_id)


def get_ftp_session_meta(session_id: str) -> tuple[str, str, str | None]:
    """Return (device_label, cloudshell_user, source_ip)."""
    entry = _ftp_sessions.get(session_id)
    if entry:
        return entry.device_label, entry.cloudshell_user, entry.source_ip
    return "", "", None


# -- Filesystem helpers --------------------------------------------------------


async def list_directory(session_id: str, remote_path: str) -> list[dict]:
    """
    List the contents of ``remote_path``.

    Returns a list of dicts with keys:
      name, path, size, is_dir, permissions, modified
    """
    entry = _ftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("FTP session not found")

    result = []
    # Ensure a per-session lock exists and serialize the listing operation.
    if entry.lock is None:
        entry.lock = asyncio.Lock()
    async with entry.lock:
        async for path_obj, info in entry.client.list(remote_path, recursive=False):
            name = path_obj.name
            if name in (".", ".."):
                continue
            is_dir = info.get("type") == "dir"
            # Build a clean joined path without double-slashes
            parent = remote_path.rstrip("/")
            full_path = f"{parent}/{name}" if parent else f"/{name}"
            size = int(info.get("size", 0) or 0)
            modify = info.get("modify", "")
            # modify is a 14-char timestamp: YYYYMMDDHHMMSS
            modified_ts = _parse_ftp_mtime(modify)
            result.append(
                {
                    "name": name,
                    "path": full_path,
                    "size": size,
                    "is_dir": is_dir,
                    "permissions": info.get("unix.mode", None),
                    "modified": modified_ts,
                }
            )

    result.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return result


def _parse_ftp_mtime(modify: str) -> int:
    """Convert an FTP MLSD modify timestamp (YYYYMMDDHHMMSS) to a Unix epoch int."""
    if not modify or len(modify) < 14:
        return 0
    try:
        from datetime import datetime, timezone
        dt = datetime(
            int(modify[0:4]),
            int(modify[4:6]),
            int(modify[6:8]),
            int(modify[8:10]),
            int(modify[10:12]),
            int(modify[12:14]),
            tzinfo=timezone.utc,
        )
        return int(dt.timestamp())
    except (ValueError, OverflowError):
        return 0


async def read_file_bytes(session_id: str, remote_path: str) -> bytes:
    """Download a remote file and return its raw bytes."""
    entry = _ftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("FTP session not found")
    
    log.debug(
        "FTP download starting: path=%s, session=%s",
        remote_path,
        session_id[:8],
    )
    
    try:
        chunks: list[bytes] = []
        if entry.lock is None:
            entry.lock = asyncio.Lock()
        async with entry.lock:
            async with entry.client.download_stream(remote_path) as stream:
                chunk_count = 0
                async for chunk in stream.iter_by_block():
                    chunks.append(chunk)
                chunk_count += 1
        
        total_size = len(b"".join(chunks))
        file_size_mb = total_size / (1024 * 1024)
        log.info(
            "FTP download completed: path=%s, size=%s bytes (%.2f MB), chunks=%d, session=%s",
            remote_path,
            total_size,
            file_size_mb,
            chunk_count,
            session_id[:8],
        )
        return b"".join(chunks)
    except Exception as exc:
        log.error(
            "FTP download failed for %s: %s (session %s)",
            remote_path,
            exc,
            session_id[:8],
        )
        raise


async def write_file_bytes(
    session_id: str,
    remote_path: str,
    data: bytes,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> None:
    """Upload raw bytes to a remote file (overwrites if it exists)."""
    entry = _ftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("FTP session not found")
    
    file_size = len(data)
    file_size_mb = file_size / (1024 * 1024)
    log.debug(
        "FTP upload starting: path=%s, size=%s bytes (%.2f MB), session=%s",
        remote_path,
        file_size,
        file_size_mb,
        session_id[:8],
    )
    
    try:
        if entry.lock is None:
            entry.lock = asyncio.Lock()
        async with entry.lock:
            async with entry.client.upload_stream(remote_path) as stream:
                log.debug(
                    "FTP upload stream opened for %s (session %s)",
                    remote_path,
                    session_id[:8],
                )

                # Write in chunks to avoid timeout and allow progress monitoring
                chunk_size = 1024 * 1024  # 1 MB chunks
                bytes_written = 0
                chunk_num = 0

                while bytes_written < file_size:
                    chunk_num += 1
                    end = min(bytes_written + chunk_size, file_size)
                    chunk = data[bytes_written:end]

                    try:
                        # Each chunk has 10-minute timeout
                        await asyncio.wait_for(stream.write(chunk), timeout=600)
                    except asyncio.TimeoutError as exc:
                        log.error(
                            "FTP upload timeout at chunk %d (%.2f MB of %.2f MB), session=%s",
                            chunk_num,
                            bytes_written / (1024 * 1024),
                            file_size_mb,
                            session_id[:8],
                        )
                        raise TimeoutError(
                            f"FTP upload timed out at chunk {chunk_num} after {bytes_written} bytes"
                        ) from exc

                    bytes_written = end

                    if progress_callback:
                        try:
                            progress_callback(bytes_written)
                        except Exception:
                            log.debug("FTP progress callback raised, ignoring")

                    progress_mb = bytes_written / (1024 * 1024)
                    log.debug(
                        "FTP upload progress: path=%s, chunk=%d, progress=%.2f MB / %.2f MB, session=%s",
                        remote_path,
                        chunk_num,
                        progress_mb,
                        file_size_mb,
                        session_id[:8],
                    )

                log.debug(
                    "FTP upload stream write completed for %s (session %s)",
                    remote_path,
                    session_id[:8],
                )
    except Exception as exc:
        log.error(
            "FTP upload failed for %s (%.2f MB): %s (session %s)",
            remote_path,
            file_size_mb,
            exc,
            session_id[:8],
        )
        raise


async def delete_remote(
    session_id: str,
    remote_path: str,
    is_dir: bool,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> int:
    """Delete a remote file or directory (recursively if non-empty).

    Returns the total number of items deleted.  For a single file this is 1.
    For a directory tree the count includes every file and sub-directory plus
    the root directory itself.

    ``progress_callback(deleted_count)`` is called after each individual
    item is removed so callers can report progress.
    """
    entry = _ftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("FTP session not found")

    # Shared counter across all recursive calls so progress is cumulative
    total_deleted = [0]

    async def _delete_tree(client: aioftp.Client, path: str) -> None:
        """Depth-first recursive delete.  Must be called under the session lock."""
        # List children
        children: list[tuple[str, bool]] = []
        async for child_path, info in client.list(path, recursive=False):
            name = child_path.name
            if name in (".", ".."):
                continue
            parent = path.rstrip("/")
            full = f"{parent}/{name}" if parent else f"/{name}"
            children.append((full, info.get("type") == "dir"))

        # Recurse into sub-directories first, then delete files
        for child_full, child_is_dir in children:
            if child_is_dir:
                await _delete_tree(client, child_full)
            else:
                await client.remove_file(child_full)
                total_deleted[0] += 1
                if progress_callback:
                    try:
                        progress_callback(total_deleted[0])
                    except Exception:
                        pass

        # Now the directory is empty -- remove it
        await client.remove_directory(path)
        total_deleted[0] += 1
        if progress_callback:
            try:
                progress_callback(total_deleted[0])
            except Exception:
                pass

    try:
        if entry.lock is None:
            entry.lock = asyncio.Lock()
        async with entry.lock:
            if is_dir:
                log.debug(
                    "FTP recursive delete directory: path=%s, session=%s",
                    remote_path,
                    session_id[:8],
                )
                await _delete_tree(entry.client, remote_path)
            else:
                log.debug(
                    "FTP delete file: path=%s, session=%s",
                    remote_path,
                    session_id[:8],
                )
                await entry.client.remove_file(remote_path)
                total_deleted[0] = 1
                if progress_callback:
                    try:
                        progress_callback(1)
                    except Exception:
                        pass

        log.info(
            "FTP delete successful: %s (%s, %d items), session=%s",
            remote_path,
            "directory" if is_dir else "file",
            total_deleted[0],
            session_id[:8],
        )
    except Exception as exc:
        log.error(
            "FTP delete failed for %s: %s (session %s)",
            remote_path,
            exc,
            session_id[:8],
        )
        raise

    return total_deleted[0]


async def rename_remote(session_id: str, old_path: str, new_path: str) -> None:
    """Rename/move a remote path."""
    entry = _ftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("FTP session not found")
    
    try:
        if entry.lock is None:
            entry.lock = asyncio.Lock()
        async with entry.lock:
            log.debug(
                "FTP rename: %s -> %s, session=%s",
                old_path,
                new_path,
                session_id[:8],
            )
            await entry.client.rename(old_path, new_path)

        log.info(
            "FTP rename successful: %s -> %s, session=%s",
            old_path,
            new_path,
            session_id[:8],
        )
    except Exception as exc:
        log.error(
            "FTP rename failed: %s -> %s, error=%s (session %s)",
            old_path,
            new_path,
            exc,
            session_id[:8],
        )
        raise


async def mkdir_remote(session_id: str, remote_path: str) -> None:
    """Create a remote directory."""
    entry = _ftp_sessions.get(session_id)
    if entry is None:
        raise ValueError("FTP session not found")
    
    try:
        if entry.lock is None:
            entry.lock = asyncio.Lock()
        async with entry.lock:
            log.debug(
                "FTP mkdir: path=%s, session=%s",
                remote_path,
                session_id[:8],
            )
            await entry.client.make_directory(remote_path)

        log.info(
            "FTP mkdir successful: path=%s, session=%s",
            remote_path,
            session_id[:8],
        )
    except Exception as exc:
        log.error(
            "FTP mkdir failed for %s: %s (session %s)",
            remote_path,
            exc,
            session_id[:8],
        )
        raise
