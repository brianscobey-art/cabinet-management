from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.database import get_db
from app.feeds import sync_all
from app.models import Role

router = APIRouter(tags=["sync"])


@router.post("/sync/feeds", dependencies=[Depends(require_roles(Role.admin, Role.sales))])
def run_feed_sync(db: Session = Depends(get_db)):
    """Manually pull the latest Vendor Suite + Century reports into the app."""
    return sync_all(db)
