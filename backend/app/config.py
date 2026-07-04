from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """App configuration. Everything secret comes from env vars / .env (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Local no-Docker fallback (anchored to backend/ regardless of cwd); Postgres in docker/prod.
    database_url: str = f"sqlite:///{(_BACKEND_DIR / 'dev.db').as_posix()}"
    secret_key: str = "dev-only-insecure-key-set-SECRET_KEY-in-env-for-real-use"
    access_token_expire_minutes: int = 720
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
