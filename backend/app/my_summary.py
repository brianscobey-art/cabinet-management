"""My Stuff > Summary reports for one KSR (Brian 10/29/26): what's been
received on their jobs, their upcoming installs, and their upcoming service.

A job belongs to a KSR through app.sales.effective_ksr (the job's own KSR,
else the account default). Received items are DOMO receipts joined to our POs
through the tracker's PO Tracking sheet (the same join as the job page).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app.models import Job, JobPo, JobStatus, PoReceipt, ServiceRequest, Visit
from app.sales import effective_ksr

INACTIVE = (JobStatus.closed, JobStatus.void)
SERVICE_PREFIXES = ("service_", "warranty_")
VISIT_LABELS = {
    "service_t1": "Service (small)", "service_t2": "Service", "service_t3": "Service (large)",
    "warranty_t1": "Warranty", "warranty_t2_eval": "Warranty eval", "warranty_t2_complete": "Warranty completion",
}


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _job(j: Job) -> dict:
    return {"job_id": j.id, "job_code": j.job_code, "address": j.address,
            "community": j.community.name if j.community else None, "status": j.status.value}


def ksr_jobs(db: Session, ksr: str) -> list[Job]:
    jobs = (db.query(Job).options(joinedload(Job.account), joinedload(Job.community))
            .filter(Job.status.notin_(INACTIVE)).all())
    return [j for j in jobs if (effective_ksr(j) or "") == ksr]


def summary(db: Session, ksr: str, days: int | None = 30, today: date | None = None) -> dict:
    today = today or date.today()
    jobs = ksr_jobs(db, ksr)
    by_code = {j.job_code: j for j in jobs if j.job_code}
    ids = [j.id for j in jobs]

    # Our POs on these jobs and their DOMO receipts.
    lines = db.query(JobPo).filter(JobPo.job_code.in_(list(by_code))).all() if by_code else []
    po_line: dict[str, JobPo] = {}
    for jp in lines:
        if jp.our_po and jp.our_po not in po_line:
            po_line[jp.our_po] = jp
    recs = db.query(PoReceipt).filter(PoReceipt.order_number.in_(list(po_line))).all() if po_line else []
    since = today - timedelta(days=days) if days else None
    received = []
    for r in recs:
        if since and (r.receipt_date is None or r.receipt_date < since):
            continue
        jp = po_line[r.order_number]
        received.append({**_job(by_code[jp.job_code]), "received": _iso(r.receipt_date),
                         "our_po": jp.our_po, "vendor": jp.vendor or r.supplier, "product": jp.product,
                         "receipt_number": r.receipt_number, "landed_cost": _f(r.landed_cost)})
    received.sort(key=lambda x: (x["received"] or "", x["job_code"] or ""), reverse=True)

    # Per job: are its POs in? -> the install list's material column.
    got = {r.order_number for r in recs}
    pos_by_job: dict[str, set[str]] = {}
    for po, jp in po_line.items():
        pos_by_job.setdefault(jp.job_code, set()).add(po)

    def material(code: str | None) -> str:
        pos = pos_by_job.get(code or "", set())
        if not pos:
            return "no POs"
        n = len(pos & got)
        return "received" if n == len(pos) else ("partial" if n else "awaiting")

    installs = sorted(
        ({**_job(j), "install_date": _iso(j.install_date), "material": material(j.job_code)}
         for j in jobs if j.install_date and j.install_date >= today),
        key=lambda x: (x["install_date"], x["job_code"] or ""),
    )

    # Pending service / warranty visits, then scheduled service requests with no visit yet.
    service = []
    visits = (db.query(Visit).options(joinedload(Visit.assignee))
              .filter(Visit.job_id.in_(ids), Visit.status == "pending").all()) if ids else []
    jobs_by_id = {j.id: j for j in jobs}
    covered = set()
    for v in visits:
        if not v.visit_type.startswith(SERVICE_PREFIXES):
            continue
        covered.add(v.service_request_id)
        when = v.scheduled_date or v.open_date or v.close_date
        service.append({**_job(jobs_by_id[v.job_id]), "date": _iso(when),
                        "scheduled": v.scheduled_date is not None, "due": _iso(v.close_date),
                        "kind": VISIT_LABELS.get(v.visit_type, v.visit_type),
                        "who": v.assignee.name if v.assignee else "Tech",
                        "notes": v.notes})
    srs = (db.query(ServiceRequest).filter(ServiceRequest.job_id.in_(ids),
                                           ServiceRequest.scheduled_date >= today).all()) if ids else []
    for sr in srs:
        if sr.id in covered:
            continue
        service.append({**_job(jobs_by_id[sr.job_id]), "date": _iso(sr.scheduled_date), "scheduled": True,
                        "due": None, "kind": sr.title or "Service request", "who": None,
                        "notes": sr.material_status and f"Parts: {sr.material_status}"})
    service.sort(key=lambda x: (x["date"] or "9999", x["job_code"] or ""))

    return {"ksr": ksr, "days": days, "active_jobs": len(jobs), "received": received,
            "received_cost": round(sum(r["landed_cost"] or 0 for r in received), 2),
            "installs": installs, "service": service}
