"""COAST suite hand-off API: the one door each app uses to write to CabinetTron.

Each hand-off answers 200 with {level, issues, status, ...} when it went in
(level ok / warn / hold) and 422 with the same shape when it was refused. Every
call, refused or not, leaves a row on the job's timeline.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.database import get_db
from app.models import Job, Role, User
from app.suite import handoff
from app.suite.access import access_map, allows, suite_access
from app.suite.schemas import (
    FieldCheckIn,
    InstallIn,
    JobSetupIn,
    OrderSentIn,
    PoBackIn,
    ScheduleIn,
    SoBackIn,
    SoldIn,
)

router = APIRouter(prefix="/suite", tags=["suite"])


@router.get("/access")
def my_access(user: User = Depends(get_current_user)) -> dict:
    """Which apps this login can open, and how far. The launcher hides the rest."""
    return {"role": user.role.value, "apps": access_map(user.role)}


@router.post("/sterling/sold")
def sterling_sold(data: SoldIn, db: Session = Depends(get_db), user: User = Depends(suite_access("sterling", "full"))):
    return handoff.sterling_sold(db, data, user)


@router.post("/optimus/order-sent")
def order_sent(data: OrderSentIn, db: Session = Depends(get_db), user: User = Depends(suite_access("optimus", "full"))):
    return handoff.optimus_order_sent(db, data, user)


@router.post("/optimus/so-back")
def so_back(data: SoBackIn, db: Session = Depends(get_db), user: User = Depends(suite_access("optimus", "full"))):
    return handoff.optimus_so_back(db, data, user)


@router.post("/optimus/po-back")
def po_back(data: PoBackIn, db: Session = Depends(get_db), user: User = Depends(suite_access("optimus", "full"))):
    return handoff.optimus_po_back(db, data, user)


@router.post("/feeds/schedule")
def feed_schedule(data: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(suite_access("cabinettron", "full"))):
    return handoff.feed_schedule(db, data, user)


@router.post("/feeds/job-setup")
def feed_job_setup(data: JobSetupIn, db: Session = Depends(get_db), user: User = Depends(suite_access("cabinettron", "full"))):
    return handoff.feed_job_setup(db, data, user)


@router.post("/autobot/field-check")
def field_check(data: FieldCheckIn, db: Session = Depends(get_db), user: User = Depends(suite_access("autobot", "full"))):
    # Field and inspectors finish field checks. A service tech ("own") logs service visits only.
    return handoff.autobot_field_check(db, data, user)


@router.post("/tailgate/install")
def install(data: InstallIn, db: Session = Depends(get_db), user: User = Depends(suite_access("tailgate", "own"))):
    # "own" lets installers in; handoff refuses a job that isn't theirs.
    if not allows(user.role, "tailgate", "full") and user.role is not Role.installer:
        raise HTTPException(status_code=403, detail=f"Your role ({user.role.value}) has view access to tailgate only")
    return handoff.tailgate_install(db, data, user)


@router.get("/tailgate/my-installs")
def my_installs(db: Session = Depends(get_db), user: User = Depends(suite_access("tailgate", "own"))):
    q = db.query(Job).filter(Job.install_date.isnot(None))
    if not allows(user.role, "tailgate", "view"):
        names = {(user.full_name or "").strip().lower(), (user.email or "").strip().lower()}
        jobs = [j for j in q.all() if (j.installer or "").strip().lower() in names]
    else:
        jobs = q.all()
    return [
        {"job_code": j.job_code, "address": j.address, "install_date": j.install_date.isoformat(),
         "status": j.status.value, "installer": j.installer}
        for j in sorted(jobs, key=lambda j: j.install_date)
    ]


@router.get("/jobs/{job_code}/timeline")
def job_timeline(job_code: str, db: Session = Depends(get_db), user: User = Depends(suite_access("cabinettron", "view"))):
    job = handoff.job_by_code(db, job_code)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_code}")
    return {
        "job_code": job.job_code,
        "status": job.status.value,
        "open_holds": [{"code": h.hold_code, "source": h.source, "issues": h.issues or []} for h in handoff.open_holds(db, job)],
        "events": handoff.timeline(db, job),
    }


@router.get("/unmatched")
def unmatched(db: Session = Depends(get_db), user: User = Depends(suite_access("cabinettron", "view"))):
    """Refused hand-offs and feed rows still waiting on a job, newest first."""
    return handoff.unmatched(db)
