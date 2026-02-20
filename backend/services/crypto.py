import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from backend.config import get_settings

_SALT = b"cloudshell-static-salt-v1"  # static salt; key rotates via SECRET_KEY


def _derive_key() -> bytes:
    """Derive a 256-bit AES key from SECRET_KEY."""
    settings = get_settings()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=260_000,
    )
    return kdf.derive(settings.secret_key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a string; returns base64-encoded nonce+ciphertext."""
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(token: str) -> str:
    """Decrypt a base64-encoded nonce+ciphertext string."""
    key = _derive_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()
