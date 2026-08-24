"""Team notes & tasks.

One entry type: a note. Give it an assignee and it becomes a task (completable,
with an optional due date). Replies are child notes. Everyone can read
everything; the default view is simply filtered to what belongs to you.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access
from app.auth.deps import get_current_user
from app.database import get_db
from app.models import NOTE_TYPES, Job, Note, NoteRead, NoteTag, User

router = APIRouter(tags=["notes"])


class NoteIn(BaseModel):
    body: str = Field(min_length=1)
    note_type: str = "fyi"
    job_id: int | None = None
    assignee_email: str | None = None
    due_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    parent_id: int | None = None


class NoteOut(BaseModel):
    id: int
    body: str
    note_type: str
    job_id: int | None
    job_code: str | None
    job_address: str | None
    author_email: str
    author_name: str | None
    assignee_email: str | None
    assignee_name: str | None
    due_date: date | None
    completed_at: datetime | None
    completed_by: str | None
    parent_id: int | None
    created_at: datetime
    tags: list[str]
    is_task: bool
    is_overdue: bool
    unread: bool
    replies: list["NoteOut"] = Field(default_factory=list)


NoteOut.model_rebuild()


def _names(db: Session) -> dict[str, str]:
    return {u.email: u.full_name for u in db.query(User).all()}


def _out(n: Note, names: dict, unread_ids: set[int], today: date) -> NoteOut:
    return NoteOut(
        id=n.id,
        body=n.body,
        note_type=n.note_type,
        job_id=n.job_id,
        job_code=n.job.job_code if n.job else None,
        job_address=n.job.address if n.job else None,
        author_email=n.author_email,
        author_name=n.author_name or names.get(n.author_email),
        assignee_email=n.assignee_email,
        assignee_name=names.get(n.assignee_email) if n.assignee_email else None,
        due_date=n.due_date,
        completed_at=n.completed_at,
        completed_by=n.completed_by,
        parent_id=n.parent_id,
        created_at=n.created_at,
        tags=[t.user_email for t in n.tags],
        is_task=bool(n.assignee_email),
        is_overdue=bool(
            n.assignee_email and n.due_date and not n.completed_at and n.due_date < today
        ),
        unread=n.id in unread_ids,
    )


def _mine(n: Note, email: str) -> bool:
    """Authored by, assigned to, or tagging this person."""
    return (
        n.author_email == email
        or n.assignee_email == email
        or any(t.user_email == email for t in n.tags)
    )


@router.get("/notes", response_model=list[NoteOut], dependencies=[Depends(read_access)])
def list_notes(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    job_id: int | None = None,
    show_done: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Top-level notes with their replies. scope=mine keeps it to yours."""
    q = (
        db.query(Note)
        .options(joinedload(Note.tags), joinedload(Note.job))
        .filter(Note.parent_id.is_(None))
    )
    if job_id is not None:
        q = q.filter(Note.job_id == job_id)
    parents = q.order_by(Note.created_at.desc()).limit(400).all()

    by_parent: dict[int, list[Note]] = {}
    if parents:
        kids = (
            db.query(Note)
            .options(joinedload(Note.tags), joinedload(Note.job))
            .filter(Note.parent_id.in_([p.id for p in parents]))
            .order_by(Note.created_at.asc())
            .all()
        )
        for k in kids:
            by_parent.setdefault(k.parent_id, []).append(k)

    # A job's own Notes section shows everything for that job; the hub filters.
    if scope == "mine" and job_id is None:
        parents = [
            p
            for p in parents
            if _mine(p, user.email) or any(_mine(k, user.email) for k in by_parent.get(p.id, []))
        ]
    if not show_done:
        # completed tasks drop off the working list; plain notes always stay
        parents = [p for p in parents if not (p.assignee_email and p.completed_at)]

    read_ids = {
        r.note_id for r in db.query(NoteRead).filter(NoteRead.user_email == user.email).all()
    }
    names, today = _names(db), date.today()

    def unread_of(n: Note) -> set[int]:
        seen = n.id in read_ids or n.author_email == user.email
        return set() if seen else {n.id}

    rows = []
    for p in parents:
        out = _out(p, names, unread_of(p), today)
        out.replies = [_out(k, names, unread_of(k), today) for k in by_parent.get(p.id, [])]
        out.unread = out.unread or any(r.unread for r in out.replies)
        rows.append(out)

    # newest first, but anything overdue or urgent floats to the top
    rows.sort(key=lambda r: r.created_at, reverse=True)
    rows.sort(key=lambda r: (r.is_overdue, r.note_type == "urgent"), reverse=True)
    return rows


@router.get("/notes/unread-count", dependencies=[Depends(read_access)])
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Badge count: things addressed to you that you have not opened."""
    read_ids = {
        r.note_id for r in db.query(NoteRead).filter(NoteRead.user_email == user.email).all()
    }
    notes = (
        db.query(Note)
        .options(joinedload(Note.tags))
        .filter(Note.author_email != user.email)
        .all()
    )
    return {"count": len([n for n in notes if _mine(n, user.email) and n.id not in read_ids])}


@router.post(
    "/notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(read_access)],
)
def create_note(
    payload: NoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if payload.note_type not in NOTE_TYPES:
        raise HTTPException(400, "Unknown note type")
    if payload.job_id is not None and db.get(Job, payload.job_id) is None:
        raise HTTPException(404, "Job not found")
    if payload.parent_id is not None and db.get(Note, payload.parent_id) is None:
        raise HTTPException(404, "Note not found")
    note = Note(
        body=payload.body.strip(),
        note_type=payload.note_type,
        job_id=payload.job_id,
        author_email=user.email,
        author_name=user.full_name,
        assignee_email=payload.assignee_email or None,
        due_date=payload.due_date,
        parent_id=payload.parent_id,
    )
    db.add(note)
    db.flush()
    for email in {e for e in payload.tags if e}:
        db.add(NoteTag(note_id=note.id, user_email=email))
    db.commit()
    db.refresh(note)
    return _out(note, _names(db), set(), date.today())


@router.post(
    "/notes/{note_id}/complete", response_model=NoteOut, dependencies=[Depends(read_access)]
)
def complete(
    note_id: int,
    done: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a task done (or reopen it). The assigner sees it as an update."""
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(404, "Note not found")
    if not note.assignee_email:
        raise HTTPException(400, "Only tasks (notes with an assignee) can be completed")
    note.completed_at = datetime.now(timezone.utc) if done else None
    note.completed_by = user.full_name if done else None
    db.commit()
    db.refresh(note)
    return _out(note, _names(db), set(), date.today())


@router.post("/notes/read", dependencies=[Depends(read_access)])
def mark_read(
    ids: list[int], db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if not ids:
        return {"marked": 0}
    have = {
        r.note_id
        for r in db.query(NoteRead)
        .filter(NoteRead.user_email == user.email, NoteRead.note_id.in_(ids))
        .all()
    }
    fresh = set(ids) - have
    for nid in fresh:
        db.add(NoteRead(note_id=nid, user_email=user.email))
    db.commit()
    return {"marked": len(fresh)}


@router.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(read_access)],
)
def delete_note(
    note_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(404, "Note not found")
    if note.author_email != user.email and user.role.value != "admin":
        raise HTTPException(403, "You can only delete your own notes")
    db.query(Note).filter(Note.parent_id == note_id).delete()
    db.query(NoteTag).filter(NoteTag.note_id == note_id).delete()
    db.query(NoteRead).filter(NoteRead.note_id == note_id).delete()
    db.delete(note)
    db.commit()
