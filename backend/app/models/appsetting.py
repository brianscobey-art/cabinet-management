from app.database import Base
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column


class AppSetting(Base):
    """Small key/value store for app-managed settings (e.g. the manager report
    share token) that a non-technical admin can change from the UI without env vars."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, default=None)


def get_setting(db, key: str, default: str | None = None) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row is not None else default


def set_setting(db, key: str, value: str | None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
