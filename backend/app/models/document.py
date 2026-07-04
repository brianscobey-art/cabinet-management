from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobDocument(Base):
    """A file attached to a job — layouts, POs, sales orders, selections, etc.

    Local deployment stores an absolute path (OneDrive folders); when we move to
    object storage (spec §3) this becomes a blob URL and nothing else changes.
    """

    __tablename__ = "job_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(32), default="document")  # layout/order/po/sales_order/selections/summary/document
    file_path: Mapped[str] = mapped_column(String(1000))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    job: Mapped["Job"] = relationship()  # noqa: F821
