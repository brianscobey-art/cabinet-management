from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String
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


class DomoPo(Base):
    """One of our POs as DOMO's "Purchase Order Details" (O00059) has it, rolled
    up from its lines: which job account it was bought for, open/closed, and its
    latest receipt. Replaced by each nightly pull (app.domo_pos, 10/29/26)."""

    __tablename__ = "domo_pos"

    our_po: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True, default=None)
    job_account: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # I7510029-304
    job_name: Mapped[str | None] = mapped_column(String(120), default=None)  # CAB CESF 24
    customer: Mapped[str | None] = mapped_column(String(200), default=None)
    vendor: Mapped[str | None] = mapped_column(String(160), default=None)
    product: Mapped[str | None] = mapped_column(String(200), default=None)
    order_date: Mapped[date | None] = mapped_column(Date, default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)  # DOMO request date
    status: Mapped[str | None] = mapped_column(String(20), default=None)  # Open / Closed
    close_date: Mapped[date | None] = mapped_column(Date, default=None)
    ordered_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    received_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    last_receipt_date: Mapped[date | None] = mapped_column(Date, default=None)
    last_receipt_number: Mapped[str | None] = mapped_column(String(40), default=None)
    sales_order: Mapped[str | None] = mapped_column(String(40), default=None)
    salesperson: Mapped[str | None] = mapped_column(String(120), default=None)
    pos: Mapped[str | None] = mapped_column(String(80), default=None)
    lines: Mapped[int | None] = mapped_column(Integer, default=None)


class PoLineItem(Base):
    """One line of a PO as DOMO's PO drill-down card (584540536) has it (Brian
    11/24/26): a "header" row per PO (Spec Description "-", the PO's ordered
    cost) and an "item" row per item received (item code, qty, whole-dollar
    received cost). DOMO gives no line number; the logical key is po_number +
    item_code + qty_received + received_cost, and every pull replaces all rows
    of the POs it brought back (app.po_lines)."""

    __tablename__ = "po_line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(40), index=True)  # = DomoPo.our_po / Order Number
    line_type: Mapped[str] = mapped_column(String(10))  # header | item
    transaction_date: Mapped[date | None] = mapped_column(Date, default=None)
    supplier_id: Mapped[str | None] = mapped_column(String(20), default=None)
    supplier_name: Mapped[str | None] = mapped_column(String(160), default=None)
    vendor_alias: Mapped[str | None] = mapped_column(String(80), default=None)  # Hype Mill -> Hoodsly
    carter_sku: Mapped[str | None] = mapped_column(String(200), default=None)  # "C2283: CABINETS KITCHEN CRAFT ..."
    item_code: Mapped[str | None] = mapped_column(String(200), default=None)  # Spec Description; None on header
    qty_ordered: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    ordered_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    qty_received: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    received_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    account: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # I7550228-004 (prefix kept)
    account_name: Mapped[str | None] = mapped_column(String(200), default=None)
    cab_job_code: Mapped[str | None] = mapped_column(String(60), index=True, default=None)  # text after "CAB "
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True, default=None)
    salesperson: Mapped[str | None] = mapped_column(String(120), default=None)
    pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class IAccountLine(Base):
    """One line of DOMO's "Installed Sales | I-Account Detail" card (the daily
    "CabinetTron feed - I-Account Detail" email): what is posted to a house's
    I-account by SKU, and the G-account it final-bills to. Replaced whole on
    each import."""

    __tablename__ = "i_account_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    g_account: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # G7510029-635
    i_account: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # I7510029-176
    i_account_name: Mapped[str | None] = mapped_column(String(200), default=None)
    sku: Mapped[str | None] = mapped_column(String(200), default=None)
    status: Mapped[str | None] = mapped_column(String(20), default=None)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    sales: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
