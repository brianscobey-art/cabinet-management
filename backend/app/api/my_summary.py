"""My Stuff > Summary reports (Brian 10/29/26)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import read_access
from app.auth.deps import get_current_user
from app.database import get_db
from app.models import User
from app.my_summary import summary
from app.sales import KSR_ROSTER, canonical_ksr

router = APIRouter(tags=["my stuff"])


@router.get("/my/summary", dependencies=[Depends(read_access)])
def my_summary(
    ksr: str | None = None,
    days: int = Query(30, ge=0, le=3650),  # received-items window; 0 = everything
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One KSR's received items, upcoming installs and upcoming service.
    Defaults to the signed-in person when they're on the KSR roster."""
    pick = canonical_ksr(ksr) if ksr else (user.full_name if user.full_name in KSR_ROSTER else KSR_ROSTER[0])
    return {**summary(db, pick, days or None), "roster": KSR_ROSTER}
