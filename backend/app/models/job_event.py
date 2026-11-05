"""Job timeline: one row per hand-off between the COAST apps.

Every app (Sterling, Optimus, Autobot, Tailgate, the builder feeds) writes to the
job record through `app.suite.handoff`, and every one of those writes leaves a
row here: who sent it, from which app, what it did, and what the double checks
found. A row with level "hold" that is not resolved holds the job from its next
step (for example a field-measure discrepancy holds ordering).
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

EVENT_LEVELS = ("ok", "warn", "hold", "reject")
EVENT_SOURCES = ("cabinettron", "sterling", "optimus", "autobot", "tailgate", "feed")


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Null only for a rejected hand-off that never resolved to a job.
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, default=None)
    job_code: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    source: Mapped[str] = mapped_column(String(20), index=True)  # EVENT_SOURCES
    kind: Mapped[str] = mapped_column(String(40), index=True)  # sold, so_back, po_back, ...
    level: Mapped[str] = mapped_column(String(10), default="ok", index=True)  # EVENT_LEVELS
    # Plain-English lines from the double checks, one per finding.
    issues: Mapped[list | None] = mapped_column(JSON, default=None)
    # The hold's short code ("measure_discrepancy", "so_total_mismatch") so a later
    # clean hand-off of the same kind can resolve it.
    hold_code: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    status_from: Mapped[str | None] = mapped_column(String(20), default=None)
    status_to: Mapped[str | None] = mapped_column(String(20), default=None)
    payload: Mapped[dict | None] = mapped_column(JSON, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    actor: Mapped[str | None] = mapped_column(String(255), default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolved_by_event: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    job: Mapped["Job | None"] = relationship()  # noqa: F821
