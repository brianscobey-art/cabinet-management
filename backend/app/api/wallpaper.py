"""Keyed read-only feed for Brian's LiveDesktop wallpaper.

No JWT: the wallpaper's refresh script is headless, so access is a static key
(override via WALLPAPER_FEED_KEY env var). Data returned is low-sensitivity
(this week's install schedule) and read-only.
"""

import os
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Job, JobStatus

router = APIRouter(prefix="/wallpaper", tags=["wallpaper"])

FEED_KEY = os.getenv("WALLPAPER_FEED_KEY", "ckb-wall-4e19c7d2a6")


@router.get("/installs")
def wallpaper_installs(key: str = Query(...), db: Session = Depends(get_db)):
    """This week's installs (Sunday..Saturday containing today)."""
    if key != FEED_KEY:
        raise HTTPException(status_code=403, detail="bad key")
    today = date.today()
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    end = start + timedelta(days=6)
    rows = (
        db.query(Job)
        .options(joinedload(Job.community))
        .filter(Job.install_date >= start, Job.install_date <= end,
                Job.status != JobStatus.void)
        .order_by(Job.install_date)
        .all()
    )
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "installs": [
            {
                "date": j.install_date.isoformat(),
                "job": j.job_code or "",
                "community": j.community.name if j.community else "",
                "lot": j.lot_number or "",
            }
            for j in rows
        ],
    }
