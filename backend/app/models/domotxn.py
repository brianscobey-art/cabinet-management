from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DomoTxn(Base):
    """One dated Domo cost/sales transaction line, keyed to a job by G/I code.

    Populated by the browser transaction pull (KB Job Txns*.json). The dates let
    the Domo P&L report slice by window / quarter / half / YTD / year-over-year.
    Product vs C9009 labor vs other labor is derived from code_type + sku at query
    time; account_name/job_code are denormalised at import for fast grouping.
    """

    __tablename__ = "domo_txns"

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_date: Mapped[date | None] = mapped_column(Date, index=True, default=None)
    job_field: Mapped[str | None] = mapped_column(String(80), default=None)  # raw Domo "job" value
    code_type: Mapped[str | None] = mapped_column(String(1), index=True, default=None)  # "G" | "I"
    code_prefix: Mapped[str | None] = mapped_column(String(40), index=True, default=None)  # before ":"
    sku: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    sales: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    # denormalised job attribution (None if the code didn't match a job)
    job_id: Mapped[int | None] = mapped_column(index=True, default=None)
    job_code: Mapped[str | None] = mapped_column(String(50), default=None)
    account_name: Mapped[str | None] = mapped_column(String(120), index=True, default=None)
    community_name: Mapped[str | None] = mapped_column(String(120), default=None)
    source_file: Mapped[str | None] = mapped_column(String(255), default=None)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
