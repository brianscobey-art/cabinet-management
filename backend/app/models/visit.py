"""Autobot: the universal visit record.

Every field visit — measures, post-walks, punch, blue-tape, phase checks,
service and warranty trips — is one row here. The route engine (app/autobot.py)
reads pending visits and builds the tech's daily loop out of the Dothan shop.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Flat visit-type vocabulary (strings, not a native enum, so new types are a
# constant away). Durations and routing rules per type live in app/autobot.py.
VISIT_TYPES = (
    "field_measure",    # hard window: open = measure date, may slip 1 day late, never early
    "post_walk",        # hard 48h clock from install completion
    "punch_out",        # flexible, a few weeks after install
    "blue_tape",        # homeowner walk — flexible but urgent before closing
    "phase_check",      # recurring community sweep, every 10 days
    "service_t1",       # ad-hoc service, small fix
    "service_t2",
    "service_t3",
    "warranty_t1",      # known fix, single visit, parts ordered up front
    "warranty_t2_eval",     # diagnose + write up + order parts
    "warranty_t2_complete", # completion once parts are confirmed
)

VISIT_STATUSES = ("pending", "done", "canceled")


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_type: Mapped[str] = mapped_column(String(30), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, default=None)
    # phase checks (and anything community-wide) hang off the community instead of a job
    community_id: Mapped[int | None] = mapped_column(
        ForeignKey("communities.id"), index=True, default=None
    )
    # service/warranty visits link to the request that carries their parts list
    service_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_requests.id"), index=True, default=None
    )
    # Who's doing it. Null = the service tech's pool (the default truck).
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id"), index=True, default=None
    )

    # Own coordinates win; falls back to the community pin at plan time.
    lat: Mapped[float | None] = mapped_column(Float, default=None)
    lon: Mapped[float | None] = mapped_column(Float, default=None)

    open_date: Mapped[date | None] = mapped_column(Date, default=None)   # earliest it can happen
    close_date: Mapped[date | None] = mapped_column(Date, default=None)  # deadline it must happen by
    priority: Mapped[int] = mapped_column(Integer, default=0)  # higher = sooner in backfill
    duration_min: Mapped[int | None] = mapped_column(Integer, default=None)  # manual override
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    scheduled_date: Mapped[date | None] = mapped_column(Date, default=None)  # pin to a specific day

    notes: Mapped[str | None] = mapped_column(Text, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_by: Mapped[str | None] = mapped_column(String(255), default=None)
    created_by: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    job: Mapped["Job | None"] = relationship()  # noqa: F821
    community: Mapped["Community | None"] = relationship()  # noqa: F821
    service_request: Mapped["ServiceRequest | None"] = relationship()  # noqa: F821
    assignee: Mapped["Worker | None"] = relationship()  # noqa: F821
