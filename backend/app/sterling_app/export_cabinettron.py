"""Hand a sold Sterling job to CabinetTron.

COAST suite: Sterling and CabinetTron run in the same app, so this calls the
sold hand-off (app/suite/handoff.py) directly. No stored CabinetTron login and
no HTTP round trip. The hand-off runs the double checks (job code, lot,
selections, excluded SKUs, prices) and writes the job's timeline row.

Re-sending a sold job is allowed: it updates the job while it is still before
ordering, holds it if the order already went out, and refuses once ordered.
"""

import re
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.sterling_app.models import CoverSheet, Job
from app.suite.schemas import LineIn, RoomIn, SoldIn

JOB_CODE_RE = re.compile(r"^[A-Z0-9]{2,8}-\d{3,4}$")


class ExportError(Exception):
    pass


def _job_code(db: Session, ct: Session, job: Job) -> str:
    """The cover sheet's job code, or the code the subdivision's other lots use."""
    sheet = (
        db.query(CoverSheet).filter(CoverSheet.job_id == job.id, CoverSheet.job_code.isnot(None))
        .order_by(CoverSheet.id.desc()).first()
    )
    code = (sheet.job_code or "").strip().upper() if sheet else ""
    if JOB_CODE_RE.match(code):
        return code
    if job.community and job.lot_number:
        from app.feeds import _derive_job_code, _lot4
        from app.models import Account, Community

        comm = (
            ct.query(Community).join(Account, Community.account_id == Account.id)
            .filter(Community.name == job.community.strip(), Account.name == (job.builder or "").strip())
            .first()
        )
        derived = _derive_job_code(ct, comm, _lot4(job.lot_number)) if comm is not None else None
        if derived:
            return derived
    raise ExportError(
        "No job code for this job. Put it on the job's cover sheet (like DRLB50-0062), then send it again."
    )


def sold_payload(db: Session, ct: Session, job: Job) -> SoldIn:
    account_name = (job.builder or "").strip() or job.name.strip()
    retail = job.job_type.value == "remodel"
    return SoldIn(
        job_code=_job_code(db, ct, job),
        account_name=account_name,
        account_type="retail" if retail else "builder",
        job_type=job.job_type.value,
        community=job.community,
        lot_number=job.lot_number,
        address=job.address or job.name,
        plan=job.plan,
        sales_contact_name=job.sales_contact_name or "Brian Scobey",
        field_contact_name=job.field_contact_name or job.sales_contact_name or "",
        field_contact_phone=job.field_contact_phone,
        rooms=[
            RoomIn(room=r.name, zone=r.zone, cabinet_brand=r.cabinet_brand, series=r.series,
                   door_style=r.door_style, finish=r.finish)
            for r in job.rooms
        ],
        lines=[
            LineIn(sku=ln.sku, qty=ln.qty, list_price=Decimal(str(ln.list_price or 0)),
                   room=(f"{r.name} {r.zone}".strip() if r.zone else r.name)[:100])
            for r in job.rooms for ln in r.lines
        ],
    )


def export_job(db: Session, job: Job) -> dict:
    """Returns {"job_id", "job_code", "url", "level", "issues"} for the CabinetTron job."""
    from app.database import SessionLocal
    from app.models import Job as CtJob
    from app.suite.handoff import sterling_sold

    with SessionLocal() as ct:
        data = sold_payload(db, ct, job)
        try:
            out = sterling_sold(ct, data, None)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"issues": [str(exc.detail)]}
            raise ExportError("CabinetTron refused it: " + "; ".join(detail.get("issues") or ["no reason given"]))
        ct_job = ct.query(CtJob).filter(CtJob.job_code == out["job_code"]).one()
        return {"job_id": ct_job.id, "job_code": out["job_code"], "url": f"/jobs/{ct_job.id}",
                "level": out["level"], "issues": out["issues"]}
