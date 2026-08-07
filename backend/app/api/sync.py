from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.database import get_db
from app.feeds import sync_all, sync_tracker
from app.models import Role

router = APIRouter(tags=["sync"])


@router.post("/sync/feeds", dependencies=[Depends(require_roles(Role.admin, Role.sales))])
def run_feed_sync(db: Session = Depends(get_db)):
    """Manually pull the latest tracker + Vendor Suite + Century reports into the app."""
    return sync_all(db)


@router.post("/sync/tracker", dependencies=[Depends(require_roles(Role.admin, Role.sales))])
def run_tracker_sync(db: Session = Depends(get_db)):
    """Sync jobs from the newest 3.0 Online Sales Tracker only (status + install dates)."""
    return sync_tracker(db)
