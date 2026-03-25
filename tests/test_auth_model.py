"""tests/test_auth_model.py - Unit tests for auth model helpers."""

from unittest.mock import patch

from backend.models.auth import AdminTOTPSecret


def test_admin_totp_secret_getter_falls_back_for_legacy_plaintext() -> None:
    """Getter should return raw value when versioned decrypt fails."""
    record = AdminTOTPSecret(username="admin", secret="ABCDEFGHIJKLMNOP", is_enabled=False)

    with patch("backend.models.auth.decrypt_versioned", side_effect=ValueError("bad format")):
        raw_secret = record.secret

    assert raw_secret == record._secret_encrypted


def test_admin_totp_secret_setter_encrypts_value() -> None:
    """Setter should store encrypted versioned secret at rest."""
    record = AdminTOTPSecret(username="admin", secret="ABCDEFGHIJKLMNOP", is_enabled=False)

    assert record._secret_encrypted.startswith("v1:")


def test_admin_totp_secret_getter_returns_decrypted_secret() -> None:
    """Getter should return the decrypted plaintext value in normal path."""
    original_secret = "ABCDEFGHIJKLMNOP"
    record = AdminTOTPSecret(username="admin", secret=original_secret, is_enabled=False)

    assert record.secret == original_secret
