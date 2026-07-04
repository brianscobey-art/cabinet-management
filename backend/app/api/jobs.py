from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import read_access, write_access
from app.api.schemas import JobCreate, JobDetail, JobListItem, JobOut, JobUpdate
from app.database import get_db
from app.models import Account, Community, Job, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_job_or_404(job_id: int, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _check_community(db: Session, account_id: int, community_id: int | None) -> None:
    """A job's community must belong to the job's account."""
    if community_id is None:
        return
    community = db.get(Community, community_id)
    if community is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community not found")
    if community.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Community belongs to a different account",
        )


def _to_list_item(job: Job) -> JobListItem:
    return JobListItem(
        id=job.id,
        account_id=job.account_id,
        account_name=job.account.name,
        community_name=job.community.name if job.community else None,
        lot_number=job.lot_number,
        address=job.address,
        job_type=job.job_type,
        status=job.status,
        install_date=job.install_date,
    )


@router.get("", response_model=list[JobListItem], dependencies=[Depends(read_access)])
def list_jobs(
    account_id: int | None = None,
    community_id: int | None = None,
    status_filter: JobStatus | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Job).options(joinedload(Job.account), joinedload(Job.community))
    if account_id is not None:
        query = query.filter(Job.account_id == account_id)
    if community_id is not None:
        query = query.filter(Job.community_id == community_id)
    if status_filter is not None:
        query = query.filter(Job.status == status_filter)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Job.address.ilike(like), Job.lot_number.ilike(like)))
    jobs = query.order_by(Job.updated_at.desc()).limit(500).all()
    return [_to_list_item(j) for j in jobs]


@router.post(
    "", response_model=JobOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    if db.get(Account, payload.account_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    _check_community(db, payload.account_id, payload.community_id)
    job = Job(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobDetail, dependencies=[Depends(read_access)])
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(
            joinedload(Job.account),
            joinedload(Job.community),
            selectinload(Job.room_selections),
            selectinload(Job.hardware_selections),
        )
        .filter(Job.id == job_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobDetail(
        **JobOut.model_validate(job).model_dump(),
        account_name=job.account.name,
        community_name=job.community.name if job.community else None,
        room_selections=job.room_selections,
        hardware_selections=job.hardware_selections,
    )


@router.patch("/{job_id}", response_model=JobOut, dependencies=[Depends(write_access)])
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    job = get_job_or_404(job_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if "community_id" in updates:
        _check_community(db, job.account_id, updates["community_id"])
    # Warranty starts at install date (spec §4) — default it when install_date is set.
    if updates.get("install_date") and not job.warranty_start_date and "warranty_start_date" not in updates:
        updates["warranty_start_date"] = updates["install_date"]
    for key, value in updates.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return job
