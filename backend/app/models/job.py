import enum
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobType(str, enum.Enum):
    tract = "tract"        # production builder (DRH, Century, Jubilee...)
    custom = "custom"      # custom new construction
    remodel = "remodel"    # retail remodel


class JobStatus(str, enum.Enum):
    """Workflow stage — mirrors the lifecycle in the spec (§1)."""

    quote = "quote"
    field_measure = "field_measure"
    ordered = "ordered"
    delivery = "delivery"
    install = "install"
    quality = "quality"
    punch = "punch"
    warranty = "warranty"
    closed = "closed"


class Job(Base):
    """The central record everything hangs off."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Derived unique key used across the tracker, sold-job folders, and supplier POs
    # (e.g. DRLICR-0113 for DR Horton, WEL-0318 for locals).
    job_code: Mapped[str | None] = mapped_column(String(50), unique=True, index=True, default=None)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    community_id: Mapped[int | None] = mapped_column(
        ForeignKey("communities.id"), index=True, default=None  # nullable for retail
    )
    lot_number: Mapped[str | None] = mapped_column(String(32), default=None)
    address: Mapped[str] = mapped_column(String(500))
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, native_enum=False, length=16))
    plan: Mapped[str | None] = mapped_column(String(100), default=None)  # house plan, e.g. "DRH1 Madison STD"
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32), default=JobStatus.quote, index=True
    )
    install_date: Mapped[date | None] = mapped_column(Date, default=None)
    warranty_start_date: Mapped[date | None] = mapped_column(Date, default=None)

    # Two contacts, set at creation (spec §4): sales = billing, field = measure/install issues.
    sales_contact_name: Mapped[str] = mapped_column(String(255))
    sales_contact_phone: Mapped[str | None] = mapped_column(String(50), default=None)
    sales_contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    field_contact_name: Mapped[str] = mapped_column(String(255))
    field_contact_phone: Mapped[str | None] = mapped_column(String(50), default=None)
    field_contact_email: Mapped[str | None] = mapped_column(String(255), default=None)

    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    account: Mapped["Account"] = relationship(back_populates="jobs")  # noqa: F821
    community: Mapped["Community | None"] = relationship(back_populates="jobs")  # noqa: F821
    room_selections: Mapped[list["RoomSelection"]] = relationship(  # noqa: F821
        back_populates="job", cascade="all, delete-orphan", order_by="RoomSelection.id"
    )
    hardware_selections: Mapped[list["HardwareSelection"]] = relationship(  # noqa: F821
        back_populates="job", cascade="all, delete-orphan", order_by="HardwareSelection.id"
    )
