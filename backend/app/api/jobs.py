from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import NATIONAL_BUILDER_PREFIXES, read_access, write_access
from app.api.schemas import JobCreate, JobDetail, JobListItem, JobOut, JobUpdate
from app.database import get_db
from app.models import Account, Community, Job, JobStatus, PhaseUpdate
from app.phases import PHASE_LABELS

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


def _check_job_code(db: Session, job_code: str | None, exclude_id: int | None = None) -> None:
    if not job_code:
        return
    clash = db.query(Job).filter(Job.job_code == job_code)
    if exclude_id is not None:
        clash = clash.filter(Job.id != exclude_id)
    if clash.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Job code {job_code} already in use"
        )


def _latest_phases(db: Session, job_ids: list[int]) -> dict[int, str]:
    """job id -> its newest logged phase code (same rule as the phase board)."""
    if not job_ids:
        return {}
    sub = (
        db.query(func.max(PhaseUpdate.id).label("max_id"))
        .filter(PhaseUpdate.job_id.in_(job_ids))
        .group_by(PhaseUpdate.job_id)
        .subquery()
    )
    rows = db.query(PhaseUpdate.job_id, PhaseUpdate.phase).join(sub, PhaseUpdate.id == sub.c.max_id).all()
    return {job_id: phase for job_id, phase in rows}


def _to_list_item(job: Job, phase: str | None = None) -> JobListItem:
    return JobListItem(
        id=job.id,
        job_code=job.job_code,
        account_id=job.account_id,
        account_name=job.account.name,
        community_name=job.community.name if job.community else None,
        lot_number=job.lot_number,
        address=job.address,
        job_type=job.job_type,
        status=job.status,
        install_date=job.install_date,
        phase=phase,
        phase_label=PHASE_LABELS.get(phase) if phase else None,
    )


@router.get("", response_model=list[JobListItem], dependencies=[Depends(read_access)])
def list_jobs(
    account_id: int | None = None,
    community_id: int | None = None,
    account_ids: list[int] | None = Query(None),      # e.g. all DR Horton divisions
    community_ids: list[int] | None = Query(None),    # multi-select communities
    status_filter: JobStatus | None = None,
    archived: bool = False,
    category: str | None = None,  # national | local | dr_horton | century | national_other
    q: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Job).options(joinedload(Job.account), joinedload(Job.community))
    if category:
        national = or_(*[Account.name.like(f"{p}%") for p in NATIONAL_BUILDER_PREFIXES])
        drh = Account.name.like("DR Horton%")
        century = Account.name.like("Century%")
        conditions = {
            "national": national,
            "local": ~national,
            "dr_horton": drh,
            "century": century,
            # national builders added to the prefix list later land here automatically
            "national_other": national & ~drh & ~century,
        }
        if category in conditions:
            query = query.join(Account, Job.account_id == Account.id).filter(conditions[category])
    if account_ids:
        query = query.filter(Job.account_id.in_(account_ids))
    elif account_id is not None:
        query = query.filter(Job.account_id == account_id)
    if community_ids:
        query = query.filter(Job.community_id.in_(community_ids))
    elif community_id is not None:
        query = query.filter(Job.community_id == community_id)
    # Closed and void jobs live on the Archive tab; active views never show them.
    inactive = (JobStatus.closed, JobStatus.void)
    if archived:
        query = query.filter(Job.status.in_(inactive))
    elif status_filter is not None:
        query = query.filter(Job.status == status_filter)
    else:
        query = query.filter(Job.status.notin_(inactive))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(Job.address.ilike(like), Job.lot_number.ilike(like), Job.job_code.ilike(like))
        )
    jobs = query.order_by(Job.job_code.asc().nulls_last(), Job.id).limit(2000).all()
    phases = _latest_phases(db, [j.id for j in jobs])
    return [_to_list_item(j, phases.get(j.id)) for j in jobs]


@router.post(
    "", response_model=JobOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    if db.get(Account, payload.account_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    _check_community(db, payload.account_id, payload.community_id)
    _check_job_code(db, payload.job_code)
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


@router.get("/{job_id}/purchase-orders", dependencies=[Depends(read_access)])
def job_purchase_orders(job_id: int, db: Session = Depends(get_db)):
    """The job page's Orders section: builder PO, G/I codes, and every one of
    our POs with its DOMO receipt (or how late it is)."""
    from app.po_receipts import job_purchase_orders as build

    return build(db, get_job_or_404(job_id, db))


def _clean(v):
    """Tracker cells: '#N/A', 'NA', 0 and floats like 297770024.0 -> tidy text or None."""
    if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return None if s.upper() in ("", "NA", "N/A", "#N/A", "NONE") else s


@router.get("/{job_id}/site", dependencies=[Depends(read_access)])
def job_site(job_id: int, db: Session = Depends(get_db)):
    """The job page's Jobsite card: what CabinetTron doesn't store (city/state,
    builder job code, swing, installer) from the job's tracker row (Brian 10/29/26)."""
    from app.smartsheet.api import _tracker_rows

    job = get_job_or_404(job_id, db)
    try:
        rows, _, _ = _tracker_rows()
    except Exception:  # noqa: BLE001 -- the card still shows what the job has
        rows = []
    code = (job.job_code or "").strip().upper()
    r = next((x for x in rows if str(x.get("Job Code") or "").strip().upper() == code), None) if code else None
    if r is None:
        return {"in_tracker": False}
    return {
        "in_tracker": True,
        "city": _clean(r.get("City")),
        "state": _clean(r.get("State")),
        "builder_job_code": _clean(r.get("Builder Job Code")),
        "swing": _clean(r.get("Swing")),
        "zone": _clean(r.get("Zone")),
        "installer": _clean(r.get("Installer")),
        "builder_po": _clean(r.get("PO#  Order #") or r.get("PO# Order #")),
    }


@router.patch("/{job_id}", response_model=JobOut, dependencies=[Depends(write_access)])
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    job = get_job_or_404(job_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if "community_id" in updates:
        _check_community(db, job.account_id, updates["community_id"])
    if "job_code" in updates:
        _check_job_code(db, updates["job_code"], exclude_id=job.id)
    # Warranty starts at install date (spec §4) — default it when install_date is set.
    if updates.get("install_date") and not job.warranty_start_date and "warranty_start_date" not in updates:
        updates["warranty_start_date"] = updates["install_date"]
    # Picking a KSR makes them the sales contact (Brian 10/29/26).
    if updates.get("ksr"):
        from app.sales import ksr_contact

        name, phone, email = ksr_contact(db, updates["ksr"])
        updates.update(ksr=name, sales_contact_name=name, sales_contact_phone=phone, sales_contact_email=email)
    for key, value in updates.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return job
