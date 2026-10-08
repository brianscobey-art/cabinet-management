from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LayoutPrint(Base):
    """One stamped layout that went to the printer for a field measure.

    The Field Measures report prints only layouts that are NEW: never printed
    for that house, or printed from an older template version. This row is
    what makes that judgement, so it records exactly which source and which
    version went out, and whether it was a first print or a reprint.
    """

    __tablename__ = "layout_prints"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    batch_id: Mapped[str] = mapped_column(String(32), index=True)  # one print run
    source: Mapped[str] = mapped_column(String(16))  # "template" | "job_doc"
    source_name: Mapped[str] = mapped_column(String(400))  # template path or document name
    source_version: Mapped[str] = mapped_column(String(32))  # date in the name, else mtime
    reprint: Mapped[bool] = mapped_column(Boolean, default=False)
    # Field-measure state captured on the stamp at print time.
    measured_date: Mapped[date | None] = mapped_column(Date, default=None)
    printed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    printed_by: Mapped[str | None] = mapped_column(String(255), default=None)

    job: Mapped["Job"] = relationship()  # noqa: F821
