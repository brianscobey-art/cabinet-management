from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import read_access
from app.auth.deps import require_roles
from app.database import get_db
from app.models import (
    FieldMeasure, FieldMeasureNote, Job, JobDocument, JobStatus, OrderingChecklist,
    PhaseUpdate, Role, User,
)
from app.phases import PHASE_CODES, PHASE_HIDDEN_STATUSES, PHASE_LABELS, PHASES

router = APIRouter(tags=["phases"])

# Field people log phases from the community — wider write access than sales data.
phase_write = require_roles(Role.sales, Role.field, Role.installer_coordinator, Role.admin)


class PhaseDef(BaseModel):
    code: str
    label: str


class PhaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    phase: str
    source: str
    noted_by: str | None
    noted_at: datetime


class PhaseSet(BaseModel):
    phase: str


class FMNote(BaseModel):
    body: str
    author: str | None
    created_at: datetime


class PhaseBoardRow(BaseModel):
    job_id: int
    job_code: str | None
    lot_number: str | None
    address: str
    plan: str | None
    status: JobStatus
    phase: str | None
    phase_label: str | None
    phase_date: datetime | None
    measure_date: date | None  # the "red" field measure date
    layout_doc_id: int | None  # the job's field layout PDF, if attached
    ordering_stages: list[bool]  # the 4-step ordering pipeline, in order
    # field-measure verification (checkbox state only; stamps live on the job page)
    fm_complete_date: date | None
    fm_correct: bool
    fm_incorrect: bool
    fm_super_notified: bool
    fm_notes: list[FMNote]


@router.get("/phases", response_model=list[PhaseDef], dependencies=[Depends(read_access)])
def phase_definitions():
    return [PhaseDef(code=c, label=lbl) for c, lbl in PHASES]


@router.get("/phase-board", response_model=list[PhaseBoardRow], dependencies=[Depends(read_access)])
def phase_board(community_id: int, include_closed: bool = False, db: Session = Depends(get_db)):
    """Active houses in a community with each one's current phase."""
    query = db.query(Job).filter(Job.community_id == community_id)
    if not include_closed:
        # phase tracking stops at punch — hide punch and everything after it
        query = query.filter(Job.status.notin_(PHASE_HIDDEN_STATUSES))
    jobs = query.all()

    latest: dict[int, PhaseUpdate] = {}
    checklists: dict[int, OrderingChecklist] = {}
    measures: dict[int, FieldMeasure] = {}
    fm_notes: dict[int, list[FieldMeasureNote]] = {}
    if jobs:
        job_ids = [j.id for j in jobs]
        sub = (
            db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("max_id"))
            .filter(PhaseUpdate.job_id.in_(job_ids))
            .group_by(PhaseUpdate.job_id)
            .subquery()
        )
        for row in db.query(PhaseUpdate).join(sub, PhaseUpdate.id == sub.c.max_id).all():
            latest[row.job_id] = row
        for cl in db.query(OrderingChecklist).filter(OrderingChecklist.job_id.in_(job_ids)).all():
            checklists[cl.job_id] = cl
        for fm in db.query(FieldMeasure).filter(FieldMeasure.job_id.in_(job_ids)).all():
            measures[fm.job_id] = fm
        for n in (
            db.query(FieldMeasureNote)
            .filter(FieldMeasureNote.job_id.in_(job_ids))
            .order_by(FieldMeasureNote.created_at.desc())
            .all()
        ):
            fm_notes.setdefault(n.job_id, []).append(n)

    layouts: dict[int, int] = {}
    if jobs:
        for doc in (
            db.query(JobDocument)
            .filter(JobDocument.job_id.in_([j.id for j in jobs]), JobDocument.doc_type == "layout")
            .order_by(JobDocument.id.desc())
            .all()
        ):
            layouts[doc.job_id] = doc.id  # newest layout wins

    def lot_key(job: Job):
        lot = (job.lot_number or "").strip()
        return (0, int(lot)) if lot.isdigit() else (1, lot)

    rows = []
    for job in sorted(jobs, key=lot_key):
        current = latest.get(job.id)
        cl = checklists.get(job.id)
        fm = measures.get(job.id)
        rows.append(
            PhaseBoardRow(
                job_id=job.id,
                job_code=job.job_code,
                lot_number=job.lot_number,
                address=job.address,
                plan=job.plan,
                status=job.status,
                phase=current.phase if current else None,
                phase_label=PHASE_LABELS.get(current.phase) if current else None,
                phase_date=current.noted_at if current else None,
                measure_date=job.measure_date,
                layout_doc_id=layouts.get(job.id),
                ordering_stages=[
                    bool(cl and getattr(cl, f"stage{i}_done")) for i in (1, 2, 3, 4)
                ],
                fm_complete_date=fm.complete_date if fm else None,
                fm_correct=bool(fm and fm.correct),
                fm_incorrect=bool(fm and fm.incorrect),
                fm_super_notified=bool(fm and fm.super_notified),
                fm_notes=[
                    FMNote(body=n.body, author=n.author, created_at=n.created_at)
                    for n in fm_notes.get(job.id, [])
                ],
            )
        )
    return rows


@router.post("/jobs/{job_id}/phase", response_model=PhaseOut, status_code=status.HTTP_201_CREATED)
def set_phase(
    job_id: int,
    payload: PhaseSet,
    db: Session = Depends(get_db),
    user: User = Depends(phase_write),
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if payload.phase not in PHASE_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown phase '{payload.phase}'",
        )
    update = PhaseUpdate(job_id=job_id, phase=payload.phase, source="manual", noted_by=user.full_name)
    db.add(update)
    db.commit()
    db.refresh(update)
    return update


@router.get("/jobs/{job_id}/phases", response_model=list[PhaseOut], dependencies=[Depends(read_access)])
def phase_history(job_id: int, db: Session = Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return (
        db.query(PhaseUpdate)
        .filter(PhaseUpdate.job_id == job_id)
        .order_by(PhaseUpdate.id.desc())
        .all()
    )
