"""Field-measure verification: completion date, correct/incorrect/super-notified
toggles (each stamped with who + when), and dated issue notes.

The phase board shows just the checkboxes; the stamps and notes surface on the
job detail page and the phase board's Field Measure Notes section.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import read_access
from app.auth.deps import require_roles
from app.database import get_db
from app.models import FieldMeasure, FieldMeasureNote, Job, Role, User

router = APIRouter(tags=["field-measure"])

# Field people verify measures from the field — same write set as phase logging.
fm_write = require_roles(Role.sales, Role.field, Role.installer_coordinator, Role.admin)


class FMNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    body: str
    author: str | None
    created_at: datetime


class FieldMeasureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    complete_date: date | None = None
    correct: bool = False
    correct_by: str | None = None
    correct_at: datetime | None = None
    incorrect: bool = False
    incorrect_by: str | None = None
    incorrect_at: datetime | None = None
    super_notified: bool = False
    super_notified_by: str | None = None
    super_notified_at: datetime | None = None


class FieldMeasureDetail(FieldMeasureOut):
    notes: list[FMNoteOut] = []


class FieldMeasureUpdate(BaseModel):
    complete_date: date | None = None
    correct: bool | None = None
    incorrect: bool | None = None
    super_notified: bool | None = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def get_or_create(db: Session, job_id: int) -> FieldMeasure:
    fm = db.query(FieldMeasure).filter(FieldMeasure.job_id == job_id).first()
    if fm is None:
        fm = FieldMeasure(job_id=job_id)
        db.add(fm)
        db.flush()
    return fm


def _notes(db: Session, job_id: int) -> list[FieldMeasureNote]:
    return (
        db.query(FieldMeasureNote)
        .filter(FieldMeasureNote.job_id == job_id)
        .order_by(FieldMeasureNote.created_at.desc())
        .all()
    )


@router.get("/jobs/{job_id}/field-measure", response_model=FieldMeasureDetail,
            dependencies=[Depends(read_access)])
def get_field_measure(job_id: int, db: Session = Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    fm = db.query(FieldMeasure).filter(FieldMeasure.job_id == job_id).first()
    detail = FieldMeasureDetail.model_validate(fm) if fm else FieldMeasureDetail()
    detail.notes = [FMNoteOut.model_validate(n) for n in _notes(db, job_id)]
    return detail


@router.patch("/jobs/{job_id}/field-measure", response_model=FieldMeasureOut)
def update_field_measure(
    job_id: int, payload: FieldMeasureUpdate,
    db: Session = Depends(get_db), user: User = Depends(fm_write),
):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    fm = get_or_create(db, job_id)
    now = datetime.now(timezone.utc)
    data = payload.model_dump(exclude_unset=True)

    if "complete_date" in data:
        fm.complete_date = data["complete_date"]

    # correct / incorrect are mutually exclusive; each toggle stamps who + when
    def stamp(flag: str, value: bool):
        setattr(fm, flag, value)
        setattr(fm, f"{flag}_by", user.full_name if value else None)
        setattr(fm, f"{flag}_at", now if value else None)

    if data.get("correct") is not None:
        stamp("correct", data["correct"])
        if data["correct"]:
            stamp("incorrect", False)
    if data.get("incorrect") is not None:
        stamp("incorrect", data["incorrect"])
        if data["incorrect"]:
            stamp("correct", False)
    if data.get("super_notified") is not None:
        stamp("super_notified", data["super_notified"])

    db.commit()
    db.refresh(fm)
    return fm


@router.post("/jobs/{job_id}/field-measure/notes", response_model=FMNoteOut,
             status_code=status.HTTP_201_CREATED)
def add_field_measure_note(
    job_id: int, payload: NoteIn,
    db: Session = Depends(get_db), user: User = Depends(fm_write),
):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    note = FieldMeasureNote(job_id=job_id, body=payload.body.strip(), author=user.full_name)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note
