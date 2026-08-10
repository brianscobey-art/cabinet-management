"""Autobot workers: who can be sent to a visit.

One is the service tech (the default truck every route plans for). The rest are
area helpers — office/sales people with a home base and a coverage radius who
pick up work near them (Brian in Chipley, Alex in Freeport) or on jobs they
sold (Paula measures and post-walks her own local sales).
"""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    is_tech: Mapped[bool] = mapped_column(Boolean, default=False)  # the default truck
    # Matches the start of job.salesperson — sold-it-so-you-walk-it rule (local accounts).
    sales_match: Mapped[str | None] = mapped_column(String(60), default=None)
    # Full street address or just a town — whatever pins their driveway best.
    home_town: Mapped[str | None] = mapped_column(String(120), default=None)
    lat: Mapped[float | None] = mapped_column(Float, default=None)
    lon: Mapped[float | None] = mapped_column(Float, default=None)
    radius_miles: Mapped[float] = mapped_column(Float, default=30.0)  # territory rule reach
    # Works national accounts? Local-only people (Laurie, Paula) never get
    # DR Horton / Century work from the territory rule.
    national_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    time_off: Mapped[list["WorkerTimeOff"]] = relationship(
        back_populates="worker", cascade="all, delete-orphan", order_by="WorkerTimeOff.start_date"
    )


class WorkerTimeOff(Base):
    """Vacation / unavailability. The router plans nothing for someone who's off,
    and hard deadlines assigned to them get rescued onto the truck for those days.
    """

    __tablename__ = "worker_time_off"

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), default=None)

    worker: Mapped["Worker"] = relationship(back_populates="time_off")


class DutyAssignment(Base):
    """The duty chart: per community, per task, who owns it. Beats the radius
    rule — this is how national-account territories are really split. A row with
    worker_id NULL means 'explicitly the tech' (skip the radius rule too);
    no row at all means 'fall back to the normal rules'.
    """

    __tablename__ = "duty_assignments"
    __table_args__ = (UniqueConstraint("community_id", "duty", name="uq_duty_community_task"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(
        ForeignKey("communities.id", ondelete="CASCADE"), index=True
    )
    duty: Mapped[str] = mapped_column(String(30))  # field_measure, post_walk, punch_out, blue_tape, phase_check, service
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"), default=None
    )

    community: Mapped["Community"] = relationship()  # noqa: F821
    worker: Mapped["Worker | None"] = relationship()
