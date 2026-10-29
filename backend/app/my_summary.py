"""My Stuff > Summary reports for one KSR (Brian 10/29/26): what's been
received on their jobs, their upcoming installs, and their upcoming service.

A job belongs to a KSR through app.sales.effective_ksr (the job's own KSR,
else the account default). Received items are DOMO receipts joined to our POs
through the tracker's PO Tracking sheet (the same join as the job page).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app.models import Job, JobStatus, ServiceRequest, Visit
from app.po_receipts import po_lines
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
    ids = [j.id for j in jobs]

    # Our POs on these jobs (DOMO + tracker sheet) and their receipts.
    lines = po_lines(db, jobs)
    jobs_by_id = {j.id: j for j in jobs}
    since = today - timedelta(days=days) if days else None
    received = []
    for job_id, pos in lines.items():
        for p in pos:
            for r in p["receipts"]:
                d = r["receipt_date"]
                if since and (d is None or d < since):
                    continue
                received.append({**_job(jobs_by_id[job_id]), "received": _iso(d), "our_po": p["our_po"],
                                 "vendor": p["vendor"] or r["supplier"], "product": p["product"],
                                 "receipt_number": r["receipt_number"], "landed_cost": r["landed_cost"]})
    received.sort(key=lambda x: (x["received"] or "", x["job_code"] or ""), reverse=True)

    def material(job_id: int) -> str:
        pos = lines.get(job_id, [])
        if not pos:
            return "no POs"
        n = sum(1 for p in pos if p["receipts"] or (p["status"] or "").lower() == "closed")
        return "received" if n == len(pos) else ("partial" if n else "awaiting")

    installs = sorted(
        ({**_job(j), "install_date": _iso(j.install_date), "material": material(j.id)}
         for j in jobs if j.install_date and j.install_date >= today),
        key=lambda x: (x["install_date"], x["job_code"] or ""),
    )

    # Pending service / warranty visits, then scheduled service requests with no visit yet.
    service = []
    visits = (db.query(Visit).options(joinedload(Visit.assignee))
              .filter(Visit.job_id.in_(ids), Visit.status == "pending").all()) if ids else []
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
