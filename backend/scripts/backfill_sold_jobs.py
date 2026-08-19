"""Backfill from the Sold Job Files folders:

  1. attach every document in each job's folder (skipping ones already linked)
  2. fill missing ordering numbers — PO # (builder), SO # (vendor), Carter PO #
  3. read each SO PDF's "Total" into the checklist's so_total (the Ordered page's
     SO Amount column)

Safe to re-run: only fills blanks, never overwrites a value that's already set.
Run from backend/ (set DATABASE_URL to target the cloud database):
    python -m scripts.backfill_sold_jobs [--limit N] [--dry-run]
"""

import re
import sys
from decimal import Decimal
from pathlib import Path

from app.database import SessionLocal
from app.models import Job, JobDocument, OrderingChecklist

SOLD_ROOT = Path(
    r"C:\Users\Brian SE6\OneDrive - carterlumber.com"
    r"\Townsend Kitchen and Bath - Master Plans & Pricing\Sold Job Files"
)
SO_RE = re.compile(r"\b(SO\d{3,})\b", re.I)
CARTER_PO_RE = re.compile(r"\b(7\d{8})\b")          # Carter PO/SO numbers are 75xxxxxxx
TOTAL_RE = re.compile(r"\bTotal\s*\$?([\d,]+\.\d{2})")


def classify(name: str) -> str:
    from scripts.import_sold_jobs import classify as _c

    return _c(name)


def pdf_total(path: Path) -> Decimal | None:
    """Last 'Total $x' on the SO — the order's grand total."""
    try:
        from pypdf import PdfReader

        text = "".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 — scanned/damaged PDFs just yield nothing
        return None
    hits = TOTAL_RE.findall(text)
    if not hits:
        return None
    try:
        return Decimal(hits[-1].replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def folder_for(job_code: str, index: dict) -> Path | None:
    return index.get(job_code.upper())


def build_index() -> dict:
    """job_code -> folder, from the leaf folders under Sold Job Files."""
    index = {}
    for folder in SOLD_ROOT.rglob("*"):
        if not folder.is_dir():
            continue
        m = re.match(r"([A-Z]{2,}[A-Z0-9]*-?\d{3,}(?:\.\d+)?)", folder.name.upper())
        if m:
            index.setdefault(m.group(1), folder)
    return index


def main() -> None:
    dry = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    if not SOLD_ROOT.is_dir():
        print(f"Sold Job Files not found: {SOLD_ROOT}")
        raise SystemExit(1)

    print("indexing sold job folders ...")
    index = build_index()
    print(f"  {len(index)} job folders")

    db = SessionLocal()
    stats = {"jobs": 0, "docs": 0, "po": 0, "so": 0, "carter": 0, "so_total": 0, "no_folder": 0}
    jobs = db.query(Job).filter(Job.job_code.isnot(None)).all()
    for job in jobs:
        folder = folder_for(job.job_code, index)
        if folder is None:
            stats["no_folder"] += 1
            continue
        stats["jobs"] += 1
        files = [f for f in folder.iterdir() if f.is_file() and not f.name.startswith("~")]

        # 1. documents
        have = {d.file_path for d in db.query(JobDocument).filter(JobDocument.job_id == job.id)}
        for f in files:
            if str(f) in have:
                continue
            if not dry:
                db.add(JobDocument(job_id=job.id, filename=f.name,
                                   doc_type=classify(f.name), file_path=str(f)))
            stats["docs"] += 1

        # 2/3. ordering numbers + SO total
        cl = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
        if cl is None:
            cl = OrderingChecklist(job_id=job.id)
            if not dry:
                db.add(cl)
                db.flush()

        so_file = next((f for f in files if classify(f.name) == "sales_order"), None)
        if not cl.so_number and so_file:
            m = SO_RE.search(so_file.name)
            if m:
                if not dry:
                    cl.so_number = m.group(1).upper()
                stats["so"] += 1
        if not cl.po_number and job.builder_po:
            if not dry:
                cl.po_number = job.builder_po
            stats["po"] += 1
        if not cl.carter_po_number:
            carter = job.cabinet_po or next(
                (m.group(1) for f in files if (m := CARTER_PO_RE.search(f.name))), None
            )
            if carter:
                if not dry:
                    cl.carter_po_number = carter
                stats["carter"] += 1
        if cl.so_total is None and so_file:
            total = pdf_total(so_file)
            if total is not None:
                if not dry:
                    cl.so_total = total
                stats["so_total"] += 1

        if not dry and stats["jobs"] % 25 == 0:
            db.commit()
        if limit and stats["jobs"] >= limit:
            break

    if not dry:
        db.commit()
    db.close()
    print(("DRY RUN — " if dry else "") + "done:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
