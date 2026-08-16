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

    # Email invites (SendGrid). Set SENDGRID_API_KEY + a verified INVITE_FROM_EMAIL
    # to turn on "send invite" when adding a user. app_base_url is where the
    # set-password link points (the live site). Empty key = invites disabled.
    sendgrid_api_key: str = ""
    invite_from_email: str = ""
    invite_from_name: str = "Carter Kitchen and Bath"
    app_base_url: str = "https://cabinettron.com"
    invite_expire_hours: int = 168  # set-password link good for 7 days

    @property
    def email_enabled(self) -> bool:
        return bool(self.sendgrid_api_key and self.invite_from_email)

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
    feed_sync_hour: int = 7  # legacy single-hour fallback (kept for compatibility)
    # Hours (in feed_sync_tz) to run the feed sync. Comma-separated for multiple
    # runs a day. Default 5 AM + noon Central. Cloud runs on UTC, so the tz matters.
    feed_sync_hours: str = "5,12"
    feed_sync_tz: str = "America/Chicago"  # Central — FL Panhandle / Alabama
    feed_sync_enabled: bool = True

    @property
    def feed_sync_hour_list(self) -> list[int]:
        hours = [
            int(p) for p in self.feed_sync_hours.split(",")
            if p.strip().isdigit() and 0 <= int(p.strip()) <= 23
        ]
        return hours or [self.feed_sync_hour]
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

    # Order Pack (private mode inside Optimus, /ordering-platform/pack) ------
    # The four stage folders live under this root; a job folder's position in
    # the chain IS its status, so the on-prem agent scans it and reports.
    # These paths are read by the AGENT on Brian's PC, not by the cloud app.
    new_orders_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Shared File"
        r"\Sold Jobs\New Orders"
    )
    # Where stage 4 files completed jobs. The old "Sold Jobs\Builders\DR Horton"
    # tree is deprecated and must never be read or written.
    sold_files_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com"
        r"\Townsend Kitchen and Bath - Master Plans & Pricing\Sold Job Files"
        r"\National Accounts\DR Horton - All"
    )
    # Only these logins may load the page or hit its endpoints (comma-separated).
    orderpack_owner_emails: str = (
        "brian.scobey@townsendbuildingsupply.com,brian.scobey@carterlumber.com"
    )
    # Shared secret the on-prem agent authenticates with (X-Pack-Key header),
    # same approach as WALLPAPER_FEED_KEY. Override in .env on Render AND on the PC.
    orderpack_agent_key: str = "ckb-pack-9f3a71c4e08b"
    # Minutes between the agent's folder scans (0 = scan only when asked).
    orderpack_scan_minutes: int = 15
    # Auto-run stage 4 on a schedule the way Pull_scheduled.vbs does today.
    # Off for now (Brian's call 8/16/26): nothing fires unless he presses Run.
    orderpack_auto_stage4: bool = False

    @property
    def orderpack_owner_list(self) -> list[str]:
        return [e.strip().lower() for e in self.orderpack_owner_emails.split(",") if e.strip()]

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

    # Manager sales report ----------------------------------------------------
    # Folder holding the monthly K&B P&L workbooks (newest is read for NET SALES).
    pl_reports_dir: str = (
        r"C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Shared File"
        r"\Operations\P&L Reports"
    )
    # The Chipley, FL store — base point for KSR travel-mile calculations.
    chipley_lat: float = 30.7819
    chipley_lon: float = -85.5386
    ksr_houses_per_year: int = 350   # national benchmark a field person can cover
    ksr_trips_per_job: int = 3       # site visits per job (× 2 for the round trip)
    coverage_sq_miles: int = 23000
    # A long random token unlocks the public read-only manager report link
    # (no login). Empty = the public link is disabled. Set on Render to enable.
    manager_report_token: str = ""

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
