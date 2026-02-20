import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    secret_key: str = os.getenv("SECRET_KEY", "changeme-please-set-in-env")
    admin_user: str = os.getenv("ADMIN_USER", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "changeme")
    token_ttl_hours: int = int(os.getenv("TOKEN_TTL_HOURS", "8"))
    data_dir: str = os.getenv("DATA_DIR", "/data")
    db_path: str = ""
    keys_dir: str = ""

    def model_post_init(self, __context):
        if not self.db_path:
            self.db_path = os.path.join(self.data_dir, "cloudshell.db")
        if not self.keys_dir:
            self.keys_dir = os.path.join(self.data_dir, "keys")

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
