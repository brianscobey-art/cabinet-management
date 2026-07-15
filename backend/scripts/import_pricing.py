"""Import PO & pricing data for every tracker job into the structured fields.

Reads the 3.0 Online Sales Tracker DATA table and fills:
  builder_po   <- DRH PO#  (fallback: PO#/Order#)
  po_amount    <- Actual PO Amount (fallback: Tracked PO Amount / DRH PO Amount)
  cabinet_po   <- Cabinet PO#
  materials_cost, margin_amount, margin_pct  (skipping #N/A formula errors)
  po_status    <- VS PO Status

Overwrites these fields (the tracker is the pricing source of truth). Matched
by job_code. Usage (from backend/):
    python -m scripts.import_pricing "<tracker .xlsm>" [--dry-run]
"""

import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scripts.import_tracker import clean, load_rows

from app.database import SessionLocal
from app.models import Job


def money(value) -> Decimal | None:
    value = clean(value)
    if value is None or isinstance(value, str):
        return None  # '#N/A' etc.
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d != 0 else None


def po_str(value) -> str | None:
    value = clean(value)
    if value is None:
        return None
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value).strip()


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if not args:
        print('Usage: python -m scripts.import_pricing "<tracker .xlsm>" [--dry-run]')
        sys.exit(1)

    rows = load_rows(Path(args[0]))
    counts = {"updated": 0, "no_job": 0, "no_data": 0}
    with SessionLocal() as db:
        for row in rows:
            code = str(clean(row["Job Code"])).strip()
            job = db.query(Job).filter(Job.job_code == code).first()
            if job is None:
                counts["no_job"] += 1
                continue

            builder_po = po_str(row.get("DRH PO#")) or po_str(row.get("PO#  Order #"))
            po_amount = money(row.get("Actual PO Amount")) or money(row.get("Tracked PO Amount")) or money(
                row.get("DRH PO Amount")
            )
            cabinet_po = po_str(row.get("Cabinet PO#"))
            materials = money(row.get("Materials"))
            margin_amt = money(row.get("Projected Margin $"))
            margin_pct = money(row.get("Projected Margin %"))
            po_status = clean(row.get("VS PO Status"))

            if not any([builder_po, po_amount, cabinet_po, materials, margin_amt, po_status]):
                counts["no_data"] += 1
                continue

            job.builder_po = builder_po
            job.po_amount = po_amount
            job.cabinet_po = cabinet_po
            job.materials_cost = materials
            job.margin_amount = margin_amt
            # store margin % as a fraction; tracker gives 0.32 or sometimes 1.0
            job.margin_pct = margin_pct if margin_pct is not None and margin_pct <= 5 else None
            job.po_status = str(po_status).strip() if po_status else None
            counts["updated"] += 1

        if dry:
            db.rollback()
            print("(dry run — rolled back)")
        else:
            db.commit()
    print(counts)


if __name__ == "__main__":
    main()
