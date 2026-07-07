from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PhaseUpdate(Base):
    """One row per phase change — the latest row is the house's current phase,
    and the history preserves when each phase was reached (spec §4)."""

    __tablename__ = "phase_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    phase: Mapped[str] = mapped_column(String(8))  # code from app.phases (0..12, 4.1..4.5)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | voice (later)
    noted_by: Mapped[str | None] = mapped_column(String(255), default=None)
    noted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
