"""Installer and post-walk reports read from Smartsheet (Brian 10/30/26).

Both sheets are filled in on phones in the field; CabinetTron only reads them
(app.field_reports). Each row is keyed by its Smartsheet row id so a re-read
updates rather than duplicates.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InstallReport(Base):
    """The installer's sign-off ("Install Reports" sheet): done or not, what's
    still needed, damage / parts."""

    __tablename__ = "install_reports"

    row_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True, default=None)
    job_code: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    install_date: Mapped[date | None] = mapped_column(Date, default=None)
    installer: Mapped[str | None] = mapped_column(String(120), default=None)
    complete: Mapped[bool | None] = mapped_column(Boolean, default=None)
    trade_stopping: Mapped[bool | None] = mapped_column(Boolean, default=None)
    needed_to_finish: Mapped[str | None] = mapped_column(Text, default=None)
    shoe_sticks: Mapped[float | None] = mapped_column(Float, default=None)
    damage_parts: Mapped[bool | None] = mapped_column(Boolean, default=None)
    damage_detail: Mapped[str | None] = mapped_column(Text, default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Set once the report's automatic actions (phase / post-walk clock / parts)
    # have run, so an edited row in Smartsheet never fires them twice.
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    actions: Mapped[str | None] = mapped_column(String(300), default=None)


class QcReport(Base):
    """The old post-walk form ("TBS Quality Control v2", 4/13-9/29/26), kept as
    each house's post-walk history. The answers are stored as JSON."""

    __tablename__ = "qc_reports"

    row_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True, default=None)
    job_code: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    pwid: Mapped[str | None] = mapped_column(String(20), default=None)
    walked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    walked_by: Mapped[str | None] = mapped_column(String(255), default=None)
    result: Mapped[str | None] = mapped_column(String(20), default=None)  # ok / issues
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    answers: Mapped[str | None] = mapped_column(Text, default=None)  # JSON {question: answer}
    visit_id: Mapped[int | None] = mapped_column(Integer, default=None)  # the done post_walk it became
