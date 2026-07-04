import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Supplier(str, enum.Enum):
    everluxe = "everluxe"
    legacy = "legacy"
    hardware = "hardware"


class ConfirmationStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    rejected = "rejected"


class ShipStatus(str, enum.Enum):
    not_shipped = "not_shipped"
    scheduled = "scheduled"
    shipped = "shipped"
    delivered = "delivered"


class Order(Base):
    """A supplier order generated from an accepted quote."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    supplier: Mapped[Supplier] = mapped_column(Enum(Supplier, native_enum=False, length=16))
    po_number: Mapped[str | None] = mapped_column(String(100), default=None)
    confirmation_status: Mapped[ConfirmationStatus] = mapped_column(
        Enum(ConfirmationStatus, native_enum=False, length=16), default=ConfirmationStatus.pending
    )
    ship_status: Mapped[ShipStatus] = mapped_column(
        Enum(ShipStatus, native_enum=False, length=16), default=ShipStatus.not_shipped
    )
    file_path: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
    quote: Mapped["Quote"] = relationship()  # noqa: F821
