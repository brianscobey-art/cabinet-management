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

import re
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
    wb = load_workbook(path, read_only=True, data_only=True)
    tab = next((n for n in wb.sheetnames if n.startswith("DRH Cabinets Combined")), None)
    if tab is None:
        wb.close()
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
                status=JobStatus.ordered if row.get("PO Number") else JobStatus.quote,
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
            if row.get("PO Number") and str(row.get("PO Status")).strip().lower() == "open":
                changed = _bump_to_ordered(job) or changed
            before = job.notes
            _set_feed_note(job, "VS:", feed_text)
            counts["updated" if (changed or job.notes != before) else "skipped"] += 1
    wb.close()
    db.commit()
    return counts


def sync_century(db: Session, path: Path) -> dict:
    wb = load_workbook(path, read_only=True, data_only=True)
    if "All Cabinet Tasks" not in wb.sheetnames:
        wb.close()
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
    db.commit()
    return counts


def sync_all(db: Session) -> dict:
    """Run both feeds against the newest file in each OneDrive folder."""
    settings = get_settings()
    result: dict = {}

    vs_file = latest_file(Path(settings.vendorsuite_dir), "DRH_Cabinets_Combined_*.xlsx")
    if vs_file:
        result["vendorsuite"] = {"file": vs_file.name, **sync_vendorsuite(db, vs_file)}
    else:
        result["vendorsuite"] = {"error": "no combined file found"}

    century_file = latest_file(Path(settings.century_dir), "Century Production Report*.xlsx")
    if century_file:
        result["century"] = {"file": century_file.name, **sync_century(db, century_file)}
    else:
        result["century"] = {"error": "no production report found"}
    return result
