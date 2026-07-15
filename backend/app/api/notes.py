from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import read_access
from app.auth.deps import get_current_user
from app.database import get_db
from app.models import Job, JobNote, User

router = APIRouter(tags=["notes"])


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    body: str
    author: str | None
    created_at: datetime


@router.get("/jobs/{job_id}/notes", response_model=list[NoteOut], dependencies=[Depends(read_access)])
def list_notes(job_id: int, db: Session = Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    # newest first — the UI shows the latest note directly under the entry line
    return db.query(JobNote).filter(JobNote.job_id == job_id).order_by(JobNote.id.desc()).all()


@router.post("/jobs/{job_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def add_note(
    job_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # any signed-in user can leave a note
):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    note = JobNote(job_id=job_id, body=payload.body.strip(), author=user.full_name)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note
