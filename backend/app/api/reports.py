from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access
from app.database import get_db
from app.models import Account, AccountType, Job, JobStatus, PhaseUpdate
from app.phases import PHASE_LABELS

router = APIRouter(tags=["reports"])


class PhaseReportRow(BaseModel):
    account_name: str
    community_name: str | None
    job_id: int
    job_code: str | None
    lot_number: str | None
    address: str
    plan: str | None
    phase: str | None
    phase_label: str | None
    phase_date: datetime | None


@router.get("/reports/phases", response_model=list[PhaseReportRow], dependencies=[Depends(read_access)])
def phase_report(db: Session = Depends(get_db)):
    """All active builder houses with current phase — sorted builder, community, lot."""
    jobs = (
        db.query(Job)
        .join(Account, Job.account_id == Account.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(Account.type == AccountType.builder, Job.status != JobStatus.closed)
        .all()
    )

    latest: dict[int, PhaseUpdate] = {}
    if jobs:
        sub = (
            db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("max_id"))
            .filter(PhaseUpdate.job_id.in_([j.id for j in jobs]))
            .group_by(PhaseUpdate.job_id)
            .subquery()
        )
        for row in db.query(PhaseUpdate).join(sub, PhaseUpdate.id == sub.c.max_id).all():
            latest[row.job_id] = row

    def sort_key(job: Job):
        lot = (job.lot_number or "").strip()
        return (
            job.account.name.lower(),
            (job.community.name.lower() if job.community else "~"),  # no-community groups last
            (0, int(lot)) if lot.isdigit() else (1, lot),
        )

    rows = []
    for job in sorted(jobs, key=sort_key):
        current = latest.get(job.id)
        rows.append(
            PhaseReportRow(
                account_name=job.account.name,
                community_name=job.community.name if job.community else None,
                job_id=job.id,
                job_code=job.job_code,
                lot_number=job.lot_number,
                address=job.address,
                plan=job.plan,
                phase=current.phase if current else None,
                phase_label=PHASE_LABELS.get(current.phase) if current else None,
                phase_date=current.noted_at if current else None,
            )
        )
    return rows
