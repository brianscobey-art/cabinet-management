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

    # Where generated order/export files land (gitignored).
    generated_dir: str = str(_BACKEND_DIR / "generated")

    # Dealer identity + default ship-to for supplier order forms (override in .env).
    dealer_name: str = "Townsend Dothan"
    dealer_contact: str = "Brian Scobey"
    dealer_phone: str = "850-890-0482"
    dealer_email: str = "Brian.Scobey@TownsendBuildingSupply.com"
    ship_to_name: str = "Townsend Dothan"
    ship_to_address: str = "868 Murray Rd"
    ship_to_city_st_zip: str = "Dothan, AL 36303"

    # Daily feed sync — OneDrive folders the scheduled cloud reports write into.
    vendorsuite_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Shared File"
        r"\AI Shared Folder\Vendor Suite\VS Combined PO and Schedules"
    )
    century_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Shared File"
        r"\AI Shared Folder\Supply Pro - Century"
    )
    feed_sync_hour: int = 7  # daily local-time hour; cloud reports land ~3:45 and ~6:00
    feed_sync_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
