"""Import jobs from the 3.0 Online Sales Tracker's DATA table (Command Center sheet).

Read-only against the workbook. Jobs are keyed by Job Code (column A) — rows whose
code already exists in the database are skipped, so re-running after a tracker
update only picks up new rows.

Usage (from backend/):
    python -m scripts.import_tracker "<path to .xlsm>" [--dry-run]
"""

import re
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from app.database import SessionLocal
from app.models import Account, AccountType, Community, Job, JobStatus, JobType, RoomSelection

SHEET = "Command Center"
TABLE_NAME = "DATA"
BLANKS = {None, 0, "0", "", "#N/A", "N/A", "NA", "TBD", "?"}

DEFAULT_SALES_CONTACT = ("Brian Scobey", "850-890-0482", "Brian.Scobey@TownsendBuildingSupply.com")


def clean(value):
    if isinstance(value, str):
        value = value.strip()
    return None if value in BLANKS else value


def as_date(value) -> date | None:
    value = clean(value)
    return value.date() if isinstance(value, datetime) else None


def money_str(value) -> str | None:
    value = clean(value)
    if isinstance(value, (int, float)):
        return f"${value:,.2f}"
    return None


def derive_status(row: dict) -> JobStatus:
    """Current workflow stage from the tracker's milestone dates."""
    if as_date(row.get("Full Punch Date")):
        return JobStatus.closed
    if as_date(row.get("Actual Install Date")):
        return JobStatus.quality
    if as_date(row.get("Cabinet Receipt Date")):
        return JobStatus.install
    if as_date(row.get("Cabinet Order Date")) or clean(row.get("Cabinet PO#")):
        return JobStatus.ordered
    if as_date(row.get("Actual Measure Date")) or as_date(row.get("Req Measure Date")):
        return JobStatus.field_measure
    return JobStatus.quote


def load_rows(path: Path) -> list[dict]:
    # Not read_only: we need ws.tables to honor the DATA table's exact range —
    # cells below the table are dashboard UI artifacts, not jobs.
    wb = load_workbook(path, data_only=True)
    ws = wb[SHEET]
    ref = ws.tables[TABLE_NAME].ref  # e.g. "A3:CQ502"
    m = re.match(r"[A-Z]+(\d+):([A-Z]+)(\d+)", ref)
    header_row, max_row = int(m.group(1)), int(m.group(3))

    rows = ws.iter_rows(min_row=header_row, max_row=max_row, max_col=95, values_only=True)
    headers = [
        h.replace("\n", " ").strip() if isinstance(h, str) else h for h in next(rows)
    ]
    out = []
    for values in rows:
        row = dict(zip(headers, values))
        if clean(row.get("Job Code")):
            out.append(row)
    wb.close()
    return out


def get_or_create_account(db, cache: dict, name: str, acc_type: AccountType) -> Account:
    if name in cache:
        return cache[name]
    account = db.query(Account).filter(Account.name == name).first()
    if account is None:
        account = Account(name=name, type=acc_type)
        db.add(account)
        db.flush()
    cache[name] = account
    return account


def get_or_create_community(db, cache: dict, account: Account, name: str, market: str | None) -> Community:
    key = (account.id, name)
    if key in cache:
        return cache[key]
    community = (
        db.query(Community)
        .filter(Community.account_id == account.id, Community.name == name)
        .first()
    )
    if community is None:
        community = Community(account_id=account.id, name=name, market=market)
        db.add(community)
        db.flush()
    cache[key] = community
    return community


def import_row(db, row: dict, caches: dict) -> str:
    job_code = str(clean(row["Job Code"])).strip()
    if db.query(Job).filter(Job.job_code == job_code).first():
        return "skipped"

    builder = clean(row.get("Full Builder")) or clean(row.get("Builder"))
    community_name = clean(row.get("Community"))
    city = clean(row.get("City"))
    state = clean(row.get("State"))
    market = ", ".join(str(p) for p in (city, state) if p) or None

    if builder:
        account = get_or_create_account(db, caches["accounts"], str(builder), AccountType.builder)
        community = (
            get_or_create_community(db, caches["communities"], account, str(community_name), market)
            if community_name
            else None
        )
        job_type = JobType.tract
    else:
        # Retail/local rows carry the customer name in the Community column.
        account_name = str(community_name or job_code)
        account = get_or_create_account(db, caches["accounts"], account_name, AccountType.retail)
        community = None
        job_type = JobType.custom

    lot = clean(row.get("Lot #"))
    address = clean(row.get("Address"))
    if not address:
        address = f"{community_name or account.name}" + (f" Lot {lot}" if lot else "")
    if market:
        address = f"{address}, {market}"

    note_bits = []
    for label, key in [
        ("Plan", "House Plan"),
        ("Phase", "Phase"),
        ("Installer", "Installer"),
        ("Cabinet PO#", "Cabinet PO#"),
        ("Salesperson", "Salesperson"),
    ]:
        if clean(row.get(key)):
            note_bits.append(f"{label}: {clean(row[key])}")
    if money_str(row.get("Actual PO Amount")):
        note_bits.append(f"PO Amount: {money_str(row['Actual PO Amount'])}")
    for label, key in [
        ("Measured", "Actual Measure Date"),
        ("Cabinets received", "Cabinet Receipt Date"),
        ("Punch", "Full Punch Date"),
    ]:
        if as_date(row.get(key)):
            note_bits.append(f"{label}: {as_date(row[key]).isoformat()}")
    note_bits.append("Imported from 3.0 Online Sales Tracker")

    salesperson = clean(row.get("Salesperson"))
    super_name = clean(row.get("Super"))
    install = as_date(row.get("Actual Install Date")) or as_date(row.get("Requested Install Date"))

    job = Job(
        job_code=job_code,
        account_id=account.id,
        community_id=community.id if community else None,
        lot_number=str(lot) if lot is not None else None,
        address=str(address)[:500],
        job_type=job_type,
        status=derive_status(row),
        install_date=install,
        warranty_start_date=install,
        sales_contact_name=str(salesperson) if salesperson else DEFAULT_SALES_CONTACT[0],
        sales_contact_phone=None if salesperson else DEFAULT_SALES_CONTACT[1],
        sales_contact_email=None if salesperson else DEFAULT_SALES_CONTACT[2],
        field_contact_name=str(super_name) if super_name else "TBD",
        field_contact_phone=str(clean(row.get("Super Phone")) or "") or None,
        notes=" | ".join(note_bits),
    )
    db.add(job)
    db.flush()

    brand = clean(row.get("Cabinet Brand"))
    if brand:
        db.add(
            RoomSelection(
                job_id=job.id,
                room="Whole House",
                cabinet_brand=str(brand),
                notes="From tracker",
            )
        )
    return "imported"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv
    if not args:
        print('Usage: python -m scripts.import_tracker "<path to .xlsm>" [--dry-run]')
        sys.exit(1)

    path = Path(args[0])
    rows = load_rows(path)
    print(f"{len(rows)} rows with job codes in {path.name}")

    counts = {"imported": 0, "skipped": 0, "failed": 0}
    caches = {"accounts": {}, "communities": {}}
    with SessionLocal() as db:
        for row in rows:
            try:
                counts[import_row(db, row, caches)] += 1
            except Exception as exc:
                counts["failed"] += 1
                print(f"! {clean(row.get('Job Code'))}: {exc}")
        if dry_run:
            db.rollback()
            print("(dry run — rolled back)")
        else:
            db.commit()
    print(counts)


if __name__ == "__main__":
    main()
