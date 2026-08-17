from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActivityLog(Base):
    """Who did what, when. One row per state-changing request (and each sign-in),
    so an admin can answer 'who changed this job / who deleted that?' after the fact."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=lambda: datetime.now(timezone.utc)
    )
    user_email: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    user_name: Mapped[str | None] = mapped_column(String(255), default=None)
    role: Mapped[str | None] = mapped_column(String(32), default=None)
    action: Mapped[str] = mapped_column(String(160))          # plain-English summary
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    entity: Mapped[str | None] = mapped_column(String(60), index=True, default=None)  # job, quote…
    entity_id: Mapped[str | None] = mapped_column(String(40), default=None)
    status_code: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(60), default=None)


Index("ix_activity_at_user", ActivityLog.at, ActivityLog.user_email)
