"""Account Code Match (Brian 11/24/26): DOMO's job accounts, the Job Setup
Requests log, and one flag row per job/field problem. See app.account_codes."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DomoAccount(Base):
    """One DOMO job account ("G7510082-016: SUZANNE VICKERS ... - CAB SVCC3160").
    Replaced whole each time the Job Account feed is read; the I-Account Detail
    email adds accounts the Job Account card hasn't listed yet."""

    __tablename__ = "domo_accounts"

    account: Mapped[str] = mapped_column(String(40), primary_key=True)  # G7510082-016 (prefix kept)
    kind: Mapped[str] = mapped_column(String(1))  # "I" or "G"
    customer: Mapped[str | None] = mapped_column(String(200), default=None)
    name: Mapped[str | None] = mapped_column(String(200), default=None)  # "CAB SVCC3160"
    cab_code: Mapped[str | None] = mapped_column(String(80), index=True, default=None)  # "SVCC3160"
    linked_g: Mapped[str | None] = mapped_column(String(40), default=None)  # I-account's final-bill G
    source: Mapped[str] = mapped_column(String(40))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobSetupRequest(Base):
    """A row of "Received Job Setup Requests.xlsx" (Job Setups sheet)."""

    __tablename__ = "job_setup_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_date: Mapped[date | None] = mapped_column(Date, default=None)
    ashley_code: Mapped[str | None] = mapped_column(String(80), default=None)  # "CAB TRAN1506"
    g_account: Mapped[str | None] = mapped_column(String(40), default=None)
    i_account: Mapped[str | None] = mapped_column(String(40), default=None)
    g_limit: Mapped[str | None] = mapped_column(String(20), default=None)
    i_limit: Mapped[str | None] = mapped_column(String(20), default=None)
    request_no: Mapped[str | None] = mapped_column(String(20), default=None)
    customer_name: Mapped[str | None] = mapped_column(String(200), default=None)
    tracker_job_code: Mapped[str | None] = mapped_column(String(50), default=None)


class AccountCodeFlag(Base):
    """One problem with a job's stored I- or G-code against DOMO. Open until a
    run finds the job matching DOMO (Fixed), or someone marks it Ignored."""

    __tablename__ = "account_code_flags"
    __table_args__ = (UniqueConstraint("job_code", "field", "flag", name="uq_account_code_flag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True, default=None)
    job_code: Mapped[str] = mapped_column(String(50), index=True)
    field: Mapped[str] = mapped_column(String(1))  # "I", "G", or "-" (no setup request)
    flag: Mapped[str] = mapped_column(String(40))
    stored_code: Mapped[str | None] = mapped_column(String(40), default=None)
    domo_code: Mapped[str | None] = mapped_column(String(40), default=None)  # suggested fix
    domo_name: Mapped[str | None] = mapped_column(String(300), default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | fixed | ignored
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolved_by: Mapped[str | None] = mapped_column(String(255), default=None)
    times_seen: Mapped[int] = mapped_column(Integer, default=1)
