import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobType(str, enum.Enum):
    tract = "tract"        # production builder (DRH, Century, Jubilee...)
    custom = "custom"      # custom new construction
    remodel = "remodel"    # retail remodel


class JobStatus(str, enum.Enum):
    """Brian's 16-stage job status ladder (order matters — it's the dropdown order)."""

    track = "1.0-Track"
    preord = "1.1-PreOrd"
    ndord = "1.2-NdOrd"
    ordprcss = "1.3-Ord Prcss"
    ordsub = "1.4-OrdSub"
    ordpo = "1.5-OrdPO"
    ord = "2.0-Ord"
    inst = "2.1-Inst"
    ndqw = "3.0-Nd QW"
    parts = "3.1-Parts"
    punch = "4.0-Punch"
    blue = "4.1-Blue"
    epo = "5.0-EPO"
    closed = "6.0-Clsd"
    war = "7.0-War"
    void = "8.0-Void"  # cancelled/voided job — archived, never on active views


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
        Enum(JobStatus, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e]),
        default=JobStatus.track,
        index=True,
    )
    measure_date: Mapped[date | None] = mapped_column(Date, default=None)  # field measure
    install_date: Mapped[date | None] = mapped_column(Date, default=None)
    warranty_start_date: Mapped[date | None] = mapped_column(Date, default=None)

    # Two contacts, set at creation (spec §4): sales = billing, field = measure/install issues.
    sales_contact_name: Mapped[str] = mapped_column(String(255))
    sales_contact_phone: Mapped[str | None] = mapped_column(String(50), default=None)
    sales_contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    field_contact_name: Mapped[str] = mapped_column(String(255))
    field_contact_phone: Mapped[str | None] = mapped_column(String(50), default=None)
    field_contact_email: Mapped[str | None] = mapped_column(String(255), default=None)

    salesperson: Mapped[str | None] = mapped_column(String(120), default=None)  # rep (Brian = mgr, excluded)
    g_code: Mapped[str | None] = mapped_column(String(40), default=None)  # Domo goods/product job code
    i_code: Mapped[str | None] = mapped_column(String(40), default=None)  # Domo install/labor job code

    # PO & pricing (imported from the tracker / builder reports)
    builder_po: Mapped[str | None] = mapped_column(String(50), default=None)  # builder's PO to us
    po_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)  # revenue
    cabinet_po: Mapped[str | None] = mapped_column(String(50), default=None)  # our PO to the supplier
    materials_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    margin_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), default=None)
    po_status: Mapped[str | None] = mapped_column(String(32), default=None)
    # builder-paid detail from the DRH Combined report (used as revenue in the P&L)
    po_check_number: Mapped[str | None] = mapped_column(String(40), default=None)
    po_paid_date: Mapped[date | None] = mapped_column(Date, default=None)  # PO Status Date when paid

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
