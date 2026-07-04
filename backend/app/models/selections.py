from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RoomSelection(Base):
    """One row per room/zone — kitchen perimeter and island can differ, so each is its own row.

    This is the record someone pulls up two years later to answer
    "what door style went in the master bath?"
    """

    __tablename__ = "room_selections"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    room: Mapped[str] = mapped_column(String(100))              # Kitchen, Master Bath...
    zone: Mapped[str | None] = mapped_column(String(100), default=None)  # Perimeter, Island...
    cabinet_brand: Mapped[str | None] = mapped_column(String(100), default=None)
    series: Mapped[str | None] = mapped_column(String(100), default=None)
    door_style: Mapped[str | None] = mapped_column(String(100), default=None)
    finish: Mapped[str | None] = mapped_column(String(100), default=None)
    wood_species: Mapped[str | None] = mapped_column(String(100), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    job: Mapped["Job"] = relationship(back_populates="room_selections")  # noqa: F821


class HardwareSelection(Base):
    """Hardware tracked separately from cabinets — different vendors."""

    __tablename__ = "hardware_selections"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    room: Mapped[str | None] = mapped_column(String(100), default=None)
    vendor: Mapped[str | None] = mapped_column(String(100), default=None)
    item: Mapped[str] = mapped_column(String(255))
    qty: Mapped[int] = mapped_column(Integer, default=1)

    job: Mapped["Job"] = relationship(back_populates="hardware_selections")  # noqa: F821
