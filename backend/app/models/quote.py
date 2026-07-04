import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.pricing import DEALER_MULTIPLIER


class QuoteStatus(str, enum.Enum):
    draft = "draft"
    accepted = "accepted"


class Quote(Base):
    """A pricing scenario for a job (Option A / Option B). One per job may be accepted."""

    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))  # "Option A"
    status: Mapped[QuoteStatus] = mapped_column(
        Enum(QuoteStatus, native_enum=False, length=16), default=QuoteStatus.draft
    )
    # Snapshot of the multiplier at creation so old quotes stay honest if the rate changes.
    multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=DEALER_MULTIPLIER)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
    lines: Mapped[list["QuoteLineItem"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="QuoteLineItem.id"
    )


class QuoteLineItem(Base):
    __tablename__ = "quote_line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    room: Mapped[str | None] = mapped_column(String(100), default=None)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    sku: Mapped[str] = mapped_column(String(100))
    product_code: Mapped[str | None] = mapped_column(String(100), default=None)
    fin_end: Mapped[str | None] = mapped_column(String(50), default=None)
    color: Mapped[str | None] = mapped_column(String(100), default=None)
    list_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    quote: Mapped["Quote"] = relationship(back_populates="lines")
