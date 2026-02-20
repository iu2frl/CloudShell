"""
Encryption helpers for CloudShell.

All secrets (passwords, SSH private keys) are encrypted with AES-256-GCM
before being stored on disk.  The encryption key is derived once from
SECRET_KEY via PBKDF2-HMAC-SHA256 and then cached for the process lifetime.

Wire format (base64-encoded):
    [ 12-byte nonce ][ ciphertext + 16-byte GCM tag ]
"""
import base64
import functools
import logging
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.config import get_settings

log = logging.getLogger(__name__)

_SALT = b"cloudshell-static-salt-v1"  # static salt; effective key rotates via SECRET_KEY
_PBKDF2_ITERATIONS = 260_000


@functools.lru_cache(maxsize=1)
def _derive_key() -> bytes:
    """Derive a 256-bit AES key from SECRET_KEY (cached after first call)."""
    settings = get_settings()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=_PBKDF2_ITERATIONS,
    )
    key = kdf.derive(settings.secret_key.encode())
    log.debug("Encryption key derived")
    return key


# ── Core encrypt / decrypt ────────────────────────────────────────────────────

def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string; returns base64-encoded nonce+ciphertext."""
    return _encrypt_bytes(plaintext.encode())


def decrypt(token: str) -> str:
    """Decrypt a base64-encoded token; returns the original UTF-8 string."""
    return _decrypt_bytes(token).decode()


def _encrypt_bytes(data: bytes) -> str:
    """Encrypt raw bytes; returns base64-encoded nonce+ciphertext string."""
    aesgcm = AESGCM(_derive_key())
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, data, None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt_bytes(token: str) -> bytes:
    """Decrypt a base64-encoded token; returns raw bytes."""
    aesgcm = AESGCM(_derive_key())
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return aesgcm.decrypt(nonce, ct, None)


# ── SSH key file helpers ──────────────────────────────────────────────────────

def save_encrypted_key(device_id: int, pem: str, keys_dir: str) -> str:
    """
    Encrypt a PEM private key and write it to keys_dir.

    The file on disk is the base64-encoded AES-256-GCM ciphertext — never
    the raw PEM.  Returns the filename (not the full path).
    """
    os.makedirs(keys_dir, exist_ok=True)
    filename = f"device_{device_id}.enc"
    path = os.path.join(keys_dir, filename)
    encrypted = _encrypt_bytes(pem.encode())
    with open(path, "w") as fh:
        fh.write(encrypted)
    os.chmod(path, 0o600)
    log.info("Encrypted key saved: %s", path)
    return filename


def load_decrypted_key(filename: str, keys_dir: str) -> str:
    """
    Read an encrypted key file and return the decrypted PEM string.
    """
    path = os.path.join(keys_dir, filename)
    with open(path) as fh:
        token = fh.read().strip()
    return _decrypt_bytes(token).decode()


def delete_key_file(filename: str, keys_dir: str) -> None:
    """Remove a key file from disk, ignoring missing-file errors."""
    path = os.path.join(keys_dir, filename)
    try:
        os.remove(path)
        log.info("Deleted key file: %s", path)
    except FileNotFoundError:
        pass


# ── Key pair generation ───────────────────────────────────────────────────────

def generate_key_pair() -> tuple[str, str]:
    """
    Generate a fresh 4096-bit RSA key pair.

    Returns:
        (private_key_pem, public_key_openssh)  both as plain strings.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_openssh = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()

    return private_pem, public_openssh

