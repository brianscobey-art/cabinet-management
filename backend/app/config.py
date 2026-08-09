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

    # Dealer identity + default ship-to for supplier order forms (override in .env —
    # if Everluxe still has the account under the old Townsend name, set it there).
    dealer_name: str = "Carter Lumber Dothan"
    dealer_contact: str = "Brian Scobey"
    dealer_phone: str = "850-890-0482"
    dealer_email: str = "Brian.Scobey@CarterLumber.com"
    ship_to_name: str = "Carter Lumber Dothan"
    ship_to_address: str = "868 Murray Rd"
    ship_to_city_st_zip: str = "Dothan, AL 36303"

    # Daily feed sync — OneDrive folders the scheduled cloud reports write into.
    vendorsuite_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Shared File"
        r"\AI Shared Folder\Vendor Suite\VS Combined PO and Schedules"
    )
    century_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com"
        r"\Townsend Kitchen and Bath - Master Plans & Pricing\Downloads\SupplyPro\Century"
    )
    feed_sync_hour: int = 7  # daily local-time hour; cloud reports land ~3:45 and ~6:00
    feed_sync_enabled: bool = True
    # Folder holding the 3.0 Online Sales Tracker .xlsm versions; the newest readable
    # one is the source of truth for job status (CONST LVL) + install dates.
    tracker_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com"
        r"\Townsend Kitchen and Bath - Master Plans & Pricing\Trackers"
        r"\3.0 Online Sales Tracker 010726 Backup"
    )
    domo_export_dir: str = r"C:\Users\Brian SE6\Downloads\domo-kb-tool"  # Domo cost JSON exports land here
    domo_instance: str = "carterlumber.domo.com"
    domo_dataset_id: str = "c9b70636-b093-4bcd-90e4-8f4b99e12df5"  # Sales Details PDP dataset
    domo_access_token: str = ""  # DOMO_ACCESS_TOKEN in .env enables live server-side pulls
    new_orders_file: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Shared File"
        r"\Sold Jobs\New Orders\New Orders Status.xlsx"
    )

    # Autobot — the service tech's home base (868 Murray Rd, Dothan) and workday,
    # minutes since midnight. Override in .env if the shop or hours change.
    autobot_depot_lat: float = 31.2571037
    autobot_depot_lon: float = -85.4034831
    autobot_day_start_min: int = 7 * 60      # leave the shop at 7:00 AM
    autobot_day_end_min: int = 17 * 60       # back at the shop by 5:00 PM
    autobot_sync_minutes: int = 10           # auto-spawn visits from job statuses; 0 = off
    # Google Maps Platform key (Geocoding API). Set it and every address lookup
    # uses Google; empty = OpenStreetMap/Nominatim fallback. Free tier ~10k/mo.
    google_maps_api_key: str = ""

    # Cloudflare R2 (S3-compatible) object storage — the bridge that lets the
    # cloud app read the tracker/VS/Century feeds. The on-prem uploader pushes
    # OneDrive files here; the cloud app pulls the newest into its feed dirs.
    # All four empty = R2 disabled (local dev reads OneDrive directly).
    r2_endpoint: str = ""        # https://<accountid>.r2.cloudflarestorage.com
    r2_bucket: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""

    @property
    def r2_enabled(self) -> bool:
        return bool(self.r2_endpoint and self.r2_bucket
                    and self.r2_access_key_id and self.r2_secret_access_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
