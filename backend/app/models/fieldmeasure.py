from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FieldMeasure(Base):
    """Field-measure verification state for a job (one per job).

    The "red" field measure date lives on Job.measure_date; this record holds the
    completion date and the correct / incorrect / super-notified toggles, each
    stamped with who set it and when, so the job page can show the audit trail
    even though the phase board only shows the checkbox.
    """

    __tablename__ = "field_measures"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
    complete_date: Mapped[date | None] = mapped_column(Date, default=None)

    correct: Mapped[bool] = mapped_column(Boolean, default=False)
    correct_by: Mapped[str | None] = mapped_column(String(255), default=None)
    correct_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    incorrect: Mapped[bool] = mapped_column(Boolean, default=False)
    incorrect_by: Mapped[str | None] = mapped_column(String(255), default=None)
    incorrect_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    super_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    super_notified_by: Mapped[str | None] = mapped_column(String(255), default=None)
    super_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    job: Mapped["Job"] = relationship()  # noqa: F821


class FieldMeasureNote(Base):
    """An issue note logged during field-measure verification — dated + attributed."""

    __tablename__ = "field_measure_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255), default=None)  # full name of who saved it
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
