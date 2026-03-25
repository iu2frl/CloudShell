"""
services/totp.py — Two-factor authentication using TOTP (RFC 6238).

Provides utilities for:
  - Generating TOTP secrets
  - Creating provisioning URIs for QR codes
  - Generating QR codes as base64 PNG
  - Verifying TOTP tokens
  - Generating and managing backup codes
"""
import json
import secrets
import logging
import hmac
import hashlib
from typing import Optional

import pyotp
import qrcode
from io import BytesIO
import base64

log = logging.getLogger(__name__)


class TOTPService:
    """Service for managing TOTP-based two-factor authentication."""

    @staticmethod
    def generate_secret() -> str:
        """
        Generate a new random TOTP secret (base32-encoded).

        Returns:
            Base32-encoded secret suitable for TOTP
        """
        return pyotp.random_base32()

    @staticmethod
    def get_provisioning_uri(
        secret: str, username: str, issuer: str = "CloudShell"
    ) -> str:
        """
        Generate the provisioning URI for QR code generation.

        This URI is compatible with Google Authenticator and other
        authenticator apps (RFC 4226/6238).

        Args:
            secret: Base32-encoded TOTP secret
            username: User's username (displayed in authenticator)
            issuer: App name (shown in authenticator app)

        Returns:
            otpauth:// URI string
        """
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name=issuer)

    @staticmethod
    def generate_qr_code(provisioning_uri: str) -> str:
        """
        Generate QR code as base64 PNG.

        The resulting string can be used directly in img src:
        <img src="data:image/png;base64,..." />

        Args:
            provisioning_uri: otpauth:// URI from get_provisioning_uri()

        Returns:
            Data URL string (data:image/png;base64,...)
        """
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffer = BytesIO()
        img.save(buffer, "PNG")
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_base64}"

    @staticmethod
    def verify_token(secret: str, token: str, window: int = 1) -> bool:
        """
        Verify a TOTP token.

        Allows a time window tolerance to account for clock drift between
        server and client. Default window=1 means ±30 seconds (±1 time step).

        Args:
            secret: Base32-encoded TOTP secret
            token: 6-digit code from authenticator app
            window: Allow ±N time windows (default 1 = ±30 seconds)

        Returns:
            True if token is valid and within time window
        """
        if not token or len(token) != 6 or not token.isdigit():
            return False

        totp = pyotp.TOTP(secret)
        try:
            return totp.verify(token, valid_window=window)
        except (ValueError, TypeError):  # pylint: disable=broad-except
            log.debug("TOTP verification failed for token")
            return False

    @staticmethod
    def generate_backup_codes(count: int = 10) -> list[str]:
        """
        Generate backup codes for account recovery.

        Each code is 8 random hex characters (32 bits). Users should save
        these codes in a safe place. Each code can be used once.

        Args:
            count: Number of codes to generate (default 10)

        Returns:
            List of backup codes in format: XXXXXXXX-XXXX-XXXX
        """
        codes = []
        for _ in range(count):
            # Generate 8 hex chars, format as XXXXXXXX-XXXX-XXXX for readability
            hex_code = secrets.token_hex(4).upper()
            code = f"{hex_code[:4]}-{hex_code[4:8]}"
            codes.append(code)
        return codes

    @staticmethod
    def hash_backup_code(code: str) -> str:
        """Hash a single backup code for storage.

        Notes:
            - We purposely use a one-way hash so a DB read doesn't reveal usable
              backup codes.
            - This is an online-checked secret (like a password). A slow KDF
              would be stronger, but sha256 is a pragmatic baseline with no new
              dependencies.

        Args:
            code: Backup code in the format produced by generate_backup_codes()

        Returns:
            Hex-encoded sha256 digest.
        """
        normalized = (code or "").strip().upper()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return digest

    @staticmethod
    def hash_backup_codes(codes: list[str]) -> list[str]:
        """Hash a list of backup codes."""
        return [TOTPService.hash_backup_code(c) for c in codes]

    @staticmethod
    def codes_to_json(codes: list[str], *, hashed: bool = False) -> str:
        """Serialize backup codes to JSON for storage.

        Args:
            codes: List of backup code strings.
            hashed: When True, store hashes instead of raw codes.

        Returns:
            JSON-encoded string.
        """
        payload = TOTPService.hash_backup_codes(codes) if hashed else codes
        return json.dumps(payload)

    @staticmethod
    def verify_and_consume_backup_code(
        stored_json: Optional[str],
        provided_code: str,
    ) -> tuple[bool, str]:
        """Verify a provided backup code against stored hashes and consume it.

        Args:
            stored_json: JSON string containing hashed backup codes.
            provided_code: User-supplied backup code.

        Returns:
            (is_valid, updated_json). If is_valid is True, updated_json will
            have the matched code removed.
        """
        stored = TOTPService.codes_from_json(stored_json)
        if not stored:
            return False, TOTPService.codes_to_json([], hashed=False)

        provided_hash = TOTPService.hash_backup_code(provided_code)

        # Constant-time compare each entry, keep all non-matching entries.
        matched = False
        remaining: list[str] = []
        for entry in stored:
            if hmac.compare_digest(entry, provided_hash) and not matched:
                matched = True
                continue
            remaining.append(entry)

        return matched, json.dumps(remaining)

    @staticmethod
    def codes_from_json(json_str: Optional[str]) -> list[str]:
        """
        Deserialize backup codes from JSON storage.

        Args:
            json_str: JSON-encoded string (or None)

        Returns:
            List of backup codes, or empty list if json_str is None/invalid
        """
        if not json_str:
            return []
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return []
