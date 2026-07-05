"""Import sold-job folders (DR Horton style) into the system.

Each folder is one job: `<JOBCODE> <PLAN> <MMDDYY>` containing Layout / Order /
PO / SO#### / Selections / Summary PDFs. We parse the Summary PDF for the job
facts, infer account (division) and community from the folder tree, create the
job with a room selection, and register every file as a JobDocument.

Usage (from backend/):
    python -m scripts.import_sold_jobs "<job folder>" ["<job folder>" ...]

Safe to re-run: a job whose notes carry the same job code is skipped.
"""

import re
import sys
from pathlib import Path

from pypdf import PdfReader

from app.database import SessionLocal
from app.models import (
    Account,
    AccountType,
    Community,
    Job,
    JobDocument,
    JobStatus,
    JobType,
    RoomSelection,
)

DEFAULT_SALES_CONTACT = ("Brian Scobey", "850-890-0482", "Brian.Scobey@TownsendBuildingSupply.com")

DOC_TYPE_PATTERNS = [
    ("layout", re.compile(r"\blayout\b", re.I)),
    ("selections", re.compile(r"\bselections\b", re.I)),
    ("summary", re.compile(r"\bsummary\b", re.I)),
    ("po", re.compile(r"\bPO\b")),
    ("sales_order", re.compile(r"\bSO\d+\b", re.I)),
    ("order", re.compile(r"\border\b", re.I)),
]

KNOWN_DOOR_STYLES = ["Shaker", "Flat Panel", "Raised Panel", "Slab"]

# Folder names use division abbreviations; accounts use the tracker's full names.
DIVISION_NAMES = {
    "DRH Montgomery": "DR Horton Montgomery",
    "DRH Panama City East": "DR Horton Panama City East",
    "DRH Panama City West": "DR Horton Panama City West",
    "DRH Pensacola West": "DR Horton Pensacola West",
    "DRH Pensecola East": "DR Horton Pensacola East",  # folder typo is real
    "DRH Pensacola East": "DR Horton Pensacola East",
}


def classify(filename: str) -> str:
    for doc_type, pattern in DOC_TYPE_PATTERNS:
        if pattern.search(filename):
            return doc_type
    return "document"


def pdf_text(path: Path) -> str:
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except Exception as exc:  # unreadable PDF shouldn't kill the whole import
        print(f"  ! could not read {path.name}: {exc}")
        return ""


def parse_summary(text: str) -> dict:
    """Pull job facts out of a DRH Summary PDF.

    Each division formats these differently — Montgomery uses "Label:\nvalue",
    Panama City uses bare "Label\nvalue" lines, Pensacola uses "Lot Address:" /
    "Superintendent:" inline — so every field tries the known variants.
    """

    def grab(*labels: str) -> str | None:
        for label in labels:
            m = re.search(rf"^{label}\s*:?\s*\n?\s*([^\n]+)", text, re.M | re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return None

    address = grab("Lot Address", "Address")
    city = grab(r"Lot City/State/Zip", r"City / State / Zip", r"Lot City, St\s+Zip")
    if address and city and city.lower() not in address.lower():
        address = f"{address}, {city}"

    plan = grab(r"Plan/Elevation/Swing")
    if not plan:  # Panama City splits these into three bare-line fields
        parts = [
            (re.search(rf"^{label}\s*\n([^\n]+)", text, re.M) or [None, None])[1]
            for label in ("Plan", "Elevation", "Swing")
        ]
        if any(parts):
            plan = "/".join(p.strip() if p else "?" for p in parts)

    facts = {
        "subdivision": grab("Subdivision Name", "Subdivision"),
        "address": address,
        # Montgomery's "Buyer" field actually carries the superintendent's name
        "super_name": grab("Superintendent", "Buyer"),
        "plan": plan,
    }
    m = re.search(r"Color:\s*([^\n]+)", text)
    facts["cabinet_color"] = m.group(1).strip().title() if m else None
    m = re.search(r"(?:PO\s*#?\s*:?\s*\n?\s*|PURCHASE ORDER\s+)(\d{4,})", text)
    facts["po_number"] = m.group(1) if m else None
    m = re.search(r"Total PO:?\s*\n?\s*\$?([\d,]+\.\d{2})", text)
    facts["po_total"] = m.group(1) if m else None
    return facts


def find_door_style(so_text: str) -> tuple[str | None, str | None]:
    """Door style + color from the Everluxe SO line items (e.g. 'Shaker White-Base Cabinet')."""
    for style in KNOWN_DOOR_STYLES:
        m = re.search(rf"{style}\s+([A-Z][a-z]+)-", so_text)
        if m:
            return style, m.group(1)
        if style.lower() in so_text.lower():
            return style, None
    return None, None


def import_job_folder(db, folder: Path) -> None:
    if not folder.is_dir():
        print(f"! not a folder: {folder}")
        return

    # Folder name: "DRLICR-0113 HARP 041326" -> job code + lot number
    job_code = folder.name.split()[0]
    lot_match = re.search(r"-0*(\d+)$", job_code)
    lot_number = lot_match.group(1) if lot_match else None

    if db.query(Job).filter(Job.job_code == job_code).first():
        print(f"= {job_code} already imported, skipping")
        return

    # Community folder: "Links Crossing 26843"; division folder: "DRH Montgomery"
    community_name = re.sub(r"\s+\d+$", "", folder.parent.name)
    division_name = DIVISION_NAMES.get(folder.parent.parent.name, folder.parent.parent.name)

    files = sorted(f for f in folder.iterdir() if f.is_file())
    summary = next((f for f in files if classify(f.name) == "summary"), None)
    facts = parse_summary(pdf_text(summary)) if summary else {}

    so_file = next((f for f in files if classify(f.name) == "sales_order"), None)
    so_match = re.search(r"\b(SO\d+)\b", so_file.name) if so_file else None
    door_style, so_color = find_door_style(pdf_text(so_file)[:4000]) if so_file else (None, None)

    account = db.query(Account).filter(Account.name == division_name).first()
    if account is None:
        account = Account(name=division_name, type=AccountType.builder)
        db.add(account)
        db.flush()

    community_name = facts.get("subdivision") or community_name
    community = (
        db.query(Community)
        .filter(Community.account_id == account.id, Community.name == community_name)
        .first()
    )
    if community is None:
        market = None
        if facts.get("address") and "," in facts["address"]:
            market = facts["address"].split(",", 1)[1].strip().title()
        community = Community(account_id=account.id, name=community_name, market=market)
        db.add(community)
        db.flush()

    note_bits = [f"Plan/Elev/Swing: {facts.get('plan') or '?'}"]
    if facts.get("po_number"):
        total = f" (${facts['po_total']} turnkey)" if facts.get("po_total") else ""
        note_bits.append(f"DRH PO# {facts['po_number']}{total}")
    if so_match:
        note_bits.append(f"Everluxe {so_match.group(1)}")
    note_bits.append(f"Imported from {folder}")

    job = Job(
        job_code=job_code,
        account_id=account.id,
        community_id=community.id,
        lot_number=lot_number,
        address=(facts.get("address") or folder.name).title(),
        job_type=JobType.tract,
        status=JobStatus.ordered,
        sales_contact_name=DEFAULT_SALES_CONTACT[0],
        sales_contact_phone=DEFAULT_SALES_CONTACT[1],
        sales_contact_email=DEFAULT_SALES_CONTACT[2],
        field_contact_name=(facts.get("super_name") or "DRH Superintendent").title(),
        notes=" | ".join(note_bits),
    )
    db.add(job)
    db.flush()

    finish = facts.get("cabinet_color") or so_color
    if finish or door_style:
        db.add(
            RoomSelection(
                job_id=job.id,
                room="Whole House",
                cabinet_brand="Everluxe",
                door_style=door_style,
                finish=finish,
                notes=f"From DRH selections ({job_code})",
            )
        )

    for f in files:
        db.add(
            JobDocument(job_id=job.id, filename=f.name, doc_type=classify(f.name), file_path=str(f))
        )

    db.commit()
    print(
        f"+ {job_code}: job #{job.id} — {job.address} "
        f"({account.name} / {community.name}, lot {lot_number}), {len(files)} documents"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python -m scripts.import_sold_jobs "<job folder>" ...')
        sys.exit(1)
    with SessionLocal() as db:
        for arg in sys.argv[1:]:
            import_job_folder(db, Path(arg))


if __name__ == "__main__":
    main()
