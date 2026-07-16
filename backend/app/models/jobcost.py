from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobCost(Base):
    """Actual costs pulled from Domo for a house, keyed to a job via G/I code.

    P&L per house = product side (G-code) + labor side (I-code). Labor billed
    on codes other than C9009 is captured in other_labor_codes for review.
    """

    __tablename__ = "job_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)

    revenue: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    product_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    labor_revenue: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    labor_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    # net P&L (billed − cost) of real non-C9009 cabinet labor; folded into margin
    other_labor_net: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    # net of the overhead/rebill wash codes (C9091, C9002) parked on this job —
    # shown for transparency but excluded from the cabinet margin
    wash_labor_net: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    margin: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    # labor billed on codes != C9009, e.g. "C9091: -$4,736.12; C9005: $1,577.78"
    other_labor_codes: Mapped[str | None] = mapped_column(Text, default=None)
    source_file: Mapped[str | None] = mapped_column(String(255), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
