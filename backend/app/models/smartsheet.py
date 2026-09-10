from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SmartsheetRow(Base):
    """The current state of one Tract Builder Management house.

    The whole row is kept as JSON rather than spread over columns: the sheets
    carry ~250 columns each, the two builders do not agree on which of them
    exist, and columns get added by whoever owns the sheet. Pinning a schema to
    that would break on somebody else's edit. The few fields we join and filter
    on are lifted out alongside it.
    """

    __tablename__ = "smartsheet_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    sheet: Mapped[str] = mapped_column(String(64), index=True)   # builder name
    sheet_id: Mapped[str | None] = mapped_column(String(32), default=None)
    row_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # Normalised join key -- see app.smartsheet.match.
    key_sub: Mapped[str] = mapped_column(String(120), default="")
    key_lot: Mapped[str] = mapped_column(String(40), default="")
    subdivision: Mapped[str | None] = mapped_column(String(160), default=None)
    lot: Mapped[str | None] = mapped_column(String(40), default=None)
    has_cabinets: Mapped[bool] = mapped_column(default=False, index=True)
    data: Mapped[str] = mapped_column(Text)                      # the row, as JSON
    pulled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_smartsheet_rows_key", "key_sub", "key_lot"),)


class SmartsheetHistory(Base):
    """One row per field per value, with the window it held that value.

    Brian asked to keep daily history so the report can say "this has been
    blank for 24 days" rather than only "this is blank today" -- staleness is
    the actual evidence about whether Smartsheet is maintained. Storing a span
    (first_seen..last_seen) instead of a row per field per day keeps a year of
    ~3,000 houses to something small: an unchanged field costs one date update,
    not 365 rows.
    """

    __tablename__ = "smartsheet_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_sub: Mapped[str] = mapped_column(String(120))
    key_lot: Mapped[str] = mapped_column(String(40))
    field: Mapped[str] = mapped_column(String(120))
    value: Mapped[str | None] = mapped_column(Text, default=None)  # None = blank
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    days_held: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_smartsheet_history_key", "key_sub", "key_lot", "field"),
    )
