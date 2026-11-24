"""PO Line Items (DOMO) -- see app.po_lines.

Feed files normally reach the cloud through R2 (app.feeds). The test copy
cannot read R2, so the PC can also post a file straight to a service here,
with the service's PO_LINES_INGEST_TOKEN (off when unset).
"""
import hmac
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import po_lines
from app.api.deps import read_access
from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["po-lines"])

FEEDS = ("po-lines", "job-pos", "i-account-detail", "job-accounts", "setup-requests", "jobs-snapshot")


def _token_ok(token: str | None) -> None:
    expected = get_settings().po_lines_ingest_token
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad or missing ingest token")


@router.post("/feeds/ingest/{feed}")
async def ingest(feed: str, request: Request, x_ingest_token: str | None = Header(default=None),
                 db: Session = Depends(get_db)):
    """Body = the CSV file. po-lines replaces the lines of every PO in it and
    returns the checks for those POs; job-pos is the Purchase Orders feed
    (DOMO Job POs); i-account-detail is the I-Account Detail email."""
    _token_ok(x_ingest_token)
    if feed not in FEEDS:
        raise HTTPException(status_code=404, detail=f"unknown feed; one of {', '.join(FEEDS)}")
    text = (await request.body()).decode("utf-8-sig")
    if feed == "po-lines":
        rows = po_lines.parse(text)
        result = po_lines.replace_lines(db, rows)
        return {**result, "checks": po_lines.checks(db, {r["po_number"] for r in rows})}
    if feed == "i-account-detail":
        return po_lines.replace_iaccount(db, po_lines.parse_iaccount(text))
    if feed == "job-accounts":
        from app import account_codes

        return account_codes.replace_accounts(db, account_codes.parse_accounts(text, "Job Account feed"))
    if feed == "setup-requests":
        from app import account_codes

        return account_codes.replace_setups(db, account_codes.parse_setups(text))
    if feed == "jobs-snapshot":
        # Test copy only: load job codes + I/G codes from a tracker snapshot so
        # the Account Code check can be tried on real data without live's DB.
        if not get_settings().is_test:
            raise HTTPException(status_code=403, detail="jobs-snapshot is for the test copy only")
        from app import account_codes_test_data

        return account_codes_test_data.load_jobs(db, text)
    from app import domo_pos

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "DOMO Job POs ingest.csv"
        path.write_text(text, encoding="utf-8")
        return domo_pos.apply(db, path)


@router.post("/feeds/code-check/run")
def code_check_run(x_ingest_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Run the Account Code check now and return the summary + open flags."""
    _token_ok(x_ingest_token)
    from app import account_codes

    return {"summary": account_codes.run(db), "flags": account_codes.flags(db, "all")}


@router.get("/feeds/po-lines/report")
def ingest_report(q: str, x_ingest_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Same as the signed-in report, for checking a run from the PC."""
    _token_ok(x_ingest_token)
    return {**po_lines.job_report(db, q), "checks": po_lines.checks(db)}


@router.get("/reports/po-lines", dependencies=[Depends(read_access)])
def po_lines_report(q: str, db: Session = Depends(get_db)):
    return po_lines.job_report(db, q)


@router.get("/reports/po-lines/checks", dependencies=[Depends(read_access)])
def po_lines_checks(db: Session = Depends(get_db)):
    return po_lines.checks(db)
