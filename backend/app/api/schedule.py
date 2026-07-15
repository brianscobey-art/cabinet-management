from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access
from app.database import get_db
from app.models import Job, JobStatus

router = APIRouter(tags=["schedule"])


class InstallItem(BaseModel):
    job_id: int
    job_code: str | None
    address: str
    account_name: str
    community_name: str | None
    lot_number: str | None
    status: JobStatus
    install_date: date
    salesperson: str | None  # first name for the calendar chip


@router.get("/schedule/installs", response_model=list[InstallItem], dependencies=[Depends(read_access)])
def installs(start: date, end: date, account_id: int | None = None, db: Session = Depends(get_db)):
    """Cabinet installs scheduled in [start, end] — feeds the calendar views."""
    query = (
        db.query(Job)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(
            Job.install_date.isnot(None),
            Job.install_date >= start,
            Job.install_date <= end,
            Job.status.notin_((JobStatus.closed, JobStatus.void)),  # archived jobs stay off the calendar
        )
    )
    if account_id is not None:
        query = query.filter(Job.account_id == account_id)
    jobs = query.order_by(Job.install_date, Job.job_code).all()
    return [
        InstallItem(
            job_id=j.id,
            job_code=j.job_code,
            address=j.address,
            account_name=j.account.name,
            community_name=j.community.name if j.community else None,
            lot_number=j.lot_number,
            status=j.status,
            install_date=j.install_date,
            salesperson=(j.sales_contact_name or "").strip().split()[0] or None
            if j.sales_contact_name
            else None,
        )
        for j in jobs
    ]
