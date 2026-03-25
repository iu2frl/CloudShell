"""
tests/test_totp_service.py — Unit tests for TOTP service.
"""
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
