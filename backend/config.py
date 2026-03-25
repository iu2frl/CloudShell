import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET_KEY = "changeme-please-set-in-env"
DEVELOPMENT_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    admin_user: str = os.getenv("ADMIN_USER", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "changeme")
    token_ttl_hours: int = int(os.getenv("TOKEN_TTL_HOURS", "8"))
    audit_retention_days: int = int(os.getenv("AUDIT_RETENTION_DAYS", "7"))
    data_dir: str = os.getenv("DATA_DIR", "/data")
    trusted_proxies: str = os.getenv("TRUSTED_PROXIES", "")
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

    def model_post_init(self, __context) -> None:
        self._validate_secret_key()
        if not self.db_path:
            self.db_path = os.path.join(self.data_dir, "cloudshell.db")
        if not self.keys_dir:
            self.keys_dir = os.path.join(self.data_dir, "keys")


@lru_cache
def get_settings() -> Settings:
    return Settings()
