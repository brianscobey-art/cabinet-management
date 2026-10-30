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
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Account, AccountType, Community, Job, JobStatus, JobType
from app.sales import resolve_salesperson

DEFAULT_SALES_CONTACT = ("Brian Scobey", "850-890-0482", "Brian.Scobey@CarterLumber.com")

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
    """Excel gives datetimes; the SupplyPro XML export gives ISO strings
    ('2026-02-27T00:00:00.000'). Anything else is not a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})", value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _fmt(d: date | None) -> str:
    return f"{d.month}/{d.day}/{d:%y}" if d else ""


def _money(value):
    from decimal import Decimal, InvalidOperation

    if value is None or isinstance(value, str):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d != 0 else None


def _po_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    s = str(value).strip()
    return s or None


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


def _norm_name(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _get_or_create_community(db: Session, account: Account, name: str) -> Community:
    """Exact name first; otherwise a community of the same builder whose name
    is the same place spelled longer or shorter ("Independence" from
    VendorSuite is the tracker's "Independence 60's"). Creating a second
    community for one place is how every house there ended up twice."""
    community = (
        db.query(Community)
        .filter(Community.account_id == account.id, Community.name == name)
        .first()
    )
    if community is None:
        want = _norm_name(name)
        if len(want) >= 5:
            for c in db.query(Community).filter(Community.account_id == account.id).all():
                have = _norm_name(c.name)
                if len(have) >= 5 and (have.startswith(want) or want.startswith(have)):
                    return c
    if community is None:
        community = Community(account_id=account.id, name=name)
        db.add(community)
        db.flush()
    return community


def merge_duplicate_houses(db: Session) -> int:
    """Fold an uncoded feed-created house into its coded twin: same builder,
    same lot, same place under two community spellings (VendorSuite's
    "Independence" vs the tracker's "Independence 60's"). The coded house
    keeps its identity and status; it gains the PO facts and dates the twin
    carried; everything attached to the twin moves over; the twin is deleted."""
    from app.database import Base

    merged = 0
    uncoded = (
        db.query(Job).join(Account, Job.account_id == Account.id)
        .filter(Account.type == AccountType.builder, Job.job_code.is_(None), Job.community_id.isnot(None))
        .all()
    )
    for dup in uncoded:
        want_lot = _canon_lot(dup.lot_number)
        if want_lot is None or dup.community is None:
            continue
        dup_comm = _norm_name(dup.community.name)
        keeper = None
        for cand in (db.query(Job).filter(Job.account_id == dup.account_id, Job.job_code.isnot(None),
                                           Job.community_id.isnot(None), Job.id != dup.id).all()):
            if _canon_lot(cand.lot_number) != want_lot or cand.community is None:
                continue
            have = _norm_name(cand.community.name)
            if have == dup_comm or (len(dup_comm) >= 5 and len(have) >= 5
                                    and (have.startswith(dup_comm) or dup_comm.startswith(have))):
                keeper = cand
                break
        if keeper is None:
            continue
        for attr in ("builder_po", "po_amount", "po_status", "po_check_number", "po_paid_date", "plan",
                     "measure_date", "install_date", "warranty_start_date", "field_contact_phone"):
            if getattr(keeper, attr, None) in (None, "") and getattr(dup, attr, None) not in (None, ""):
                setattr(keeper, attr, getattr(dup, attr))
        for tag in ("VS:", "SP:"):
            m = re.search(rf"{tag}[^|]*", dup.notes or "")
            if m and tag not in (keeper.notes or ""):
                keeper.notes = f"{keeper.notes or ''} | {m.group(0).strip()}".strip(" |")
        if (dup.notes or "").startswith("Plan:") and "VS BUID" in (dup.notes or "") and "VS BUID" not in (keeper.notes or ""):
            buid = re.search(r"VS BUID \d+", dup.notes)
            if buid:
                keeper.notes = f"{keeper.notes or ''} | {buid.group(0)}".strip(" |")
        # Children: move them; a one-per-job table keeps the keeper's row.
        for t in Base.metadata.sorted_tables:
            if "job_id" not in t.c or t.name == "jobs":
                continue
            unique = bool(t.c.job_id.unique) or any(
                len(u.columns) == 1 and "job_id" in u.columns
                for u in t.constraints if u.__class__.__name__ == "UniqueConstraint")
            if unique and db.execute(t.select().where(t.c.job_id == keeper.id)).first() is not None:
                db.execute(t.delete().where(t.c.job_id == dup.id))
            else:
                db.execute(t.update().where(t.c.job_id == dup.id).values(job_id=keeper.id))
        db.delete(dup)
        merged += 1
    if merged:
        db.commit()
    return merged


def _find_job(db: Session, community: Community, lot) -> Job | None:
    want = _canon_lot(lot)
    if want is None:
        return None
    for job in db.query(Job).filter(Job.community_id == community.id).all():
        if _canon_lot(job.lot_number) == want:
            return job
    return None


def _tracker_prefix(community_name: str) -> str | None:
    """The job-code prefix the 3.0 tracker uses for a community, for a community
    that has no coded house in CabinetTron yet (Independence -> DRID60). Names
    are matched loosely: the tracker says "Independence 60's", the feed says
    "Independence"."""
    try:
        from app.smartsheet.api import _tracker_rows

        rows, ok, _ = _tracker_rows()
    except Exception:  # noqa: BLE001
        return None
    want = re.sub(r"[^a-z0-9]", "", (community_name or "").lower())
    if not want:
        return None
    counts: dict[str, int] = {}
    for r in rows:
        comm = re.sub(r"[^a-z0-9]", "", str(r.get("Community") or "").lower())
        code = str(r.get("Job Code") or "").strip()
        if not comm or "-" not in code:
            continue
        if comm == want or comm.startswith(want) or want.startswith(comm):
            prefix = code.rsplit("-", 1)[0]
            counts[prefix] = counts.get(prefix, 0) + 1
    return max(counts, key=lambda p: counts[p]) if counts else None


def _lot4(lot) -> str:
    """Job codes carry the lot as four digits (lot 20 -> 0020); lettered or
    longer lots are kept as they are (A034, 21121)."""
    s = str(lot or "").strip()
    return s.zfill(4) if s.isdigit() and len(s) <= 4 else s


def _derive_job_code(db: Session, community: Community, lot4: str) -> str | None:
    """New lots inherit the code prefix their coded siblings use (DRLICR-0135);
    a community with no coded house yet borrows the prefix from the tracker."""
    prefixes: dict[str, int] = {}
    for (code,) in (
        db.query(Job.job_code).filter(Job.community_id == community.id, Job.job_code.isnot(None)).all()
    ):
        if "-" in code:
            prefix = code.rsplit("-", 1)[0]
            prefixes[prefix] = prefixes.get(prefix, 0) + 1
    prefix = max(prefixes, key=lambda p: prefixes[p]) if prefixes else _tracker_prefix(community.name)
    if not prefix or not lot4:
        return None
    candidate = f"{prefix}-{lot4}"
    if db.query(Job).filter(Job.job_code == candidate).first():
        return None  # collision — leave uncoded rather than mislabel
    return candidate


def backfill_job_codes(db: Session) -> int:
    """Give a code to builder houses the feeds created before their community
    had one to inherit (Century houses, the first Independence lots). Runs at
    the end of every sync; the tracker import still overrides a code later."""
    n = 0
    jobs = (
        db.query(Job).join(Account, Job.account_id == Account.id)
        .filter(Account.type == AccountType.builder, Job.job_code.is_(None), Job.community_id.isnot(None))
        .all()
    )
    for job in jobs:
        code = _derive_job_code(db, job.community, _lot4(job.lot_number))
        if code:
            job.job_code = code
            n += 1
    if n:
        db.commit()
    return n


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
    if job.status in (JobStatus.track, JobStatus.preord, JobStatus.ndord):
        job.status = JobStatus.ord
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

        # builder-side PO facts, straight from the authoritative VS report
        po_number = _po_str(row.get("PO Number"))
        po_amount = _money(row.get("PO Amount"))
        po_status = str(row.get("PO Status")).strip() if row.get("PO Status") else None
        po_check = _po_str(row.get("Check #"))
        po_paid = _as_date(row.get("PO Status Date")) if (po_status or "").lower() == "paid" else None

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
                status=JobStatus.ord if row.get("PO Number") else JobStatus.track,
                measure_date=measure,
                install_date=install,
                warranty_start_date=install,
                builder_po=po_number,
                po_amount=po_amount,
                po_status=po_status,
                po_check_number=po_check,
                po_paid_date=po_paid,
                salesperson=resolve_salesperson(account_name),
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
            # PO facts are builder-authoritative — refresh from the daily VS report
            for attr, value in (("builder_po", po_number), ("po_amount", po_amount), ("po_status", po_status),
                                ("po_check_number", po_check), ("po_paid_date", po_paid)):
                if value is not None and getattr(job, attr) != value:
                    setattr(job, attr, value)
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


CENTURY_PLACEHOLDER_CONTACTS = {"TBD", "Century Superintendent"}
_FAKE_PHONES = {"555-555-5555", "5555555555"}


def _century_subdivision(name) -> str:
    """SupplyPro lists some communities twice ('Grand Oaks at Callaway' and
    'LCA - Grand Oaks at Callaway') — the LCA prefix is the same place."""
    s = str(name).strip()
    return s[6:].strip() if s.upper().startswith("LCA - ") else s


_SSML = "{urn:schemas-microsoft-com:office:spreadsheet}"


def _spreadsheetml_tabs(path: Path) -> dict[str, list[dict]]:
    """SupplyPro's scheduled export (since 10/2/26) is Excel 2003 XML, not
    .xlsx. Each worksheet starts with a title row, so the header is the first
    row that contains 'Lot'. Returns {tab name: [row dicts]}."""
    import xml.etree.ElementTree as ET

    out: dict[str, list[dict]] = {}
    root = ET.parse(path).getroot()
    for ws in root.iter(_SSML + "Worksheet"):
        rows: list[list] = []
        for row in ws.iter(_SSML + "Row"):
            vals: list = []
            for cell in row.iter(_SSML + "Cell"):
                idx = cell.get(_SSML + "Index")
                if idx:
                    while len(vals) < int(idx) - 1:
                        vals.append(None)
                data = cell.find(_SSML + "Data")
                vals.append(data.text if data is not None else None)
            rows.append(vals)
        head = next((i for i, r in enumerate(rows) if "Lot" in [str(x).strip() for x in r if x]), None)
        if head is None:
            out[ws.get(_SSML + "Name")] = []
            continue
        headers = [str(x).strip() if x else "" for x in rows[head]]
        out[ws.get(_SSML + "Name")] = [dict(zip(headers, r)) for r in rows[head + 1:] if any(v for v in r)]
    return out


def century_candidates(directory: Path) -> list[Path]:
    """SupplyPro Century files, newest first by the MMDDYY in the filename
    (revision R.N breaks ties). Files without a date code are ignored.
    Both the old .xlsx and the current .xml export count."""
    dated = []
    for f in list(directory.glob("Century Cabinet Jobs - SupplyPro*.xlsx")) + list(directory.glob("Century Cabinet Jobs - SupplyPro*.xml")):
        if f.name.startswith("~"):
            continue
        m = re.search(r"(\d{2})(\d{2})(\d{2})(?:\s+R\.?(\d+))?", f.name)
        if not m:
            continue
        mm, dd, yy, rev = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
        try:
            dated.append(((date(2000 + yy, mm, dd), rev), f))
        except ValueError:
            continue
    return [f for _, f in sorted(dated, key=lambda t: t[0], reverse=True)]


def sync_century(db: Session, path: Path) -> dict:
    """SupplyPro 'Century Cabinet Jobs' workbook -> Century jobs.

    'Cabinet Jobs' tab: subdivision/lot/address, builder contact, and the
    measure/order/deliver dates. 'Cabinet POs' tab adds plan and PO number.
    """
    if path.suffix.lower() == ".xml":
        tabs = _spreadsheetml_tabs(path)
    else:
        wb, cleanup = _load_wb(path)

        def read_tab(name: str) -> list[dict]:
            rows = wb[name].iter_rows(min_row=2, values_only=True)
            headers = [str(h).strip() if h is not None else "" for h in next(rows)]
            idx = {h: i for i, h in enumerate(headers)}
            return [
                {h: values[i] for h, i in idx.items() if i < len(values)}
                for values in rows
            ]

        tabs = {name: read_tab(name) for name in wb.sheetnames}
        wb.close()
        cleanup()
    if "Cabinet Jobs" not in tabs:
        raise ValueError(f"No 'Cabinet Jobs' tab in {path.name}")

    records: dict[tuple[str, str], dict] = {}
    for row in tabs["Cabinet Jobs"]:
        sub, lot = row.get("Subdivision"), row.get("Lot")
        if not sub or lot is None:
            continue
        records[(_century_subdivision(sub), _canon_lot(lot))] = {"jobs": row}
    for row in tabs.get("Cabinet POs", []):
        sub, lot = row.get("Subdivision"), row.get("Lot")
        if not sub or lot is None:
            continue
        records.setdefault((_century_subdivision(sub), _canon_lot(lot)), {})["pos"] = row

    account = _get_or_create_account(db, CENTURY_ACCOUNT)
    counts = {"created": 0, "updated": 0, "skipped": 0}
    for (sub, _), rec in records.items():
        jobs_row = rec.get("jobs", {})
        pos_row = rec.get("pos", {})
        lot = jobs_row.get("Lot") or pos_row.get("Lot")
        community = _get_or_create_community(db, account, sub)

        measure = _as_date(jobs_row.get("Measure Cabinets")) or _as_date(pos_row.get("Measure Date"))
        ordered = _as_date(jobs_row.get("Order Cabinets"))
        deliver = _as_date(jobs_row.get("Deliver Cabinets")) or _as_date(pos_row.get("Deliver / Install Date"))
        po_number = pos_row.get("PO Number")
        plan = " ".join(
            str(pos_row.get(k) or "") for k in ("Plan", "Elevation", "Swing") if pos_row.get(k)
        ).replace("See Start", "").strip()

        bits = [b for b in (
            f"PO {po_number}" if po_number else None,
            f"measure {_fmt(measure)}" if measure else None,
            f"order {_fmt(ordered)}" if ordered else None,
            f"deliver {_fmt(deliver)}" if deliver else None,
        ) if b]
        feed_text = ", ".join(bits) or "on report"

        contact = str(jobs_row.get("Builder Contact") or "").strip()
        phone = str(jobs_row.get("Contact Phone") or "").strip()
        if phone.replace("-", "") in {p.replace("-", "") for p in _FAKE_PHONES}:
            phone = ""

        job = _find_job(db, community, lot)
        if job is None:
            address = str(jobs_row.get("Address") or f"{sub} Lot {lot}").title()
            city, state = jobs_row.get("City"), jobs_row.get("State")
            if city:
                address = f"{address}, {city}, {state or ''}".strip(", ")
            job = Job(
                job_code=_derive_job_code(db, community, _lot4(lot)),
                account_id=account.id,
                community_id=community.id,
                lot_number=str(lot).strip(),
                address=address,
                job_type=JobType.tract,
                plan=plan[:100] or None,
                status=JobStatus.ord if ordered and ordered <= date.today() else JobStatus.track,
                measure_date=measure,
                builder_po=_po_str(po_number),
                salesperson=resolve_salesperson(CENTURY_ACCOUNT),
                sales_contact_name=DEFAULT_SALES_CONTACT[0],
                sales_contact_phone=DEFAULT_SALES_CONTACT[1],
                sales_contact_email=DEFAULT_SALES_CONTACT[2],
                field_contact_name=contact.title() if contact else "Century Superintendent",
                field_contact_phone=phone or None,
            )
            db.add(job)
            db.flush()
            _set_feed_note(job, "SP:", feed_text)
            counts["created"] += 1
        else:
            changed = False
            if measure and job.measure_date is None:
                job.measure_date = measure
                changed = True
            if po_number and job.builder_po != _po_str(po_number):
                job.builder_po = _po_str(po_number)
                changed = True
            if plan and not job.plan:
                job.plan = plan[:100]
                changed = True
            if contact and job.field_contact_name in CENTURY_PLACEHOLDER_CONTACTS:
                job.field_contact_name = contact.title()
                if phone:
                    job.field_contact_phone = phone
                changed = True
            if ordered and ordered <= date.today():
                changed = _bump_to_ordered(job) or changed
            before = job.notes
            _set_feed_note(job, "SP:", feed_text)
            counts["updated" if (changed or job.notes != before) else "skipped"] += 1
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
    norm = {" ".join(h.split()).lower(): h for h in headers if h}

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

        # --- adopt the columns the workbook was the only home for ----------
        # CabinetTron generates this sheet now, so these have to live in the db
        # or regenerating it would blank them. Fill-blanks-only: a value already
        # in the app always wins, and re-importing our own output is a no-op.
        # Headers carry stray double spaces ("Install  Pay $"), so match on the
        # space-collapsed name rather than the literal string.
        def get(name: str):
            key = norm.get(" ".join(name.split()).lower())
            return row.get(key) if key else None

        def adopt(attr: str, value, cast=None):
            nonlocal changed
            if value in (None, "") or getattr(checklist, attr) is not None:
                return
            try:
                setattr(checklist, attr, cast(value) if cast else value)
            except (TypeError, ValueError):
                return
            changed = True

        def _int(v):
            return int(float(str(v).strip()))

        adopt("setup_date", _as_date(get("Setup Date")))
        adopt("carter_po_number", get("Carter PO #"), lambda v: str(v).strip()[:50])
        adopt("carter_so_number", get("Carter SO #"), lambda v: str(v).strip()[:50])
        adopt("carter_po_date", _as_date(get("Carter PO Date")))
        adopt("so_number", get("Everluxe SO #"), lambda v: str(v).strip()[:50])
        adopt("so_amount", get("Everluxe SO $"), lambda v: Decimal(str(v)))
        adopt("lumber_2x4x8", get("2x4x8 SYP #2"), _int)
        adopt("lumber_1x4x8", get("1x4x8 SYP #2"), _int)
        adopt("lumber_1x6x8", get("1x6x8 SYP #2"), _int)
        adopt("plywood_half", get('1/2" Plywood'), _int)
        adopt("misc_materials", get("Misc"), lambda v: str(v).strip()[:200])
        adopt("folder_name", get("Folder Name"), lambda v: str(v).strip()[:200])
        adopt("po_total", get("Total PO ($)"), lambda v: Decimal(str(v)))
        # Install pay is never invented — but this is the workbook's own number
        # coming home, not a guess, and dropping it would lose 93 rows.
        adopt("install_pay", get("Install Pay $"), lambda v: Decimal(str(v)))
        packet = get("Install Packet in Folder")
        if packet not in (None, "") and checklist.installer_pay_sheet is None:
            checklist.installer_pay_sheet = str(packet).strip().lower() in ("yes", "y", "true", "1")
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


def _sync_newest_readable(db: Session, files: list[Path], sync_fn, guard_key: str | None = None) -> dict:
    """Try files newest-first — a workbook open in Excel is unreadable, so fall
    back to the next-most-recent copy rather than failing the whole sync.

    With guard_key, a file that was already imported is skipped without being
    parsed, so frequent polling costs a stat instead of a workbook read."""
    if not files:
        return {"error": "no file found"}
    skipped = []
    for f in files[:5]:
        try:
            if guard_key and _unchanged(db, guard_key, f):
                return {"file": f.name, "unchanged": True}
            result = {"file": f.name, "skipped_locked": skipped, **sync_fn(db, f)}
            if guard_key:
                _stamp(db, guard_key, f)
            return result
        except PermissionError:
            skipped.append(f.name)
    return {"error": "all recent files locked", "skipped_locked": skipped}


def _by_mtime(directory: Path, pattern: str) -> list[Path]:
    return sorted(
        (f for f in directory.glob(pattern) if not f.name.startswith("~")),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )


TRACKER_FINGERPRINT_KEY = "tracker_fingerprint"


def _fingerprint(f: Path) -> str:
    """Cheap identity for a tracker file: name + size + mtime. Reading this costs
    one stat; parsing the 4.5 MB workbook costs seconds and a lot of memory, so
    the poll compares fingerprints first and does nothing when nothing changed."""
    st = f.stat()
    return f"{f.name}:{st.st_size}:{int(st.st_mtime)}"


def _unchanged(db, key: str, f: Path) -> bool:
    """True when this exact file was already imported under `key`."""
    from app.models import get_setting

    return get_setting(db, key) == _fingerprint(f)


def _stamp(db, key: str, f: Path) -> None:
    """Remember a file only AFTER its import succeeded."""
    from app.models import set_setting

    set_setting(db, key, _fingerprint(f))


def sync_tracker(db: Session) -> dict:
    """Sync jobs from the newest readable 3.0 Online Sales Tracker .xlsm — status
    (CONST LVL) + install dates. Falls back to the next copy if one is open in Excel."""
    from scripts.import_tracker import sync_tracker_file  # app→scripts: reuse the CLI logic

    settings = get_settings()
    from app.storage import TRACKER_GLOB  # digits only — skips the "- Copy" spares

    files = _by_mtime(Path(settings.tracker_dir), TRACKER_GLOB)
    if not files:
        return {"error": "no tracker file found"}
    skipped = []
    from app.models import get_setting, set_setting

    for f in files[:5]:
        try:
            fp = _fingerprint(f)
            if get_setting(db, TRACKER_FINGERPRINT_KEY) == fp:
                return {"file": f.name, "unchanged": True}
            result = sync_tracker_file(db, f)
            # The same .xlsm carries POTracker (Our PO # -> Job Code) for the PO
            # receipts report; refresh that map from this file too.
            try:
                from app.po_receipts import ingest_potracker

                result["job_pos"] = ingest_potracker(db, f)
            except Exception as exc:  # noqa: BLE001
                result["job_pos"] = f"error: {exc}"
            set_setting(db, TRACKER_FINGERPRINT_KEY, fp)
            db.commit()  # sibling feed syncs each commit their own work
            return {"skipped_locked": skipped, **result}
        except PermissionError:
            skipped.append(f.name)
    return {"error": "all recent tracker files locked", "skipped_locked": skipped}


def sync_all(db: Session) -> dict:
    """Run all feeds against the newest readable file in each OneDrive location."""
    settings = get_settings()
    result = {}
    # In the cloud, pull the latest feed files from R2 into the local feed dirs
    # first (no-op when R2 isn't configured). A hiccup here must not block sync.
    if settings.r2_pull_enabled:
        try:
            from app.storage import hydrate_feeds

            result["hydrate"] = hydrate_feeds(settings)
        except Exception as exc:  # noqa: BLE001
            result["hydrate"] = {"error": str(exc)}
    result.update({
        "tracker": sync_tracker(db),
        "vendorsuite": _sync_newest_readable(
            db, _by_mtime(Path(settings.vendorsuite_dir), "DRH_Cabinets_Combined_*.xlsx"), sync_vendorsuite
        ),
        "century": _sync_newest_readable(
            db, century_candidates(Path(settings.century_dir)), sync_century
        ),
    })
    new_orders = Path(settings.new_orders_file)
    if new_orders.is_file():
        try:
            result["new_orders"] = {"file": new_orders.name, **sync_new_orders(db, new_orders)}
        except PermissionError:
            result["new_orders"] = {"error": "file locked (open in Excel)"}
    else:
        result["new_orders"] = {"error": "file not found"}
    # PO receipts — live DOMO pull when configured, else newest export file.
    try:
        from app.po_receipts import refresh_receipts

        result["po_receipts"] = refresh_receipts(db)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        result["po_receipts"] = {"error": str(exc)}
    try:
        from app import job_accounts

        result["job_accounts"] = job_accounts.apply(db)
    except Exception as exc:  # noqa: BLE001
        result["job_accounts"] = {"error": str(exc)}
    try:
        from app import domo_pos

        result["domo_pos"] = domo_pos.apply(db)
    except Exception as exc:  # noqa: BLE001
        result["domo_pos"] = {"error": str(exc)}
    try:
        result["job_codes"] = {"merged_duplicates": merge_duplicate_houses(db),
                               "assigned": backfill_job_codes(db)}
    except Exception as exc:  # noqa: BLE001
        result["job_codes"] = {"error": str(exc)}
    return result


def _pull(settings, prefix: str, dest: Path, keep: int = 3) -> int:
    """Download the newest objects under one R2 prefix, skipping ones already
    here unchanged (size AND source timestamp — see storage._fresh)."""
    from app.storage import _client, _download, _fresh, _list

    client = _client(settings)
    dest.mkdir(parents=True, exist_ok=True)
    got = 0
    for key, size, lm in _list(client, settings.r2_bucket, prefix)[:keep]:
        local = dest / Path(key).name
        if not _fresh(local, size, lm):
            _download(client, settings.r2_bucket, key, local, lm)
            got += 1
    return got


def poll_slow(db: Session) -> dict:
    """Hourly: Vendor Suite + Century. Both are rebuilt once a day, so an hourly
    change-guarded look is plenty."""
    settings = get_settings()
    result = {}
    if settings.r2_pull_enabled:
        try:
            _pull(settings, "vendorsuite/", Path(settings.vendorsuite_dir))
            _pull(settings, "century/", Path(settings.century_dir))
        except Exception as exc:  # noqa: BLE001
            result["pull"] = f"error: {exc}"
    result["vendorsuite"] = _sync_newest_readable(
        db, _by_mtime(Path(settings.vendorsuite_dir), "DRH_Cabinets_Combined_*.xlsx"),
        sync_vendorsuite, guard_key="fp_vendorsuite",
    )
    result["century"] = _sync_newest_readable(
        db, century_candidates(Path(settings.century_dir)), sync_century, guard_key="fp_century",
    )
    db.commit()
    # Installer sign-offs and old post walks from Smartsheet (read only, 10/30/26).
    # Hourly so a finished install starts its 48h post-walk clock the same day.
    try:
        from app import field_reports

        result["field_reports"] = field_reports.run(db)
    except Exception as exc:  # noqa: BLE001
        result["field_reports"] = {"error": str(exc)}
    return result


def poll_tracker(db: Session) -> dict:
    """Quick refresh for the 5-minute poll: the tracker (DATA + POTracker), New
    Orders, and the DOMO PO receipts. Each is change-guarded, so an unchanged
    file costs a stat and no parse."""
    settings = get_settings()
    result = {}
    if settings.r2_pull_enabled:
        try:
            result["pulled"] = _pull(settings, "tracker/", Path(settings.tracker_dir))
            _pull(settings, "new-orders/", Path(settings.new_orders_file).parent, keep=1)
            _pull(settings, "po-receipts/", Path(settings.po_receipt_folder), keep=2)
            _pull(settings, "domo-accounts/", Path(settings.domo_accounts_folder), keep=2)
            _pull(settings, "domo-pos/", Path(settings.domo_pos_folder), keep=2)
        except Exception as exc:  # noqa: BLE001 — fall through to whatever is on disk
            result["pulled"] = f"error: {exc}"

    result["tracker"] = sync_tracker(db)
    tracker_changed = not result["tracker"].get("unchanged")

    new_orders = Path(settings.new_orders_file)
    if new_orders.is_file():
        try:
            if _unchanged(db, "fp_new_orders", new_orders):
                result["new_orders"] = {"file": new_orders.name, "unchanged": True}
            else:
                result["new_orders"] = {"file": new_orders.name, **sync_new_orders(db, new_orders)}
                _stamp(db, "fp_new_orders", new_orders)
        except PermissionError:
            result["new_orders"] = {"error": "file locked (open in Excel)"}

    try:
        from app.po_receipts import _newest_file as _newest_receipt
        from app.po_receipts import refresh_receipts

        f = _newest_receipt(Path(settings.po_receipt_folder))
        if f is not None and _unchanged(db, "fp_po_receipts", f):
            result["po_receipts"] = {"file": f.name, "unchanged": True}
        else:
            result["po_receipts"] = refresh_receipts(db)
            if f is not None:
                _stamp(db, "fp_po_receipts", f)
    except Exception as exc:  # noqa: BLE001
        result["po_receipts"] = {"error": str(exc)}

    # G/I codes from DOMO's job accounts: re-match when a new DOMO file lands
    # or the tracker changed (a house that just got its Ashley's Code).
    try:
        from app import job_accounts

        f = job_accounts.newest_file(Path(settings.domo_accounts_folder))
        if f is not None and (tracker_changed or not _unchanged(db, "fp_domo_accounts", f)):
            result["job_accounts"] = job_accounts.apply(db, f)
            _stamp(db, "fp_domo_accounts", f)
    except Exception as exc:  # noqa: BLE001
        result["job_accounts"] = {"error": str(exc)}

    # Our POs per job from DOMO (ordered + received): re-match on a new file, or
    # when job accounts / the tracker moved (a job that just got its I-code).
    try:
        from app import domo_pos

        f = domo_pos.newest_file(Path(settings.domo_pos_folder))
        if f is not None and (tracker_changed or "job_accounts" in result
                              or not _unchanged(db, "fp_domo_pos", f)):
            result["domo_pos"] = domo_pos.apply(db, f)
            _stamp(db, "fp_domo_pos", f)
    except Exception as exc:  # noqa: BLE001
        result["domo_pos"] = {"error": str(exc)}

    db.commit()
    return result
