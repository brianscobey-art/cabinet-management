from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Text
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

    notes: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
