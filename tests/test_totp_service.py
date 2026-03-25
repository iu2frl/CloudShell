"""
tests/test_totp_service.py — Unit tests for TOTP service.
"""
import hashlib

import pytest

from backend.services.totp import TOTPService


class TestTOTPService:
    """Test TOTP service methods."""

    def test_generate_secret(self):
        """Generated secrets should be base32 strings."""
        secret = TOTPService.generate_secret()
        assert isinstance(secret, str)
        assert len(secret) == 32
        assert secret.isupper()

    def test_generate_multiple_secrets_are_different(self):
        """Each generated secret should be unique."""
        secret1 = TOTPService.generate_secret()
        secret2 = TOTPService.generate_secret()
        assert secret1 != secret2

    def test_get_provisioning_uri(self):
        """Provisioning URI should contain otpauth scheme."""
        secret = TOTPService.generate_secret()
        uri = TOTPService.get_provisioning_uri(secret, "testuser", "TestApp")
        assert uri.startswith("otpauth://totp/")
        assert "testuser" in uri
        assert "TestApp" in uri
        assert secret in uri

    def test_generate_qr_code(self):
        """QR code should be base64-encoded PNG data URL."""
        secret = TOTPService.generate_secret()
        uri = TOTPService.get_provisioning_uri(secret, "testuser")
        qr_code = TOTPService.generate_qr_code(uri)
        assert qr_code.startswith("data:image/png;base64,")
        assert len(qr_code) > 100  # QR code should have reasonable size

    def test_verify_token_valid(self):
        """Should verify a valid TOTP token."""
        import pyotp
        secret = TOTPService.generate_secret()
        totp = pyotp.TOTP(secret)
        token = totp.now()
        assert TOTPService.verify_token(secret, token) is True

    def test_verify_token_invalid_length(self):
        """Should reject tokens that aren't 6 digits."""
        secret = TOTPService.generate_secret()
        assert TOTPService.verify_token(secret, "12345") is False
        assert TOTPService.verify_token(secret, "1234567") is False

    def test_verify_token_non_numeric(self):
        """Should reject non-numeric tokens."""
        secret = TOTPService.generate_secret()
        assert TOTPService.verify_token(secret, "abcdef") is False

    def test_verify_token_wrong_secret(self):
        """Should reject tokens with wrong secret."""
        import pyotp
        secret1 = TOTPService.generate_secret()
        secret2 = TOTPService.generate_secret()
        totp = pyotp.TOTP(secret1)
        token = totp.now()
        assert TOTPService.verify_token(secret2, token) is False

    def test_verify_token_edge_cases(self):
        """Verify edge cases like empty, invalid length, and non-numeric tokens."""
        secret = TOTPService.generate_secret()

        assert TOTPService.verify_token(secret, "") is False
        assert TOTPService.verify_token(secret, "12345") is False   # Too short
        assert TOTPService.verify_token(secret, "1234567") is False # Too long
        assert TOTPService.verify_token(secret, "abcdef") is False  # Letters

    def test_verify_token_exceptions(self):
        """Verify that exceptions (e.g. from bad secrets) are handled gracefully."""
        # A malformed secret that pyotp might crash on
        assert TOTPService.verify_token("NOT_BASE32_#", "123456") is False

    def test_verify_token_constant_time(self):
        """Verify timing is approximately constant regardless of format validation.

        This test verifies that format-invalid tokens (wrong length, non-numeric)
        don't early-return, but instead use a dummy token to maintain constant
        execution time and prevent timing attacks.

        The test measures execution time for:
        - Format-valid but cryptographically invalid tokens
        - Format-invalid tokens

        Both should have similar execution time since both paths call pyotp.verify().
        """
        import time
        
        secret = TOTPService.generate_secret()
        iterations = 100

        # Measure time for format-valid but crypto-invalid token
        start_valid_format = time.perf_counter()
        for _ in range(iterations):
            # "000000" is format-valid but cryptographically invalid (wrong secret)
            TOTPService.verify_token(secret, "000000")
        elapsed_valid_format = time.perf_counter() - start_valid_format

        # Measure time for format-invalid token
        start_invalid_format = time.perf_counter()
        for _ in range(iterations):
            # "abcdef" is format-invalid (non-numeric)
            TOTPService.verify_token(secret, "abcdef")
        elapsed_invalid_format = time.perf_counter() - start_invalid_format

        # Both should take similar time (within 50% margin to account for variance)
        # If format-invalid early-returns, it would be much faster
        min_time = min(elapsed_valid_format, elapsed_invalid_format)
        max_time = max(elapsed_valid_format, elapsed_invalid_format)
        
        # Ratio should be close to 1.0; allow 50% variance for system noise
        ratio = max_time / min_time if min_time > 0 else 1.0
        assert ratio < 1.5, (
            f"Timing discrepancy suggests early-return on format validation. "
            f"valid_format={elapsed_valid_format:.4f}s, "
            f"invalid_format={elapsed_invalid_format:.4f}s, "
            f"ratio={ratio:.2f}"
        )

    def test_generate_backup_codes(self):
        """Should generate requested number of backup codes."""
        codes = TOTPService.generate_backup_codes(10)
        assert len(codes) == 10
        # Each code should be in format XXXX-XXXX
        for code in codes:
            assert len(code) == 9
            assert code[4] == "-"
            assert code[:4].isalnum()
            assert code[5:].isalnum()

    def test_generate_backup_codes_default_count(self):
        """Should generate 10 codes by default."""
        codes = TOTPService.generate_backup_codes()
        assert len(codes) == 10

    def test_backup_codes_are_unique(self):
        """Generated backup codes should be unique."""
        codes = TOTPService.generate_backup_codes(20)
        assert len(codes) == len(set(codes))

    def test_codes_to_json(self):
        """Should serialize codes to JSON."""
        codes = ["AAAA-BBBB", "CCCC-DDDD"]
        json_str = TOTPService.codes_to_json(codes)
        assert isinstance(json_str, str)
        assert "AAAA-BBBB" in json_str
        assert "CCCC-DDDD" in json_str

    def test_codes_to_json_hashed(self):
        """Should serialize hashed codes to JSON when requested."""
        codes = ["AAAA-BBBB", "CCCC-DDDD"]
        json_str = TOTPService.codes_to_json(codes, hashed=True)
        assert isinstance(json_str, str)
        # Raw codes must not appear in hashed storage
        assert "AAAA-BBBB" not in json_str
        assert "CCCC-DDDD" not in json_str
        recovered = TOTPService.codes_from_json(json_str)
        assert len(recovered) == 2
        assert all(isinstance(x, str) for x in recovered)
        assert all(x.startswith("$2") for x in recovered)  # bcrypt

    def test_codes_from_json(self):
        """Should deserialize codes from JSON."""
        original = ["AAAA-BBBB", "CCCC-DDDD"]
        json_str = TOTPService.codes_to_json(original)
        recovered = TOTPService.codes_from_json(json_str)
        assert recovered == original

    def test_codes_from_json_invalid(self):
        """Should return empty list for invalid JSON."""
        assert TOTPService.codes_from_json(None) == []
        assert TOTPService.codes_from_json("") == []
        assert TOTPService.codes_from_json("{invalid json}") == []

    def test_codes_roundtrip(self):
        """Codes should survive JSON round-trip."""
        codes = TOTPService.generate_backup_codes(5)
        json_str = TOTPService.codes_to_json(codes)
        recovered = TOTPService.codes_from_json(json_str)
        assert recovered == codes

    def test_verify_and_consume_backup_code_success(self):
        """Should accept a valid backup code and remove it from storage."""
        codes = ["AAAA-BBBB", "CCCC-DDDD"]
        stored = TOTPService.codes_to_json(codes, hashed=True)
        ok, updated = TOTPService.verify_and_consume_backup_code(stored, "AAAA-BBBB")
        assert ok is True
        remaining = TOTPService.codes_from_json(updated)
        assert len(remaining) == 1

        # Second use of the same code must fail
        ok2, updated2 = TOTPService.verify_and_consume_backup_code(updated, "AAAA-BBBB")
        assert ok2 is False
        assert TOTPService.codes_from_json(updated2) == remaining

    def test_verify_and_consume_backup_code_failure(self):
        """Should reject invalid backup codes without changing stored hashes."""
        codes = ["AAAA-BBBB", "CCCC-DDDD"]
        stored = TOTPService.codes_to_json(codes, hashed=True)
        ok, updated = TOTPService.verify_and_consume_backup_code(stored, "EEEE-FFFF")
        assert ok is False
        assert TOTPService.codes_from_json(updated) == TOTPService.codes_from_json(stored)

    def test_verify_and_consume_backup_code_rejects_legacy_sha256(self):
        """Legacy SHA256 backup-code hashes should be rejected."""
        digest = hashlib.sha256("AAAA-BBBB".encode("utf-8")).hexdigest()
        stored = TOTPService.codes_to_json([digest], hashed=False)

        with pytest.raises(ValueError, match="deprecated"):
            TOTPService.verify_and_consume_backup_code(stored, "AAAA-BBBB")
