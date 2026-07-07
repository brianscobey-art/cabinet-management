"""Import/refresh jobs from the Sold Job Files tree (all builders) into the app.

Usage (from backend/):
    python -m scripts.import_sold_jobs --all "<Sold Job Files root>"
    python -m scripts.import_sold_jobs "<job folder>" ["<job folder>" ...]

A job folder is a directory named for a job — either code-first ("DRLICR-0113
HARP 041326", "JBSI8352") or an address/customer name directly under a local
builder or retail folder ("7738 Red Barrow"). Files inside (including Orders/
Selections/Layouts subfolders) attach as JobDocuments.

Upsert, idempotent: existing jobs (matched by job code, then community+lot for
DRH) get documents attached and blank fields filled — nothing already entered
is overwritten. Unknown jobs are created; DRH ones get the full Summary-PDF
parse (address, super, plan, PO, cabinet color).
"""

import re
import sys
from pathlib import Path

from pypdf import PdfReader

from app.database import SessionLocal
from app.feeds import _find_job
from app.models import (
    Account,
    AccountType,
    Community,
    HardwareSelection,  # noqa: F401  (kept for parity with tracker importer)
    Job,
    JobDocument,
    JobStatus,
    JobType,
    RoomSelection,
)

DEFAULT_SALES_CONTACT = ("Brian Scobey", "850-890-0482", "Brian.Scobey@TownsendBuildingSupply.com")

CODE = re.compile(r"^[A-Z]{2,}[A-Z0-9]*(-[A-Z0-9.]+)?$")
PLACEHOLDER_CONTACTS = {"TBD", "DRH Superintendent", "Century Superintendent"}
STRUCTURAL = {"orders", "selections", "layouts", "pricing", "delivery photos", "photos", "docs", "po's", "pos"}
BLACKLIST = {"NOTE-QUOTES"}

# Folder names use division abbreviations; accounts use the tracker's full names.
DIVISION_NAMES = {
    "DRH Montgomery": "DR Horton Montgomery",
    "DRH Panama City East": "DR Horton Panama City East",
    "DRH Panama City West": "DR Horton Panama City West",
    "DRH Pensacola West": "DR Horton Pensacola West",
    "DRH Pensecola East": "DR Horton Pensacola East",  # folder typo is real
    "DRH Pensacola East": "DR Horton Pensacola East",
}

# Local builder folder -> account name as the tracker knows it.
LOCAL_BUILDER_ACCOUNTS = {
    "Jubilee": "Jubilee Builders",
    "Chris Davis": "Chris Davis and Associates",
    "Vickers": "Suzanne Vickers Construction",
    "Phillips Homes": "Phillips Homes",
    "Holley Development": "Holley Development",
    "Carlee": "Carlee Homes",
}

DOC_TYPE_PATTERNS = [
    ("layout", re.compile(r"\blayout", re.I)),
    ("selections", re.compile(r"\bselection", re.I)),
    ("summary", re.compile(r"\bsummary\b", re.I)),
    ("po", re.compile(r"\bPO\b")),
    ("sales_order", re.compile(r"\bSO\d+\b", re.I)),
    ("order", re.compile(r"\border", re.I)),
]

KNOWN_DOOR_STYLES = ["Shaker", "Flat Panel", "Raised Panel", "Slab", "Dublin"]


EXT_TYPES = {".jpeg": "photo", ".jpg": "photo", ".png": "photo", ".kit": "design_file", ".bak": "design_file"}


def classify(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in EXT_TYPES:
        return EXT_TYPES[ext]
    for doc_type, pattern in DOC_TYPE_PATTERNS:
        if pattern.search(filename):
            return doc_type
    return "document"


def pdf_text(path: Path) -> str:
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except Exception as exc:
        print(f"  ! could not read {path.name}: {exc}")
        return ""


def parse_summary(text: str) -> dict:
    """Pull job facts out of the DRH Summary PDF text."""
    def after(label: str) -> str | None:
        m = re.search(rf"{label}:\s*\n?([^\n]+)", text)
        return m.group(1).strip() if m else None

    facts = {
        "subdivision": after("Subdivision"),
        "address": after("Address"),
        "super_name": after("Buyer"),  # DRH's 'Buyer' field carries the superintendent name
        "plan": after(r"Plan/Elevation/Swing"),
    }
    m = re.search(r"Color:\s*([^\n]+)", text)
    facts["cabinet_color"] = m.group(1).strip().title() if m else None
    m = re.search(r"PO#\s*(\d+)", text)
    facts["po_number"] = m.group(1) if m else None
    m = re.search(r"Total PO:\s*\n?([\d,]+\.\d{2})", text)
    facts["po_total"] = m.group(1) if m else None
    return facts


def find_door_style(so_text: str) -> str | None:
    for style in KNOWN_DOOR_STYLES:
        if style.lower() in so_text.lower():
            return style
    return None


def discover(root: Path) -> list[Path]:
    """Find job folders anywhere under the Sold Job Files tree."""
    found: list[Path] = []
    for d in sorted(root.rglob("*")):
        if not d.is_dir() or d.name in BLACKLIST or d.name.lower() in STRUCTURAL:
            continue
        token = d.name.split()[0]
        has_direct_files = any(c.is_file() for c in d.iterdir())
        has_structural_child = any(c.is_dir() and c.name.lower() in STRUCTURAL for c in d.iterdir())
        if CODE.match(token) and token not in DIVISION_NAMES and (has_direct_files or has_structural_child):
            found.append(d)
            continue
        parent, grandparent = d.parent.name, d.parent.parent.name if d.parent.parent else ""
        if (grandparent == "Local Builders" or parent.endswith("-Retail")) and (
            has_direct_files or has_structural_child
        ):
            found.append(d)
    # drop anything nested inside another discovered folder
    found_set = set(found)
    return [d for d in found if not any(p in found_set for p in d.parents)]


def _get_or_create_account(db, name: str, acc_type: AccountType) -> Account:
    account = db.query(Account).filter(Account.name == name).first()
    if account is None:
        account = Account(name=name, type=acc_type)
        db.add(account)
        db.flush()
    return account


def _get_or_create_community(db, account: Account, name: str, market: str | None) -> Community:
    community = (
        db.query(Community)
        .filter(Community.account_id == account.id, Community.name == name)
        .first()
    )
    if community is None:
        community = Community(account_id=account.id, name=name, market=market)
        db.add(community)
        db.flush()
    return community


def _attach_documents(db, job: Job, files: list[Path]) -> int:
    existing = {d.file_path for d in db.query(JobDocument).filter(JobDocument.job_id == job.id).all()}
    added = 0
    for f in files:
        if str(f) in existing:
            continue
        db.add(JobDocument(job_id=job.id, filename=f.name, doc_type=classify(f.name), file_path=str(f)))
        added += 1
    return added


def _fill_room_selection(db, job: Job, brand: str | None, door_style: str | None, finish: str | None) -> None:
    if not (brand or door_style or finish):
        return
    room = (
        db.query(RoomSelection)
        .filter(RoomSelection.job_id == job.id, RoomSelection.room == "Whole House")
        .first()
    )
    if room is None:
        room = RoomSelection(job_id=job.id, room="Whole House", notes="From sold job file")
        db.add(room)
        db.flush()
    for attr, value in (("cabinet_brand", brand), ("door_style", door_style), ("finish", finish)):
        if value and not getattr(room, attr):
            setattr(room, attr, value)


def _resolve_context(folder: Path) -> dict | None:
    """Work out account/community/type from where the folder sits in the tree."""
    parts = folder.parts
    if "DR Horton - All" in parts:
        division = DIVISION_NAMES.get(folder.parent.parent.name, folder.parent.parent.name)
        community = re.sub(r"\s+\d+$", "", folder.parent.name)
        return {"kind": "drh", "account": division, "acc_type": AccountType.builder, "community": community}
    if "Century - All" in parts:
        community = re.sub(r"\s+\d+$", "", folder.parent.name)
        return {"kind": "generic", "account": "Century PC", "acc_type": AccountType.builder, "community": community}
    if "Local Builders" in parts:
        i = parts.index("Local Builders")
        builder = parts[i + 1]
        account = LOCAL_BUILDER_ACCOUNTS.get(builder, builder)
        # anything between the builder dir and the job folder is a community ("Village Oaks")
        community = parts[i + 2] if len(parts) - 2 > i + 1 else None
        return {"kind": "generic", "account": account, "acc_type": AccountType.builder, "community": community}
    if folder.parent.name.endswith("-Retail"):
        account = folder.parent.name.replace("-Retail", "").strip()
        return {"kind": "generic", "account": account, "acc_type": AccountType.retail, "community": None}
    if folder.parent.name in ("Dothan", "Panama City"):  # retail folder directly under a region
        return {"kind": "generic", "account": folder.name, "acc_type": AccountType.retail, "community": None}
    return None


def import_job_folder(db, folder: Path) -> str:
    ctx = _resolve_context(folder)
    if ctx is None:
        print(f"? cannot place {folder} — skipped")
        return "unplaced"

    token = folder.name.split()[0]
    job_code = token if CODE.match(token) else None
    lot_match = re.search(r"-0*(\d+)$", job_code) if job_code else None
    lot_number = lot_match.group(1) if lot_match else None

    files = [f for f in sorted(folder.rglob("*")) if f.is_file()]

    # DRH folders carry parseable Summary/SO PDFs
    facts: dict = {}
    door_style = None
    so_match = None
    if ctx["kind"] == "drh":
        summary = next((f for f in files if classify(f.name) == "summary"), None)
        facts = parse_summary(pdf_text(summary)) if summary else {}
        so_file = next((f for f in files if classify(f.name) == "sales_order"), None)
        so_match = re.search(r"\b(SO\d+)\b", so_file.name) if so_file else None
        door_style = find_door_style(pdf_text(so_file)[:4000]) if so_file else None

    account = _get_or_create_account(db, ctx["account"], ctx["acc_type"])
    community = None
    community_name = facts.get("subdivision") or ctx["community"]
    if community_name:
        market = None
        if facts.get("address") and "," in facts["address"]:
            market = facts["address"].split(",", 1)[1].strip().title()
        community = _get_or_create_community(db, account, community_name, market)

    # --- match existing ---
    job = db.query(Job).filter(Job.job_code == job_code).first() if job_code else None
    if job is None and community is not None and lot_number:
        job = _find_job(db, community, lot_number)
        if job is not None and job.job_code is None and job_code:
            job.job_code = job_code

    if job is not None:
        added = _attach_documents(db, job, files)
        if facts.get("super_name") and job.field_contact_name in PLACEHOLDER_CONTACTS:
            job.field_contact_name = facts["super_name"].title()
        _fill_room_selection(db, job, "Everluxe" if ctx["kind"] == "drh" else None,
                             door_style, facts.get("cabinet_color"))
        marker = f"Sold file: {folder.name}"
        if marker not in (job.notes or ""):
            job.notes = f"{job.notes} | {marker}".strip(" |") if job.notes else marker
        db.commit()
        return "updated" if added else "unchanged"

    # --- create new ---
    note_bits = []
    if facts.get("plan"):
        note_bits.append(f"Plan/Elev/Swing: {facts['plan']}")
    if facts.get("po_number"):
        total = f" (${facts['po_total']} turnkey)" if facts.get("po_total") else ""
        note_bits.append(f"DRH PO# {facts['po_number']}{total}")
    if so_match:
        note_bits.append(f"Everluxe {so_match.group(1)}")
    note_bits.append(f"Sold file: {folder.name}")

    job = Job(
        job_code=job_code,
        account_id=account.id,
        community_id=community.id if community else None,
        lot_number=lot_number,
        address=(facts.get("address") or folder.name).title(),
        job_type=JobType.tract if ctx["acc_type"] == AccountType.builder else JobType.custom,
        status=JobStatus.ordered if ctx["kind"] == "drh" else JobStatus.quote,
        sales_contact_name=DEFAULT_SALES_CONTACT[0],
        sales_contact_phone=DEFAULT_SALES_CONTACT[1],
        sales_contact_email=DEFAULT_SALES_CONTACT[2],
        field_contact_name=(facts.get("super_name") or "TBD").title(),
        notes=" | ".join(note_bits),
    )
    db.add(job)
    db.flush()
    _fill_room_selection(db, job, "Everluxe" if ctx["kind"] == "drh" else None,
                         door_style, facts.get("cabinet_color"))
    _attach_documents(db, job, files)
    db.commit()
    return "created"


def main() -> None:
    args = sys.argv[1:]
    with SessionLocal() as db:
        if args and args[0] == "--all":
            root = Path(args[1])
            folders = discover(root)
            print(f"{len(folders)} job folders discovered under {root.name}")
        else:
            folders = [Path(a) for a in args]
            if not folders:
                print('Usage: python -m scripts.import_sold_jobs --all "<root>" | "<job folder>" ...')
                sys.exit(1)
        counts: dict[str, int] = {}
        for folder in folders:
            try:
                result = import_job_folder(db, folder)
            except Exception as exc:
                result = "failed"
                print(f"! {folder.name}: {exc}")
            counts[result] = counts.get(result, 0) + 1
        print(counts)


if __name__ == "__main__":
    main()
