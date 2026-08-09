"""Push job-document files (PDFs/photos attached to jobs) up to Cloudflare R2 so
the cloud app can serve them — it can't read the OneDrive paths stored in the DB.

Run on the PC where the files are accessible (OneDrive synced). It enumerates the
JobDocument rows in whatever DATABASE_URL points at and uploads each file that
exists locally, keyed by its stored path (the serving endpoint derives the same
key). Skips files already in R2 with the same size.

  - After migrating to cloud Postgres: set DATABASE_URL to the cloud database so
    it uploads exactly the documents the cloud app knows about.
  - Before migrating: run against the local dev.db to pre-seed R2.

Needs the R2_* env vars. Re-run whenever new documents get attached.

Usage (from backend/):
    python -m scripts.upload_documents_to_r2
"""

from app.config import get_settings
from app.database import SessionLocal
from app.storage import upload_documents


def main() -> None:
    s = get_settings()
    if not s.r2_enabled:
        print("R2 not configured. Set R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, "
              "R2_SECRET_ACCESS_KEY (see backend/.env.example).")
        raise SystemExit(1)
    print(f"Uploading job documents to R2 bucket '{s.r2_bucket}' ...")
    with SessionLocal() as db:
        counts = upload_documents(db, s)
    print(f"  uploaded: {counts['uploaded']}  skipped(same): {counts['skipped']}  "
          f"missing locally: {counts['missing_local']}")
    print("Done.")


if __name__ == "__main__":
    main()
