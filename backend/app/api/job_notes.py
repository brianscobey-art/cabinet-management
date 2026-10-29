"""Job notes: the append-only running log on each job page.

These routes lived in api/notes.py until the My Stuff team-notes rewrite
(8/24/26) replaced that file and dropped them -- the job page could neither
load nor save notes after that. Restored 10/29/26, with a topic per note
(Brian: Sales, Delivery, Installation, Service, Warranty, Misc).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import read_access
from app.auth.deps import get_current_user
from app.database import get_db
from app.models import Job, JobNote, User
from app.models.note import JOB_NOTE_TOPICS

router = APIRouter(tags=["job notes"])


class JobNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    topic: str = "Misc"

    @field_validator("topic")
    @classmethod
    def _valid_topic(cls, v):
        if v not in JOB_NOTE_TOPICS:
            raise ValueError(f"topic must be one of {JOB_NOTE_TOPICS}")
        return v


class JobNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    body: str
    topic: str | None
    author: str | None
    created_at: datetime


def _job_or_404(db: Session, job_id: int) -> None:
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")


@router.get("/jobs/{job_id}/notes", response_model=list[JobNoteOut], dependencies=[Depends(read_access)])
def list_job_notes(job_id: int, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    # newest first -- the UI shows the latest note directly under the entry line
    return db.query(JobNote).filter(JobNote.job_id == job_id).order_by(JobNote.id.desc()).all()


@router.post("/jobs/{job_id}/notes", response_model=JobNoteOut, status_code=status.HTTP_201_CREATED)
def add_job_note(
    job_id: int,
    payload: JobNoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # any signed-in user can leave a note
):
    _job_or_404(db, job_id)
    note = JobNote(job_id=job_id, body=payload.body.strip(), topic=payload.topic, author=user.full_name)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note
