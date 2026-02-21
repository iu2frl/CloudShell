"""
tests/test_crypto_service.py — unit tests for services/crypto.py.

Tests cover:
- encrypt / decrypt round-trip produces the original string
- encrypt returns a base64 string (not the raw plaintext)
- two encryptions of the same input produce different ciphertexts (random nonce)
- decrypt rejects tampered ciphertext
- save_encrypted_key writes a file that can be read back by load_decrypted_key
- load_decrypted_key returns the original PEM
- delete_key_file removes the file from disk
- delete_key_file is a no-op when the file does not exist
- generate_key_pair returns a valid PEM private key and OpenSSH public key
- generate_key_pair returns unique pairs each call
"""
import base64
import os
import tempfile

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.services.crypto import (
    decrypt,
    delete_key_file,
    encrypt,
    generate_key_pair,
    load_decrypted_key,
    save_encrypted_key,
)


# ── encrypt / decrypt ─────────────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip():
    """Decrypting an encrypted string must return the original plaintext."""
    original = "super-secret-password-123"
    token = encrypt(original)
    assert decrypt(token) == original


def test_encrypt_returns_base64():
    """encrypt must return a base64-decodable string, not the raw plaintext."""
    plaintext = "hello world"
    token = encrypt(plaintext)
    # Should not contain the plaintext directly
    assert plaintext not in token
    # Must be base64-decodable
    decoded = base64.b64decode(token)
    assert len(decoded) > 0


def test_encrypt_produces_unique_ciphertexts():
    """Two encryptions of the same string must produce different ciphertexts (nonce randomness)."""
    plaintext = "same input every time"
    assert encrypt(plaintext) != encrypt(plaintext)


def test_decrypt_tampered_ciphertext_raises():
    """decrypt must raise an exception when the ciphertext has been tampered with."""
    token = encrypt("original data")
    # Flip a byte in the raw blob
    raw = bytearray(base64.b64decode(token))
    raw[-1] ^= 0xFF
    bad_token = base64.b64encode(bytes(raw)).decode()

    with pytest.raises(Exception):
        decrypt(bad_token)


def test_encrypt_empty_string():
    """Encrypting an empty string and decrypting must return an empty string."""
    assert decrypt(encrypt("")) == ""


def test_encrypt_unicode_string():
    """Encrypting a Unicode string and decrypting must preserve the content."""
    plaintext = "password: P@ssw0rd! \u00e9\u00e0\u00fc"
    assert decrypt(encrypt(plaintext)) == plaintext


# ── save / load / delete key file ─────────────────────────────────────────────

def test_save_and_load_key_file():
    """save_encrypted_key followed by load_decrypted_key must return the original PEM."""
    private_pem, _ = generate_key_pair()
    with tempfile.TemporaryDirectory() as keys_dir:
        filename = save_encrypted_key(device_id=42, pem=private_pem, keys_dir=keys_dir)
        loaded = load_decrypted_key(filename, keys_dir)
    assert loaded == private_pem


def test_save_key_file_is_encrypted_on_disk():
    """The file stored on disk must not contain the raw PEM text."""
    private_pem, _ = generate_key_pair()
    with tempfile.TemporaryDirectory() as keys_dir:
        filename = save_encrypted_key(device_id=1, pem=private_pem, keys_dir=keys_dir)
        path = os.path.join(keys_dir, filename)
        raw_content = open(path).read()
    # The raw PEM header must not appear in the encrypted file
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" not in raw_content


def test_save_key_file_permissions():
    """The encrypted key file must have mode 0o600."""
    private_pem, _ = generate_key_pair()
    with tempfile.TemporaryDirectory() as keys_dir:
        filename = save_encrypted_key(device_id=7, pem=private_pem, keys_dir=keys_dir)
        path = os.path.join(keys_dir, filename)
        mode = oct(os.stat(path).st_mode)[-3:]
    assert mode == "600"


def test_save_key_filename_includes_device_id():
    """The saved key filename must include the device ID for traceability."""
    private_pem, _ = generate_key_pair()
    with tempfile.TemporaryDirectory() as keys_dir:
        filename = save_encrypted_key(device_id=99, pem=private_pem, keys_dir=keys_dir)
    assert "99" in filename


def test_delete_key_file_removes_file():
    """delete_key_file must remove the file from disk."""
    private_pem, _ = generate_key_pair()
    with tempfile.TemporaryDirectory() as keys_dir:
        filename = save_encrypted_key(device_id=5, pem=private_pem, keys_dir=keys_dir)
        path = os.path.join(keys_dir, filename)
        assert os.path.exists(path)
        delete_key_file(filename, keys_dir)
        assert not os.path.exists(path)


def test_delete_key_file_missing_is_noop():
    """delete_key_file must not raise when the file does not exist."""
    with tempfile.TemporaryDirectory() as keys_dir:
        # Should not raise
        delete_key_file("nonexistent_file.enc", keys_dir)


# ── generate_key_pair ─────────────────────────────────────────────────────────

def test_generate_key_pair_returns_strings():
    """generate_key_pair must return two non-empty strings."""
    private_pem, public_openssh = generate_key_pair()
    assert isinstance(private_pem, str) and private_pem
    assert isinstance(public_openssh, str) and public_openssh


def test_generate_key_pair_private_key_is_pem():
    """The private key must be PEM-encoded (OpenSSH format)."""
    private_pem, _ = generate_key_pair()
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" in private_pem
    assert "-----END OPENSSH PRIVATE KEY-----" in private_pem


def test_generate_key_pair_public_key_is_openssh():
    """The public key must be an OpenSSH-formatted RSA key."""
    _, public_openssh = generate_key_pair()
    assert public_openssh.strip().startswith("ssh-rsa ")


def test_generate_key_pair_unique_each_call():
    """Two calls to generate_key_pair must return different key pairs."""
    pem1, pub1 = generate_key_pair()
    pem2, pub2 = generate_key_pair()
    assert pem1 != pem2
    assert pub1 != pub2
