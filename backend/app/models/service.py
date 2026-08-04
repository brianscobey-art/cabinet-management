from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ServiceRequest(Base):
    """A service/warranty visit for a job: a parts list plus the labor to perform,
    each labor line pointing at the part it needs. Printed for the tech in the morning.
    """

    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(200), default=None)
    # Installed | Warranty | Service Empty | Service Occupied
    status: Mapped[str] = mapped_column(String(20), default="Installed")
    material_status: Mapped[str | None] = mapped_column(String(30), default=None)  # Not Ordered | Ordered | Received
    scheduled_date: Mapped[date | None] = mapped_column(Date, default=None)  # scheduled completion
    created_by: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    parts: Mapped[list["ServicePart"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="ServicePart.id"
    )
    lines: Mapped[list["ServiceLine"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="ServiceLine.id"
    )
    job: Mapped["Job"] = relationship()  # noqa: F821


class ServicePart(Base):
    """A part the tech needs (e.g. part 'Door' for cabinet 'W3636', qty 1)."""

    __tablename__ = "service_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_request_id: Mapped[int] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), index=True
    )
    part: Mapped[str] = mapped_column(String(200))          # e.g. "L-Door"
    cabinet: Mapped[str | None] = mapped_column(String(100), default=None)  # e.g. "W3636"
    style: Mapped[str | None] = mapped_column(String(100), default=None)
    color: Mapped[str | None] = mapped_column(String(100), default=None)
    vendor: Mapped[str | None] = mapped_column(String(120), default=None)
    order_number: Mapped[str | None] = mapped_column(String(60), default=None)
    order_date: Mapped[date | None] = mapped_column(Date, default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(String(300), default=None)

    request: Mapped["ServiceRequest"] = relationship(back_populates="parts")


class ServiceLine(Base):
    """A labor instruction, optionally tied to a part above.

    e.g. part_id -> (L-Door / W3636), instruction "Replace L-door on W3636 left of window".
    """

    __tablename__ = "service_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_request_id: Mapped[int] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), index=True
    )
    part_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_parts.id", ondelete="SET NULL"), default=None
    )
    instruction: Mapped[str] = mapped_column(Text)
    # filled in by the service tech working the report
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_by: Mapped[str | None] = mapped_column(String(255), default=None)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    request: Mapped["ServiceRequest"] = relationship(back_populates="lines")
    part: Mapped["ServicePart | None"] = relationship()
