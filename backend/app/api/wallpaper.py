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


@router.get("/upcoming")
def wallpaper_upcoming(key: str = Query(...), db: Session = Depends(get_db)):
    """Upcoming installs, today through +30 days (active jobs only)."""
    if key != FEED_KEY:
        raise HTTPException(status_code=403, detail="bad key")
    today = date.today()
    rows = (
        db.query(Job)
        .options(joinedload(Job.community))
        .filter(Job.install_date >= today,
                Job.install_date <= today + timedelta(days=30),
                Job.status.notin_((JobStatus.void, JobStatus.closed)))
        .order_by(Job.install_date)
        .all()
    )
    return {
        "installs": [
            {
                "date": j.install_date.isoformat(),
                "job": j.job_code or "",
                "community": j.community.name if j.community else "",
                "lot": j.lot_number or "",
                "plan": j.plan or "",
                "status": j.status.value if j.status else "",
            }
            for j in rows
        ],
    }


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


# Pre-2.0 ordering pipeline: everything Brian still has to push over the line.
# The four ordering stages (1.2-1.5) are the actionable worklist; 1.0/1.1 are
# counted for context but not listed, since dozens of jobs sit in Track for weeks.
PIPELINE_STAGES = [
    JobStatus.track, JobStatus.preord, JobStatus.ndord,
    JobStatus.ordprcss, JobStatus.ordsub, JobStatus.ordpo,
]
ACTIONABLE = [JobStatus.ndord, JobStatus.ordprcss, JobStatus.ordsub, JobStatus.ordpo]


@router.get("/pipeline")
def wallpaper_pipeline(key: str = Query(...), db: Session = Depends(get_db)):
    """Orders not yet at 2.0-Ord, so the desktop can nag about unfinished ones."""
    if key != FEED_KEY:
        raise HTTPException(status_code=403, detail="bad key")
    rows = (
        db.query(Job)
        .options(joinedload(Job.community))
        .filter(Job.status.in_(PIPELINE_STAGES))
        .order_by(Job.status, Job.job_code)
        .all()
    )
    counts = {}
    for j in rows:
        counts[j.status.value] = counts.get(j.status.value, 0) + 1
    today = date.today()

    def age(j):
        d = (j.updated_at.date() if j.updated_at else None) or (
            j.created_at.date() if j.created_at else None)
        return (today - d).days if d else None

    return {
        "counts": [{"status": s.value, "n": counts.get(s.value, 0)} for s in PIPELINE_STAGES],
        "total": len(rows),
        "actionable": sum(counts.get(s.value, 0) for s in ACTIONABLE),
        "jobs": [
            {
                "job": j.job_code or "",
                "community": j.community.name if j.community else "",
                "lot": j.lot_number or "",
                "status": j.status.value,
                "days": age(j),
            }
            for j in rows if j.status in ACTIONABLE
        ],
    }
