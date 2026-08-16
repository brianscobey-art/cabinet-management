from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
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

    # ---- Order Pack (private mode inside Optimus) --------------------------
    # Physical reality of the job's folder in "Sold Jobs\New Orders", reported by
    # the on-prem agent, plus the numbers the four stages produce. These columns
    # replace "New Orders Status.xlsx" — they live here, not in a parallel table,
    # so Optimus's rollup and the 1.2->2.0 status sync keep working off one record.
    buid: Mapped[str | None] = mapped_column(String(9), default=None, index=True)
    plan_abbr: Mapped[str | None] = mapped_column(String(20), default=None)
    elevation: Mapped[str | None] = mapped_column(String(10), default=None)
    swing: Mapped[str | None] = mapped_column(String(20), default=None)
    sub_number: Mapped[str | None] = mapped_column(String(10), default=None)

    folder_name: Mapped[str | None] = mapped_column(String(200), default=None)
    # Where the folder physically sits right now: stage1..stage4, century, sold,
    # missing. The agent's scan owns this column — it is the job's real status.
    current_folder: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    selections_file: Mapped[str | None] = mapped_column(String(200), default=None)
    po_file: Mapped[str | None] = mapped_column(String(200), default=None)
    summary_file: Mapped[str | None] = mapped_column(String(200), default=None)
    # Full inventory of the folder as last seen: ["...ORDER 081326.pdf", ...]
    folder_files: Mapped[list | None] = mapped_column(JSON, default=None)

    po_date: Mapped[date | None] = mapped_column(Date, default=None)
    po_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    so_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)

    moved_to_sold_date: Mapped[date | None] = mapped_column(Date, default=None)
    installer_pay_sheet: Mapped[bool | None] = mapped_column(Boolean, default=None)
    # Never invented: unreadable pay sheet leaves this null and writes a note.
    install_pay: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)

    # Set by the agent when a job needs Brian (total mismatch, missing SO,
    # unreadable pay sheet, BUID not in VendorSuite). Null = clean.
    exception: Mapped[str | None] = mapped_column(Text, default=None)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    job: Mapped["Job"] = relationship()  # noqa: F821
