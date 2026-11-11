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
    sent_at: datetime | None = None
    sent_by: str | None = None
    sent_to: str | None = None


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


@router.delete("/jobs/{job_id}/field-measure/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field_measure_note(
    job_id: int, note_id: int,
    db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin)),
):
    """Remove a field-measure note (admin only) — e.g. duplicates from a button
    pressed several times."""
    note = db.get(FieldMeasureNote, note_id)
    if note is None or note.job_id != job_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    db.delete(note)
    db.commit()


# --- Reports > Field Measure Notes: compile + send to Alex (Brian 11/11/26) ---

class FMNoteReportRow(BaseModel):
    id: int
    job_id: int
    job_code: str | None
    account_name: str | None
    community_name: str | None
    lot_number: str | None
    address: str
    plan: str | None
    body: str
    author: str | None
    created_at: datetime
    sent_at: datetime | None
    sent_by: str | None
    sent_to: str | None


class MarkSentIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    to: str | None = Field(default=None, max_length=255)
    sent: bool = True  # False clears the stamp (sent by mistake)


@router.get("/reports/field-measure-notes", response_model=list[FMNoteReportRow],
            dependencies=[Depends(read_access)])
def field_measure_notes_report(include_sent: bool = False, db: Session = Depends(get_db)):
    """Every field-measure note on an active house, newest house activity
    first; sent notes only when asked for."""
    from sqlalchemy.orm import joinedload

    from app.models import JobStatus

    q = (
        db.query(FieldMeasureNote)
        .join(Job, FieldMeasureNote.job_id == Job.id)
        .options(joinedload(FieldMeasureNote.job).joinedload(Job.account),
                 joinedload(FieldMeasureNote.job).joinedload(Job.community))
        .filter(Job.status.notin_((JobStatus.closed, JobStatus.void)))
    )
    if not include_sent:
        q = q.filter(FieldMeasureNote.sent_at.is_(None))
    out = []
    for n in q.order_by(FieldMeasureNote.created_at.desc()).all():
        j = n.job
        out.append(FMNoteReportRow(
            id=n.id, job_id=j.id, job_code=j.job_code,
            account_name=j.account.name if j.account else None,
            community_name=j.community.name if j.community else None,
            lot_number=j.lot_number, address=j.address, plan=j.plan,
            body=n.body, author=n.author, created_at=n.created_at,
            sent_at=n.sent_at, sent_by=n.sent_by, sent_to=n.sent_to,
        ))
    return out


@router.post("/field-measure-notes/mark-sent", response_model=list[FMNoteOut])
def mark_field_measure_notes_sent(
    payload: MarkSentIn, db: Session = Depends(get_db), user: User = Depends(fm_write),
):
    """Stamp the checked notes as sent (who, when, to whom) -- or clear it."""
    notes = db.query(FieldMeasureNote).filter(FieldMeasureNote.id.in_(payload.ids)).all()
    if len(notes) != len(set(payload.ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    now = datetime.now(timezone.utc)
    for n in notes:
        n.sent_at = now if payload.sent else None
        n.sent_by = user.full_name if payload.sent else None
        n.sent_to = (payload.to or "").strip() or None if payload.sent else None
    db.commit()
    return notes
