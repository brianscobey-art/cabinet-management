from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OrderingChecklist(Base):
    """National-builder ordering pipeline — mirrors Brian's 4-step process:

    1. PO's and Selection File Creation
    2. Orders and Layouts
    3. SO's and Order Comparison
    4. POs Attached
    """

    __tablename__ = "ordering_checklists"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)

    stage1_done: Mapped[bool] = mapped_column(Boolean, default=False)  # PO + selection file
    stage2_done: Mapped[bool] = mapped_column(Boolean, default=False)  # order + layout
    stage3_done: Mapped[bool] = mapped_column(Boolean, default=False)  # SO comparison
    stage4_done: Mapped[bool] = mapped_column(Boolean, default=False)  # POs attached

    stage1_date: Mapped[date | None] = mapped_column(Date, default=None)
    stage2_date: Mapped[date | None] = mapped_column(Date, default=None)
    stage3_date: Mapped[date | None] = mapped_column(Date, default=None)
    stage4_date: Mapped[date | None] = mapped_column(Date, default=None)

    # Fine-grained sub-steps for the Ordering Platform page: {"s1.poRecv": "2026-07-20", ...}
    # Key = stage.step, value = ISO date the step was checked. stageN_done stays the
    # coarse rollup (all of stage N's steps checked) so the classic board keeps working.
    steps: Mapped[dict] = mapped_column(JSON, default=dict)

    # Ordering queue: Order Now stages a job here; processing the queue moves the
    # batch into the pipeline at 1.2-NdOrd and clears the flag.
    queued: Mapped[bool] = mapped_column(Boolean, default=False)
    queued_at: Mapped[date | None] = mapped_column(Date, default=None)
    # Status the job had before the queue was processed — lets Undo put it back.
    prior_status: Mapped[str | None] = mapped_column(String(20), default=None)

    # Reference numbers captured along the way (builder PO, Everluxe SO, Carter PO).
    po_number: Mapped[str | None] = mapped_column(String(50), default=None)
    so_number: Mapped[str | None] = mapped_column(String(50), default=None)
    carter_po_number: Mapped[str | None] = mapped_column(String(50), default=None)
    vendor: Mapped[str | None] = mapped_column(String(100), default=None)  # None = Everluxe default

    notes: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
