"""Daily feed sync — pulls the outputs of Brian's scheduled cloud reports into the app.

Two feeds, both written to OneDrive by cloud tasks each morning:
- Vendor Suite merge (~3:45 AM): DRH_Cabinets_Combined_{MMDDYY}[.Rn].xlsx —
  every open DRH cabinet PO + schedule dates across all 5 regions.
- Century SupplyPro refresh (~6:00 AM): Century Production Report-{MMDDYY}.xlsx —
  all Century cabinet jobs with status and delivery dates.

Sync is idempotent: jobs match on community + lot; existing jobs get their
feed segment in notes refreshed (marked VS:/SP:), install dates updated, and
early statuses bumped to 'ordered' when an open PO exists. Unknown lots become
new jobs, with job codes derived from coded siblings in the same community
(e.g. Links Crossing siblings DRLICR-#### -> DRLICR-0135).
"""

import os
import re
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Account, AccountType, Community, Job, JobStatus, JobType

DEFAULT_SALES_CONTACT = ("Brian Scobey", "850-890-0482", "Brian.Scobey@TownsendBuildingSupply.com")

VS_REGION_ACCOUNTS = {
    "Mont": "DR Horton Montgomery",
    "PC West": "DR Horton Panama City West",
    "PC East": "DR Horton Panama City East",
    "Pensa East": "DR Horton Pensacola East",
    "Pensa West": "DR Horton Pensacola West",
}

CENTURY_ACCOUNT = "Century PC"


def _canon_lot(lot) -> str | None:
    if lot is None:
        return None
    s = str(lot).strip().lstrip("0")
    return s or "0"


def _as_date(value) -> date | None:
    return value.date() if isinstance(value, datetime) else None


def _fmt(d: date | None) -> str:
    return f"{d.month}/{d.day}/{d:%y}" if d else ""


def latest_file(directory: Path, pattern: str) -> Path | None:
    files = [f for f in directory.glob(pattern) if not f.name.startswith("~")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def _load_wb(path: Path):
    """Open a workbook read-only; if Excel/OneDrive holds a lock, read a shadow copy.

    Returns (workbook, cleanup) — call cleanup() after wb.close().
    """
    try:
        return load_workbook(path, read_only=True, data_only=True), (lambda: None)
    except PermissionError:
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.close()
        shutil.copyfile(path, tmp.name)
        wb = load_workbook(tmp.name, read_only=True, data_only=True)
        return wb, (lambda: os.unlink(tmp.name))


def _get_or_create_account(db: Session, name: str) -> Account:
    account = db.query(Account).filter(Account.name == name).first()
    if account is None:
        account = Account(name=name, type=AccountType.builder)
        db.add(account)
        db.flush()
    return account


def _get_or_create_community(db: Session, account: Account, name: str) -> Community:
    community = (
        db.query(Community)
        .filter(Community.account_id == account.id, Community.name == name)
        .first()
    )
    if community is None:
        community = Community(account_id=account.id, name=name)
        db.add(community)
        db.flush()
    return community


def _find_job(db: Session, community: Community, lot) -> Job | None:
    want = _canon_lot(lot)
    if want is None:
        return None
    for job in db.query(Job).filter(Job.community_id == community.id).all():
        if _canon_lot(job.lot_number) == want:
            return job
    return None


def _derive_job_code(db: Session, community: Community, lot4: str) -> str | None:
    """New lots inherit the code prefix their coded siblings use (DRLICR-0135)."""
    prefixes: dict[str, int] = {}
    for (code,) in (
        db.query(Job.job_code).filter(Job.community_id == community.id, Job.job_code.isnot(None)).all()
    ):
        if "-" in code:
            prefix = code.rsplit("-", 1)[0]
            prefixes[prefix] = prefixes.get(prefix, 0) + 1
    if not prefixes:
        return None
    prefix = max(prefixes, key=lambda p: prefixes[p])
    candidate = f"{prefix}-{lot4}"
    if db.query(Job).filter(Job.job_code == candidate).first():
        return None  # collision — leave uncoded rather than mislabel
    return candidate


def _set_feed_note(job: Job, tag: str, text: str) -> None:
    """Keep exactly one 'VS:'/'SP:' segment in notes, refreshed each sync."""
    segment = f"{tag} {text}".strip()
    notes = job.notes or ""
    pattern = re.compile(rf"{tag}[^|]*")
    if pattern.search(notes):
        job.notes = pattern.sub(segment, notes).strip(" |")
    else:
        job.notes = f"{notes} | {segment}".strip(" |")


def _bump_to_ordered(job: Job) -> bool:
    if job.status in (JobStatus.quote, JobStatus.field_measure):
        job.status = JobStatus.ordered
        return True
    return False


def sync_vendorsuite(db: Session, path: Path) -> dict:
    wb, cleanup = _load_wb(path)
    tab = next((n for n in wb.sheetnames if n.startswith("DRH Cabinets Combined")), None)
    if tab is None:
        wb.close()
        cleanup()
        raise ValueError(f"No 'DRH Cabinets Combined' tab in {path.name}")
    rows = wb[tab].iter_rows(min_row=2, values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(rows)]
    idx = {h: i for i, h in enumerate(headers)}

    counts = {"created": 0, "updated": 0, "skipped": 0}
    for values in rows:
        row = {h: values[i] for h, i in idx.items() if i < len(values)}
        region = row.get("Region")
        account_name = VS_REGION_ACCOUNTS.get(str(region).strip()) if region else None
        project = row.get("Project")
        job_number = row.get("Job Number")
        if not account_name or not project or job_number is None:
            counts["skipped"] += 1
            continue

        account = _get_or_create_account(db, account_name)
        community = _get_or_create_community(db, account, str(project).strip())
        lot4 = str(job_number)[-4:]

        po_bits = []
        if row.get("PO Number"):
            amount = row.get("PO Amount")
            amount_s = f" ${amount:,.2f}" if isinstance(amount, (int, float)) else ""
            po_bits.append(f"PO# {row['PO Number']}{amount_s} ({row.get('PO Status') or '?'})")
        measure = _as_date(row.get("Cabinet Measure/Order"))
        install = _as_date(row.get("Cabinet Install"))
        punch = _as_date(row.get("Cabinet Trim/Punch"))
        for label, d in (("measure", measure), ("install", install), ("punch", punch)):
            if d:
                po_bits.append(f"{label} {_fmt(d)}")
        feed_text = ", ".join(po_bits) or "on report, no PO detail"

        job = _find_job(db, community, lot4)
        if job is None:
            plan = " ".join(str(row.get(k) or "") for k in ("Plan", "Elevation", "Swing")).strip()
            job = Job(
                job_code=_derive_job_code(db, community, lot4),
                account_id=account.id,
                community_id=community.id,
                lot_number=lot4.lstrip("0") or "0",
                address=str(row.get("Street Address") or f"{project} Lot {lot4}").title(),
                job_type=JobType.tract,
                plan=plan[:100] or None,
                status=JobStatus.ordered if row.get("PO Number") else JobStatus.quote,
                measure_date=measure,
                install_date=install,
                warranty_start_date=install,
                sales_contact_name=DEFAULT_SALES_CONTACT[0],
                sales_contact_phone=DEFAULT_SALES_CONTACT[1],
                sales_contact_email=DEFAULT_SALES_CONTACT[2],
                field_contact_name="DRH Superintendent",
                notes=f"Plan: {plan} | VS BUID {job_number}" if plan else f"VS BUID {job_number}",
            )
            db.add(job)
            db.flush()
            _set_feed_note(job, "VS:", feed_text)
            counts["created"] += 1
        else:
            changed = False
            # Scheduling is app-managed: feeds never touch install_date on existing
            # jobs (the VS: note still carries the builder's schedule for reference).
            # Measure date fills in only when the app has none yet.
            if measure and job.measure_date is None:
                job.measure_date = measure
                changed = True
            if row.get("PO Number") and str(row.get("PO Status")).strip().lower() == "open":
                changed = _bump_to_ordered(job) or changed
            before = job.notes
            _set_feed_note(job, "VS:", feed_text)
            counts["updated" if (changed or job.notes != before) else "skipped"] += 1
    wb.close()
    cleanup()
    db.commit()
    return counts


def sync_century(db: Session, path: Path) -> dict:
    wb, cleanup = _load_wb(path)
    if "All Cabinet Tasks" not in wb.sheetnames:
        wb.close()
        cleanup()
        raise ValueError(f"No 'All Cabinet Tasks' tab in {path.name}")
    rows = wb["All Cabinet Tasks"].iter_rows(min_row=2, values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(rows)]
    idx = {h: i for i, h in enumerate(headers)}

    account = _get_or_create_account(db, CENTURY_ACCOUNT)
    counts = {"created": 0, "updated": 0, "skipped": 0}
    for values in rows:
        row = {h: values[i] for h, i in idx.items() if i < len(values)}
        subdivision = row.get("Subdivision")
        lot = row.get("Lot")
        if not subdivision or lot is None:
            counts["skipped"] += 1
            continue
        community = _get_or_create_community(db, account, str(subdivision).strip())

        sp_status = str(row.get("Job Status") or "").strip()
        start = _as_date(row.get("Projected Start Date"))
        delivery = _as_date(row.get("Cabinet Delivery Date"))
        bits = [b for b in (
            sp_status.lower() or None,
            f"start {_fmt(start)}" if start else None,
            f"cab delivery {_fmt(delivery)}" if delivery else None,
        ) if b]
        feed_text = ", ".join(bits) or "on report"

        job = _find_job(db, community, lot)
        if job is None:
            plan = " ".join(str(row.get(k) or "") for k in ("Plan Name", "Elevation", "Swing")).strip()
            builder_code = row.get("Builder Job Code")
            job = Job(
                job_code=str(builder_code).strip() if builder_code else None,
                account_id=account.id,
                community_id=community.id,
                lot_number=str(lot).strip(),
                address=str(row.get("Address") or f"{subdivision} Lot {lot}").title(),
                job_type=JobType.tract,
                plan=plan[:100] or None,
                status=JobStatus.closed if sp_status == "Complete" else JobStatus.quote,
                sales_contact_name=DEFAULT_SALES_CONTACT[0],
                sales_contact_phone=DEFAULT_SALES_CONTACT[1],
                sales_contact_email=DEFAULT_SALES_CONTACT[2],
                field_contact_name="Century Superintendent",
                notes=f"Plan: {plan}" if plan else None,
            )
            db.add(job)
            db.flush()
            _set_feed_note(job, "SP:", feed_text)
            counts["created"] += 1
        else:
            before = job.notes
            _set_feed_note(job, "SP:", feed_text)
            counts["updated" if job.notes != before else "skipped"] += 1
    wb.close()
    cleanup()
    db.commit()
    return counts


def sync_new_orders(db: Session, path: Path) -> dict:
    """Brian's New Orders Status workbook -> the 4-stage ordering checklists.

    Fill-forward only: a dated stage in the file checks the stage with that
    date; nothing already checked in the app is ever touched or un-checked.
    """
    from app.models import OrderingChecklist

    wb, cleanup = _load_wb(path)
    if "New Orders" not in wb.sheetnames:
        wb.close()
        cleanup()
        raise ValueError(f"No 'New Orders' tab in {path.name}")
    rows = wb["New Orders"].iter_rows(min_row=2, values_only=True)
    headers = [str(h).replace("\n", " ").strip() if h else "" for h in next(rows)]
    idx = {h: i for i, h in enumerate(headers)}

    def col(prefix: str) -> str | None:
        return next((h for h in headers if h.startswith(prefix)), None)

    stage_cols = {
        "stage1": col("1."),
        "stage2": col("2."),
        "stage3": col("3."),
        "stage4": col("4."),
    }
    counts = {"updated": 0, "unchanged": 0, "no_job": 0}
    for values in rows:
        row = {h: values[i] for h, i in idx.items() if i < len(values)}
        code = row.get("Job Code")
        if not code or str(code).startswith("#"):
            continue
        job = db.query(Job).filter(Job.job_code == str(code).strip()).first()
        if job is None:
            counts["no_job"] += 1
            continue

        checklist = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
        if checklist is None:
            checklist = OrderingChecklist(job_id=job.id)
            db.add(checklist)
            db.flush()

        changed = False
        for stage, header in stage_cols.items():
            done_date = _as_date(row.get(header)) if header else None
            if done_date and not getattr(checklist, f"{stage}_done"):
                setattr(checklist, f"{stage}_done", True)
                setattr(checklist, f"{stage}_date", done_date)
                changed = True

        bits = []
        if row.get(col("Carter PO")):
            bits.append(f"Carter PO# {row[col('Carter PO')]}")
        if row.get(col("Carter SO")):
            bits.append(f"Carter SO# {row[col('Carter SO')]}")
        if _as_date(row.get(col("5.0"))):
            bits.append(f"moved to sold folder {_fmt(_as_date(row[col('5.0')]))}")
        note = " | ".join(str(b) for b in bits)
        if note and note not in (checklist.notes or ""):
            checklist.notes = note
            changed = True

        counts["updated" if changed else "unchanged"] += 1
    wb.close()
    cleanup()
    db.commit()
    return counts


def _sync_newest_readable(db: Session, directory: Path, pattern: str, sync_fn) -> dict:
    """Try files newest-first — a workbook open in Excel is unreadable, so fall
    back to the next-most-recent copy rather than failing the whole sync."""
    files = sorted(
        (f for f in directory.glob(pattern) if not f.name.startswith("~")),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {"error": "no file found"}
    skipped = []
    for f in files[:5]:
        try:
            return {"file": f.name, "skipped_locked": skipped, **sync_fn(db, f)}
        except PermissionError:
            skipped.append(f.name)
    return {"error": "all recent files locked", "skipped_locked": skipped}


def sync_all(db: Session) -> dict:
    """Run all feeds against the newest readable file in each OneDrive location."""
    settings = get_settings()
    result = {
        "vendorsuite": _sync_newest_readable(
            db, Path(settings.vendorsuite_dir), "DRH_Cabinets_Combined_*.xlsx", sync_vendorsuite
        ),
        "century": _sync_newest_readable(
            db, Path(settings.century_dir), "Century Production Report*.xlsx", sync_century
        ),
    }
    new_orders = Path(settings.new_orders_file)
    if new_orders.is_file():
        try:
            result["new_orders"] = {"file": new_orders.name, **sync_new_orders(db, new_orders)}
        except PermissionError:
            result["new_orders"] = {"error": "file locked (open in Excel)"}
    else:
        result["new_orders"] = {"error": "file not found"}
    return result
