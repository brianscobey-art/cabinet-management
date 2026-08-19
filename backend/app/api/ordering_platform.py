"""Ordering Platform — fine-grained sub-steps under the 4-stage ordering pipeline.

The classic ordering board (app/api/ordering.py) tracks one checkbox per stage.
This platform breaks each stage into the actual worklist steps and syncs the
job's workflow status as the trigger steps are checked:

    s2.ordSub   (order sent to vendor)        -> 1.3-Ord Prcss
    s3.soRecv   (SO back from vendor)         -> 1.4-OrdSub
    s4.sentCoord (sent to coordinator for PO) -> 1.5-OrdPO
    s4.poFiled  (PO filed, folder moved)      -> 2.0-Ord

Unchecking a trigger step drops the status back to the highest still-checked
trigger (floor 1.2-NdOrd). Statuses outside the 1.2→2.0 window are never
touched — if a job moved on to install/punch, this page won't drag it back.
"""

from decimal import Decimal
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps import NATIONAL_BUILDER_PREFIXES, read_access, write_access
from app.api.ordering import get_or_create_checklist
from app.database import get_db
from app.models import Account, AccountType, Job, JobStatus, OrderingChecklist

router = APIRouter(prefix="/ordering-platform", tags=["ordering-platform"])

DEFAULT_VENDOR = "Everluxe"

# (stage key, stage label, [(step key, step label), ...])
PLATFORM_STAGES = [
    ("s1", "1. PO's & Selection File", [
        ("poRecv", "Builder PO received"),
        ("selFile", "Selection file created"),
        ("selVer", "Selections verified against PO"),
    ]),
    ("s2", "2. Orders & Layouts", [
        ("layout", "Layout drawn"),
        ("ordCr", "Cabinet order created"),
        ("ordSub", "Order sent to vendor for SO"),
    ]),
    ("s3", "3. SO's & Order Comparison", [
        ("soRecv", "SO received from vendor"),
        ("soComp", "Order / SO / layout compared"),
        ("discRes", "Discrepancies resolved"),
    ]),
    ("s4", "4. POs Attached", [
        ("sentCoord", "Order + SO sent to coordinator for Carter PO"),
        ("poGen", "Carter PO generated"),
        ("poEmail", "PO emailed to vendor"),
        ("poFiled", "PO filed & folder moved to sold jobs"),
    ]),
]

ALL_STEP_KEYS = [f"{sk}.{k}" for sk, _, steps in PLATFORM_STAGES for k, _ in steps]
_STAGE_STEPS = {sk: [f"{sk}.{k}" for k, _ in steps] for sk, _, steps in PLATFORM_STAGES}
_STAGE_NUM = {"s1": 1, "s2": 2, "s3": 3, "s4": 4}

# Trigger steps in ladder order: checking one advances the job at least this far;
# unchecking drops back to the highest remaining trigger.
STATUS_TRIGGERS = [
    ("s2.ordSub", JobStatus.ordprcss),   # 1.3
    ("s3.soRecv", JobStatus.ordsub),     # 1.4
    ("s4.sentCoord", JobStatus.ordpo),   # 1.5
    ("s4.poFiled", JobStatus.ord),       # 2.0
]

# The window this page is allowed to move a job's status within.
_LADDER = [JobStatus.ndord, JobStatus.ordprcss, JobStatus.ordsub, JobStatus.ordpo, JobStatus.ord]

WORKLIST_STATUSES = (JobStatus.ndord, JobStatus.ordprcss, JobStatus.ordsub, JobStatus.ordpo)

# Not yet in the pipeline — shown on the "Up Next" list with an Order Now button.
UPCOMING_STATUSES = (JobStatus.track, JobStatus.preord)


def _seed_steps(checklist: OrderingChecklist, job_status: JobStatus) -> bool:
    """Pre-check steps implied by the coarse stage flags and the job's status,
    so existing jobs land on the platform with their history filled in.
    Returns True if anything changed. Never unchecks a human's work."""
    steps = dict(checklist.steps or {})
    before = dict(steps)

    def check_all(stage_key: str, stamp: date | None) -> None:
        for sk in _STAGE_STEPS[stage_key]:
            steps.setdefault(sk, (stamp or date.today()).isoformat())

    for stage_key in _STAGE_STEPS:
        n = _STAGE_NUM[stage_key]
        if getattr(checklist, f"stage{n}_done"):
            check_all(stage_key, getattr(checklist, f"stage{n}_date"))

    try:
        pos = _LADDER.index(job_status)
    except ValueError:
        pos = -1
    if pos >= 1:  # 1.3+ — order went out, stages 1–2 happened
        check_all("s1", checklist.stage1_date)
        check_all("s2", checklist.stage2_date)
    if pos >= 2:  # 1.4+ — SO is back
        steps.setdefault("s3.soRecv", (checklist.stage3_date or date.today()).isoformat())
    if pos >= 3:  # 1.5+ — comparison done, handed to coordinator
        check_all("s3", checklist.stage3_date)
        steps.setdefault("s4.sentCoord", (checklist.stage4_date or date.today()).isoformat())
    if pos >= 4:  # 2.0 — fully ordered
        check_all("s4", checklist.stage4_date)

    if steps != before:
        checklist.steps = steps
        return True
    return False


def _rollup_stages(checklist: OrderingChecklist) -> None:
    """stageN_done = every sub-step of stage N checked (keeps classic board in sync)."""
    steps = checklist.steps or {}
    for stage_key, step_keys in _STAGE_STEPS.items():
        n = _STAGE_NUM[stage_key]
        done = all(k in steps for k in step_keys)
        if done != getattr(checklist, f"stage{n}_done"):
            setattr(checklist, f"stage{n}_done", done)
            setattr(checklist, f"stage{n}_date", date.today() if done else None)


def _sync_status(job: Job, checklist: OrderingChecklist) -> None:
    """Move the job's status to match the highest checked trigger step.
    Only acts when the current status is inside the 1.2→2.0 window."""
    if job.status not in _LADDER:
        return
    target = JobStatus.ndord
    steps = checklist.steps or {}
    for step_key, trig_status in STATUS_TRIGGERS:
        if step_key in steps:
            target = trig_status
    if job.status != target:
        job.status = target


class PlatformRow(BaseModel):
    job_id: int
    job_code: str | None
    address: str
    account_name: str
    community_name: str | None
    lot_number: str | None
    plan: str | None
    status: JobStatus
    install_date: date | None
    queued: bool
    queued_at: date | None
    steps: dict[str, str]
    po_number: str | None
    so_number: str | None
    carter_po_number: str | None
    vendor: str | None
    so_total: Decimal | None
    notes: str | None
    updated_at: datetime | None


class PlatformUpdate(BaseModel):
    step: str | None = None            # e.g. "s2.ordSub"
    done: bool | None = None           # required when step is given
    po_number: str | None = Field(default=None, max_length=50)
    so_number: str | None = Field(default=None, max_length=50)
    carter_po_number: str | None = Field(default=None, max_length=50)
    vendor: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


def _row(job: Job, checklist: OrderingChecklist) -> PlatformRow:
    return PlatformRow(
        job_id=job.id,
        job_code=job.job_code,
        address=job.address,
        account_name=job.account.name,
        community_name=job.community.name if job.community else None,
        lot_number=job.lot_number,
        plan=job.plan,
        status=job.status,
        install_date=job.install_date,
        queued=checklist.queued,
        queued_at=checklist.queued_at,
        steps=checklist.steps or {},
        po_number=checklist.po_number,
        so_number=checklist.so_number,
        carter_po_number=checklist.carter_po_number,
        vendor=checklist.vendor or DEFAULT_VENDOR,
        so_total=checklist.so_total,
        notes=checklist.notes,
        updated_at=checklist.updated_at,
    )


@router.get("/meta", dependencies=[Depends(read_access)])
def platform_meta():
    """Stage/step definitions and trigger map, so the page renders from one source of truth."""
    return {
        "stages": [
            {"key": sk, "label": label, "steps": [{"key": k, "label": lbl} for k, lbl in steps]}
            for sk, label, steps in PLATFORM_STAGES
        ],
        "triggers": {k: s.value for k, s in STATUS_TRIGGERS},
        "default_vendor": DEFAULT_VENDOR,
    }


@router.get("/board", response_model=list[PlatformRow], dependencies=[Depends(read_access)])
def platform_board(
    account_id: int | None = None,
    community_id: int | None = None,
    include_ordered: bool = False,
    include_upcoming: bool = False,
    db: Session = Depends(get_db),
):
    """Active ordering worklist: national-builder jobs in 1.2-NdOrd → 1.5-OrdPO.
    include_ordered=true adds 2.0-Ord jobs (the Ordered view);
    include_upcoming=true adds 1.0-Track/1.1-PreOrd jobs (the Up Next list)."""
    statuses = list(WORKLIST_STATUSES) + ([JobStatus.ord] if include_ordered else [])
    if include_upcoming:
        statuses += list(UPCOMING_STATUSES)
    query = (
        db.query(Job)
        .join(Account, Job.account_id == Account.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(
            Account.type == AccountType.builder,
            or_(*[Account.name.like(f"{p}%") for p in NATIONAL_BUILDER_PREFIXES]),
            Job.status.in_(statuses),
        )
    )
    if account_id is not None:
        query = query.filter(Job.account_id == account_id)
    if community_id is not None:
        query = query.filter(Job.community_id == community_id)
    jobs = query.order_by(Job.job_code.asc().nulls_last(), Job.id).limit(500).all()

    rows = []
    for job in jobs:
        checklist = get_or_create_checklist(db, job)
        if _seed_steps(checklist, job.status):
            _rollup_stages(checklist)
        rows.append(_row(job, checklist))
    db.commit()
    return rows


def _get_job(db: Session, job_id: int) -> Job:
    job = (
        db.query(Job)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(Job.id == job_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/order-now", response_model=PlatformRow, dependencies=[Depends(write_access)])
def order_now(job_id: int, db: Session = Depends(get_db)):
    """Stage an upcoming job (1.0-Track / 1.1-PreOrd) in the ordering queue.
    The job's status doesn't change until the queue is processed."""
    job = _get_job(db, job_id)
    if job.status not in UPCOMING_STATUSES:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not an upcoming job")
    checklist = get_or_create_checklist(db, job)
    if checklist.queued:
        raise HTTPException(status_code=409, detail="Job is already in the ordering queue")
    checklist.queued = True
    checklist.queued_at = date.today()
    db.commit()
    db.refresh(checklist)
    return _row(job, checklist)


@router.post("/jobs/{job_id}/dequeue", response_model=PlatformRow, dependencies=[Depends(write_access)])
def dequeue(job_id: int, db: Session = Depends(get_db)):
    """Take a job back out of the ordering queue (before it's processed)."""
    job = _get_job(db, job_id)
    checklist = get_or_create_checklist(db, job)
    if not checklist.queued:
        raise HTTPException(status_code=409, detail="Job is not in the ordering queue")
    checklist.queued = False
    checklist.queued_at = None
    db.commit()
    db.refresh(checklist)
    return _row(job, checklist)


@router.post("/queue/process", response_model=list[PlatformRow], dependencies=[Depends(write_access)])
def process_queue(db: Session = Depends(get_db)):
    """Finalize the queue: every queued job enters the pipeline at 1.2-NdOrd,
    starting stage 1 (PO's & Selection File). Returns the processed jobs."""
    queued = (
        db.query(OrderingChecklist)
        .join(Job, OrderingChecklist.job_id == Job.id)
        .options(joinedload(OrderingChecklist.job).joinedload(Job.account),
                 joinedload(OrderingChecklist.job).joinedload(Job.community))
        .filter(OrderingChecklist.queued.is_(True))
        .all()
    )
    rows = []
    for checklist in queued:
        job = checklist.job
        if job.status in UPCOMING_STATUSES:
            checklist.prior_status = job.status.value  # so Undo can put it back
            job.status = JobStatus.ndord
        checklist.queued = False
        checklist.queued_at = None
        rows.append(_row(job, checklist))
    db.commit()
    return rows


@router.post("/jobs/{job_id}/undo-order", response_model=PlatformRow, dependencies=[Depends(write_access)])
def undo_order(job_id: int, db: Session = Depends(get_db)):
    """Undo a processed order that hasn't gone out yet: the job returns to its
    pre-queue status (Up Next) and the checklist is deleted outright, so the
    next Order Now starts a completely fresh pull (re-seeded from documents).
    Only allowed at 1.2-NdOrd — once the order is sent (1.3+), there's real
    work to lose and the status ladder should be walked back step by step."""
    job = _get_job(db, job_id)
    if job.status != JobStatus.ndord:
        raise HTTPException(
            status_code=409,
            detail=f"Job is {job.status.value}; undo is only available at 1.2-NdOrd",
        )
    checklist = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
    prior = checklist.prior_status if checklist else None
    job.status = JobStatus(prior) if prior in {s.value for s in UPCOMING_STATUSES} else JobStatus.track
    if checklist is not None:
        db.delete(checklist)  # fresh pull next time
    db.commit()
    return _row(job, get_or_create_checklist(db, job))


@router.patch("/jobs/{job_id}", response_model=PlatformRow, dependencies=[Depends(write_access)])
def platform_update(job_id: int, payload: PlatformUpdate, db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(Job.id == job_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    checklist = get_or_create_checklist(db, job)

    if payload.step is not None:
        if payload.step not in ALL_STEP_KEYS:
            raise HTTPException(status_code=422, detail=f"Unknown step '{payload.step}'")
        if payload.done is None:
            raise HTTPException(status_code=422, detail="'done' is required with 'step'")
        steps = dict(checklist.steps or {})
        if payload.done:
            steps.setdefault(payload.step, date.today().isoformat())
        else:
            steps.pop(payload.step, None)
        checklist.steps = steps
        _rollup_stages(checklist)
        _sync_status(job, checklist)

    for field in ("po_number", "so_number", "carter_po_number", "vendor", "notes"):
        value = getattr(payload, field)
        if field in payload.model_fields_set:
            setattr(checklist, field, value.strip() if isinstance(value, str) else value)

    db.commit()
    db.refresh(checklist)
    return _row(job, checklist)
