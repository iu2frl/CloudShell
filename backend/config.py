import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET_KEY = "changeme-please-set-in-env"
DEFAULT_ADMIN_PASSWORD = "changeme"
DEVELOPMENT_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    admin_user: str = os.getenv("ADMIN_USER", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    token_ttl_hours: int = int(os.getenv("TOKEN_TTL_HOURS", "8"))
    audit_retention_days: int = int(os.getenv("AUDIT_RETENTION_DAYS", "7"))
    data_dir: str = os.getenv("DATA_DIR", "/data")
    trusted_proxies: str = os.getenv("TRUSTED_PROXIES", "")
    oidc_enabled: bool = os.getenv("OIDC_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    oidc_issuer_url: str = os.getenv("OIDC_ISSUER_URL", "").strip()
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "").strip()
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "").strip()
    oidc_redirect_uri: str = os.getenv("OIDC_REDIRECT_URI", "").strip()
    oidc_scopes: str = os.getenv("OIDC_SCOPES", "openid profile email groups").strip()
    oidc_discovery_ttl_seconds: int = int(os.getenv("OIDC_DISCOVERY_TTL_SECONDS", "300"))
    oidc_post_login_redirect: str = os.getenv("OIDC_POST_LOGIN_REDIRECT", "/").strip() or "/"
    ftps_allow_insecure: bool = os.getenv("FTPS_ALLOW_INSECURE", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    db_path: str = ""
    keys_dir: str = ""

    def _is_development_environment(self) -> bool:
        """Return True when environment should allow relaxed local defaults."""
        return self.environment.strip().lower() in DEVELOPMENT_ENVIRONMENTS

    def _validate_secret_key(self) -> None:
        """Enforce non-default SECRET_KEY outside development-like environments."""
        normalized_secret = self.secret_key.strip() if self.secret_key else ""

        if not normalized_secret:
            raise ValueError("SECRET_KEY must be non-empty")

        if not self._is_development_environment() and normalized_secret == DEFAULT_SECRET_KEY:
            raise ValueError(
                "Refusing startup with insecure default SECRET_KEY in non-development environment"
            )

    def _validate_admin_password(self) -> None:
        """Enforce non-default ADMIN_PASSWORD outside development-like environments."""
        normalized_password = self.admin_password.strip() if self.admin_password else ""

        if not normalized_password:
            raise ValueError("ADMIN_PASSWORD must be non-empty")

        if not self._is_development_environment() and normalized_password == DEFAULT_ADMIN_PASSWORD:
            raise ValueError(
                "Refusing startup with insecure default ADMIN_PASSWORD in non-development environment"
            )

    def _validate_ftps_mode(self) -> None:
        """Disallow insecure FTPS mode outside development-like environments."""
        if self.ftps_allow_insecure and not self._is_development_environment():
            raise ValueError(
                "Refusing startup with FTPS_ALLOW_INSECURE enabled in non-development environment"
            )

    def _validate_oidc(self) -> None:
        """Validate OIDC settings when OIDC mode is enabled."""
        if not self.oidc_enabled:
            return

        required_fields = {
            "OIDC_ISSUER_URL": self.oidc_issuer_url,
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
            "OIDC_REDIRECT_URI": self.oidc_redirect_uri,
        }
        missing = [name for name, value in required_fields.items() if not value]
        if missing:
            raise ValueError(f"OIDC is enabled but missing required settings: {', '.join(missing)}")

        if not self.oidc_redirect_uri.startswith(("http://", "https://")):
            raise ValueError("OIDC_REDIRECT_URI must start with http:// or https://")

        if not self.oidc_issuer_url.startswith(("http://", "https://")):
            raise ValueError("OIDC_ISSUER_URL must start with http:// or https://")

        if not self._is_development_environment():
            if not self.oidc_redirect_uri.startswith("https://"):
                raise ValueError("OIDC_REDIRECT_URI must use https:// outside development")
            if not self.oidc_issuer_url.startswith("https://"):
                raise ValueError("OIDC_ISSUER_URL must use https:// outside development")

    def __init__(self, **values):
        super().__init__(**values)
        self._validate_secret_key()
        self._validate_admin_password()
        self._validate_ftps_mode()
        self._validate_oidc()
        if not self.db_path:
            self.db_path = os.path.join(self.data_dir, "cloudshell.db")
        if not self.keys_dir:
            self.keys_dir = os.path.join(self.data_dir, "keys")


@lru_cache
def get_settings() -> Settings:
    return Settings()
