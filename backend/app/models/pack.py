from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# What a run asks the on-prem agent to do.
#   scan     — walk the four stage folders (+ Century) and report what's there
#   stage1..4 — execute that stage's playbook for the selected jobs
RUN_KINDS = ("scan", "stage1", "stage2", "stage3", "stage4")
RUN_STATUSES = ("queued", "running", "done", "failed", "cancelled")


class PackRun(Base):
    """One Order Pack command: queued by the page, claimed and executed by the
    agent on Brian's PC, and kept afterwards as the audit trail of what ran."""

    __tablename__ = "pack_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="scan")   # RUN_KINDS
    stage: Mapped[int | None] = mapped_column(Integer, default=None)  # 1..4, null for a scan
    job_ids: Mapped[list | None] = mapped_column(JSON, default=None)  # jobs in this batch
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)

    requested_by: Mapped[str | None] = mapped_column(String(255), default=None)  # user email
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    log: Mapped[str | None] = mapped_column(Text, default=None)      # streamed agent output
    result: Mapped[dict | None] = mapped_column(JSON, default=None)  # per-job outcome
    error: Mapped[str | None] = mapped_column(Text, default=None)    # null unless failed
