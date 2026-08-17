"""Cloudflare R2 (S3-compatible) bridge for the OneDrive feeds.

The cloud app can't see OneDrive, so an on-prem uploader pushes the tracker /
Vendor Suite / Century / New Orders files to R2 (`upload_feeds`), and the cloud
app pulls the newest of each into its local feed dirs before every sync
(`hydrate_feeds`) — after which the existing `feeds.py` / `sync_tracker` code
reads them as plain files, unchanged.

boto3 is imported lazily so this module (and the app) load fine without it and
without R2 configured; it's only needed when R2 is actually enabled.
"""

import hashlib
import logging
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger("uvicorn.error")

# (Settings attr for the local dir, R2 key prefix, glob, how many newest to keep).
# Patterns match what feeds.py / sync_tracker already glob for.
FEED_SOURCES = [
    ("tracker_dir", "tracker/", "3.0 Online Sales Tracker *.xlsm", 5),
    ("vendorsuite_dir", "vendorsuite/", "DRH_Cabinets_Combined_*.xlsx", 5),
    ("century_dir", "century/", "Century Cabinet Jobs - SupplyPro*.xlsx", 5),
    ("pl_reports_dir", "pl-reports/", "*.xlsx", 3),  # monthly K&B P&L (manager report)
    ("po_receipt_folder", "po-receipts/", "PO Receipt List*.csv", 2),  # DOMO receipts pull
]
NEW_ORDERS_PREFIX = "new-orders/"  # single fixed file (New Orders Status.xlsx)


def _client(s: Settings):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=s.r2_endpoint,
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _list(client, bucket: str, prefix: str):
    """Every object under prefix as (key, size, last_modified), newest first."""
    out, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = client.list_objects_v2(**kw)
        for o in resp.get("Contents", []):
            if not o["Key"].endswith("/"):
                out.append((o["Key"], o["Size"], o["LastModified"]))
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def hydrate_feeds(settings: Settings | None = None) -> dict:
    """Cloud side: download the newest matching objects from R2 into the local
    feed dirs. Skips files already present with the same size. No-op when R2 off."""
    s = settings or get_settings()
    if not s.r2_enabled:
        return {"skipped": "r2 disabled"}
    client = _client(s)
    result: dict[str, int] = {}
    for attr, prefix, _pattern, keep in FEED_SOURCES:
        dest = Path(getattr(s, attr))
        dest.mkdir(parents=True, exist_ok=True)
        got = 0
        for key, size, _lm in _list(client, s.r2_bucket, prefix)[:keep]:
            local = dest / Path(key).name
            if local.exists() and local.stat().st_size == size:
                continue
            client.download_file(s.r2_bucket, key, str(local))
            got += 1
        result[prefix] = got
    # Single New Orders file
    no_path = Path(s.new_orders_file)
    no_path.parent.mkdir(parents=True, exist_ok=True)
    newest = _list(client, s.r2_bucket, NEW_ORDERS_PREFIX)[:1]
    result[NEW_ORDERS_PREFIX] = 0
    if newest:
        key, size, _lm = newest[0]
        if not (no_path.exists() and no_path.stat().st_size == size):
            client.download_file(s.r2_bucket, key, str(no_path))
            result[NEW_ORDERS_PREFIX] = 1
    return result


def upload_feeds(settings: Settings | None = None) -> dict:
    """On-prem side: push the newest matching files from the OneDrive feed dirs up
    to R2. Skips objects already present with the same size."""
    s = settings or get_settings()
    if not s.r2_enabled:
        raise RuntimeError("R2 not configured — set R2_ENDPOINT / R2_BUCKET / keys.")
    client = _client(s)
    result: dict[str, int] = {}

    def _push(path: str, prefix: str, pattern: str | None, keep: int) -> None:
        p = Path(path)
        if pattern is None:  # single file
            files = [p] if p.is_file() else []
        else:
            files = sorted(
                (f for f in p.glob(pattern) if not f.name.startswith("~")),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )[:keep]
        pushed = 0
        for f in files:
            key = prefix + f.name
            try:
                head = client.head_object(Bucket=s.r2_bucket, Key=key)
                if head["ContentLength"] == f.stat().st_size:
                    continue  # already up there, unchanged
            except Exception:  # noqa: BLE001 - not present → upload
                pass
            client.upload_file(str(f), s.r2_bucket, key)
            pushed += 1
        result[prefix] = pushed

    for attr, prefix, pattern, keep in FEED_SOURCES:
        _push(getattr(s, attr), prefix, pattern, keep)
    _push(s.new_orders_file, NEW_ORDERS_PREFIX, None, 1)
    return result


# --------------------------------------------------------------------------
# Job documents (PDFs/photos attached by path) — same R2 bridge.
# The key is derived from the stored file_path, so the uploader and the serving
# endpoint agree without adding a column to the table.
# --------------------------------------------------------------------------
DOC_PREFIX = "doc-files/"


def document_key(file_path: str) -> str:
    h = hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:16]
    return f"{DOC_PREFIX}{h}{Path(file_path).suffix.lower()}"


def object_exists(key: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    if not s.r2_enabled:
        return False
    try:
        _client(s).head_object(Bucket=s.r2_bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def stream_document(key: str, settings: Settings | None = None):
    """boto3 get_object response for a document key (has Body/ContentType), or None."""
    s = settings or get_settings()
    if not s.r2_enabled:
        return None
    try:
        return _client(s).get_object(Bucket=s.r2_bucket, Key=key)
    except Exception:  # noqa: BLE001 - missing key / auth issue → treat as not found
        return None


def upload_documents(db, settings: Settings | None = None) -> dict:
    """Push every JobDocument's local file up to R2 under document_key(path).
    Skips files already present with the same size; reports any missing locally."""
    s = settings or get_settings()
    if not s.r2_enabled:
        raise RuntimeError("R2 not configured — set R2_ENDPOINT / R2_BUCKET / keys.")
    from app.models import JobDocument  # local import to avoid a cycle at module load

    client = _client(s)
    pushed = skipped = missing = 0
    for doc in db.query(JobDocument).all():
        p = Path(doc.file_path)
        if not p.is_file():
            missing += 1
            continue
        key = document_key(doc.file_path)
        try:
            head = client.head_object(Bucket=s.r2_bucket, Key=key)
            if head["ContentLength"] == p.stat().st_size:
                skipped += 1
                continue
        except Exception:  # noqa: BLE001 - not present → upload
            pass
        client.upload_file(str(p), s.r2_bucket, key)
        pushed += 1
    return {"uploaded": pushed, "skipped": skipped, "missing_local": missing}
