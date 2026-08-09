"""On-prem uploader: push the newest tracker / Vendor Suite / Century / New Orders
files from the local OneDrive feed folders up to Cloudflare R2, so the cloud app
can read them (it can't see OneDrive directly).

Run on the PC that has OneDrive synced, on a schedule — Windows Task Scheduler,
e.g. every 30 minutes, or once each morning after the cloud reports land (~6 AM).
Needs the same R2_* env vars as the cloud service (put them in backend/.env or
the Task Scheduler action's environment). Idempotent: skips files already in R2
with the same size.

Usage (from backend/):
    python -m scripts.upload_feeds_to_r2
"""

from app.config import get_settings
from app.storage import upload_feeds


def main() -> None:
    s = get_settings()
    if not s.r2_enabled:
        print("R2 not configured. Set R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, "
              "R2_SECRET_ACCESS_KEY (see backend/.env.example).")
        raise SystemExit(1)
    print(f"Uploading feed files to R2 bucket '{s.r2_bucket}' ...")
    counts = upload_feeds(s)
    for prefix, n in counts.items():
        print(f"  {prefix}: {n} uploaded")
    print("Done.")


if __name__ == "__main__":
    main()
