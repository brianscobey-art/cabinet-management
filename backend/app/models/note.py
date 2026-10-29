from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# What a job note is about -- the dropdown on the job page (Brian 10/29/26).
JOB_NOTE_TOPICS = ["Sales", "Delivery", "Installation", "Service", "Warranty", "Misc"]


class JobNote(Base):
    """A free-text note on a job — append-only running log, attributed and dated."""

    __tablename__ = "job_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(20), default=None)  # JOB_NOTE_TOPICS
    author: Mapped[str | None] = mapped_column(String(255), default=None)  # full name of who saved it
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
