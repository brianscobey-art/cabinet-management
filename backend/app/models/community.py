from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Community(Base):
    """A builder's subdivision. Used for phase forecasting and job grouping."""

    __tablename__ = "communities"
    __table_args__ = (UniqueConstraint("account_id", "name", name="uq_community_account_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    market: Mapped[str | None] = mapped_column(String(255), default=None)  # e.g. "Santa Rosa Beach FL"
    # Community pin for Autobot routing — every lot inherits this unless the visit has its own.
    lat: Mapped[float | None] = mapped_column(Float, default=None)
    lon: Mapped[float | None] = mapped_column(Float, default=None)
    # Autobot-only hold: nothing schedules here and pending visits stay parked,
    # while the jobs themselves are untouched in CabinetTron (Clear Lake Estates,
    # POs being voided, 10/29/26).
    autobot_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    account: Mapped["Account"] = relationship(back_populates="communities")  # noqa: F821
    jobs: Mapped[list["Job"]] = relationship(back_populates="community")  # noqa: F821
