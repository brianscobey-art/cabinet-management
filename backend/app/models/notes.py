from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# The dropdown Brian picked. "blocker" = work is stopped waiting on something.
NOTE_TYPES = ("urgent", "action", "fyi", "question", "blocker")
NOTE_TYPE_LABELS = {
    "urgent": "Urgent",
    "action": "Action Needed",
    "fyi": "FYI",
    "question": "Question",
    "blocker": "Blocker",
}


class Note(Base):
    """A team note. Assign someone and it becomes a task (completable, with an
    optional due date). Replies are Notes with parent_id set."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    note_type: Mapped[str] = mapped_column(String(16), default="fyi")

    # Optional link to a house — makes it show in that job's Notes section too.
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, default=None)

    author_email: Mapped[str] = mapped_column(String(255), index=True)
    author_name: Mapped[str | None] = mapped_column(String(255), default=None)

    # Set => it's a task for this person.
    assignee_email: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_by: Mapped[str | None] = mapped_column(String(255), default=None)

    # Threaded replies hang off their parent.
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("notes.id"), index=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=lambda: datetime.now(timezone.utc)
    )

    job: Mapped["Job | None"] = relationship()  # noqa: F821
    tags: Mapped[list["NoteTag"]] = relationship(cascade="all, delete-orphan")


class NoteTag(Base):
    """Someone tagged on a note (an FYI recipient — not the assignee)."""

    __tablename__ = "note_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    user_email: Mapped[str] = mapped_column(String(255), index=True)


class NoteRead(Base):
    """Per-user read receipt — drives the unread badge."""

    __tablename__ = "note_reads"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    user_email: Mapped[str] = mapped_column(String(255), index=True)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


Index("ix_note_reads_user_note", NoteRead.user_email, NoteRead.note_id, unique=True)
Index("ix_note_tags_user_note", NoteTag.user_email, NoteTag.note_id, unique=True)
