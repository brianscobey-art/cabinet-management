from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PoReceipt(Base):
    """A DOMO 'PO Receipt List' row — a product delivery received at a warehouse
    (POS, e.g. '750: Dothan'). Joined to a job via order_number = POTracker 'Our PO #'."""

    __tablename__ = "po_receipts"

    receipt_number: Mapped[str] = mapped_column(String(40), primary_key=True)
    receipt_date: Mapped[date | None] = mapped_column(Date, default=None)
    pos: Mapped[str | None] = mapped_column(String(80), default=None)  # store, e.g. "750: Dothan"
    supplier: Mapped[str | None] = mapped_column(String(120), default=None)
    supplier_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    landed_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    order_number: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # = Our PO #


class JobPo(Base):
    """One PO line from the tracker's POTracker table — maps 'Our PO #' to a job,
    so DOMO receipts (keyed by Our PO #) can be attributed to the right house."""

    __tablename__ = "job_pos"

    id: Mapped[int] = mapped_column(primary_key=True)
    our_po: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    job_code: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    vendor: Mapped[str | None] = mapped_column(String(120), default=None)
    product: Mapped[str | None] = mapped_column(String(200), default=None)
    order_date: Mapped[date | None] = mapped_column(Date, default=None)
    tent_due_date: Mapped[date | None] = mapped_column(Date, default=None)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)


Index("ix_job_pos_our_po_job", JobPo.our_po, JobPo.job_code)
