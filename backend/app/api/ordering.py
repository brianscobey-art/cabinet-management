"""National-builder ordering pipeline — Brian's 4-step cabinet ordering process.

Stage completion is manual (a human confirms each step), but a fresh checklist
is pre-seeded from the documents already attached to the job:
PO + Selections files -> stage 1, Order + Layout -> stage 2, an SO -> stage 3.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access, write_access
from app.database import get_db
from app.models import Account, AccountType, Job, JobDocument, JobStatus, OrderingChecklist

router = APIRouter(tags=["ordering"])

from app.api.deps import NATIONAL_BUILDER_PREFIXES  # noqa: E402

STAGES = ("stage1", "stage2", "stage3", "stage4")

# The ordering board is a pre-order worklist: once a job is ordered (2.0-Ord) or
# beyond, it drops off. These are the only statuses shown by default.
PRE_ORDER_STATUSES = (
    JobStatus.track,     # 1.0-Track
    JobStatus.preord,    # 1.1-PreOrd
    JobStatus.ndord,     # 1.2-NdOrd
    JobStatus.ordprcss,  # 1.3-Ord Prcss
    JobStatus.ordsub,    # 1.4-OrdSub
    JobStatus.ordpo,     # 1.5-OrdPO
)

STAGE_LABELS = {
    "stage1": "1. PO's and Selection File Creation",
    "stage2": "2. Orders and Layouts",
    "stage3": "3. SO's and Order Comparison",
    "stage4": "4. POs Attached",
}

# doc types that suggest a stage already happened (seeding only, never overrides a human)
_STAGE_DOC_RULES = {
    "stage1": {"po", "selections"},
    "stage2": {"order", "layout"},
    "stage3": {"sales_order"},
}


class ChecklistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: int
    stage1_done: bool
    stage2_done: bool
    stage3_done: bool
    stage4_done: bool
    stage1_date: date | None
    stage2_date: date | None
    stage3_date: date | None
    stage4_date: date | None
    notes: str | None


class ChecklistUpdate(BaseModel):
    stage1_done: bool | None = None
    stage2_done: bool | None = None
    stage3_done: bool | None = None
    stage4_done: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class BoardRow(BaseModel):
    job_id: int
    job_code: str | None
    address: str
    account_name: str
    community_name: str | None
    lot_number: str | None
    status: JobStatus
    checklist: ChecklistOut


def _seed_from_documents(db: Session, job_id: int, checklist: OrderingChecklist) -> None:
    doc_types = {d.doc_type for d in db.query(JobDocument).filter(JobDocument.job_id == job_id).all()}
    for stage, required in _STAGE_DOC_RULES.items():
        if required <= doc_types:
            setattr(checklist, f"{stage}_done", True)


def get_or_create_checklist(db: Session, job: Job) -> OrderingChecklist:
    checklist = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
    if checklist is None:
        checklist = OrderingChecklist(job_id=job.id)
        _seed_from_documents(db, job.id, checklist)
        db.add(checklist)
        db.commit()
        db.refresh(checklist)
    return checklist


@router.get("/jobs/{job_id}/ordering", response_model=ChecklistOut, dependencies=[Depends(read_access)])
def get_checklist(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return get_or_create_checklist(db, job)


@router.patch("/jobs/{job_id}/ordering", response_model=ChecklistOut, dependencies=[Depends(write_access)])
def update_checklist(job_id: int, payload: ChecklistUpdate, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    checklist = get_or_create_checklist(db, job)
    updates = payload.model_dump(exclude_unset=True)
    for stage in STAGES:
        key = f"{stage}_done"
        if key in updates and updates[key] is not None and updates[key] != getattr(checklist, key):
            setattr(checklist, key, updates[key])
            # stamp when a human marks it done; clear when unchecked
            setattr(checklist, f"{stage}_date", datetime.now().date() if updates[key] else None)
    if "notes" in updates:
        checklist.notes = updates["notes"]
    db.commit()
    db.refresh(checklist)
    return checklist


def _is_filed(cl) -> bool:
    """Stage 4 complete (our PO attached) and the job folder filed under Sold Jobs."""
    return bool(cl.stage4_done and (cl.moved_to_sold_date is not None or cl.current_folder == "sold"))


@router.get("/ordering", response_model=list[BoardRow], dependencies=[Depends(read_access)])
def ordering_board(
    account_id: int | None = None,
    community_id: int | None = None,
    include_ordered: bool = False,
    db: Session = Depends(get_db),
):
    """National-builder jobs still to be ordered (pre-order stages), with their
    4-stage progress. Pass include_ordered=true to also show ordered/completed jobs."""
    query = (
        db.query(Job)
        .join(Account, Job.account_id == Account.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(
            Account.type == AccountType.builder,
            or_(*[Account.name.like(f"{p}%") for p in NATIONAL_BUILDER_PREFIXES]),
            Job.status.notin_((JobStatus.closed, JobStatus.void)),  # archived never on the board
        )
    )
    if account_id is not None:
        query = query.filter(Job.account_id == account_id)
    if community_id is not None:
        query = query.filter(Job.community_id == community_id)
    if not include_ordered:
        query = query.filter(Job.status.in_(PRE_ORDER_STATUSES))
    jobs = query.order_by(Job.job_code.asc().nulls_last(), Job.id).limit(500).all()

    checklists = {
        c.job_id: c
        for c in db.query(OrderingChecklist)
        .filter(OrderingChecklist.job_id.in_([j.id for j in jobs]))
        .all()
    }
    rows = []
    for job in jobs:
        checklist = checklists.get(job.id)
        # Done and filed: our PO is attached AND the folder has been moved to the
        # Sold Jobs file. Nothing left to work, so it drops off the board.
        if checklist is not None and _is_filed(checklist):
            continue
        if checklist is None:
            checklist = OrderingChecklist(job_id=job.id)
            _seed_from_documents(db, job.id, checklist)
            db.add(checklist)
            db.flush()  # apply column defaults before serializing
        rows.append(
            BoardRow(
                job_id=job.id,
                job_code=job.job_code,
                address=job.address,
                account_name=job.account.name,
                community_name=job.community.name if job.community else None,
                lot_number=job.lot_number,
                status=job.status,
                checklist=ChecklistOut.model_validate(checklist),
            )
        )
    db.commit()  # persist any newly seeded checklists
    return rows
