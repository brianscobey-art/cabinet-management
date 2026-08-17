"""Autobot API: the universal visit board, the daily route plan, and the
community pins the router needs. Engine logic lives in app/autobot.py."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.auth.deps import require_roles
from app.autobot import (
    DUTIES,
    INACTIVE_JOB_STATUSES,
    NATIONAL_PREFIXES,
    TRACK_TO_BLUE_STATUSES,
    _active_house_count,
    auto_assign,
    duty_of,
    effective_coords,
    generate_visits,
    geocode_address,
    parts_state,
    phase_check_metrics,
    plan_day,
    plan_horizon,
    visit_duration_min,
    visit_label,
)
from app.database import get_db
from app.models import (
    VISIT_STATUSES,
    VISIT_TYPES,
    Community,
    DutyAssignment,
    Job,
    PhaseUpdate,
    Role,
    ServiceRequest,
    User,
    Visit,
    Worker,
    WorkerTimeOff,
)

router = APIRouter(tags=["autobot"])

# Autobot is the tech's app, but KSRs and field crews carry their own visits
# (field measures, post-walks) — they need to see and work their route. Setting
# up the roster/duty chart/time off stays with the tech and Brian (admin).
autobot_access = require_roles(
    Role.service_tech, Role.admin, Role.sales, Role.field, Role.installer_coordinator
)
# Doing the work (log a visit, mark it done, log a phase) — anyone who can see it.
autobot_do = autobot_access
# Configuring it (roster, duty chart, time off, visit generation) — tech + admin.
autobot_write = require_roles(Role.service_tech, Role.admin)


class VisitOut(BaseModel):
    id: int
    visit_type: str
    status: str
    label: str
    job_id: int | None
    job_code: str | None
    community_id: int | None
    community_name: str | None
    service_request_id: int | None
    lat: float | None
    lon: float | None
    has_location: bool
    open_date: date | None
    close_date: date | None
    scheduled_date: date | None
    priority: int
    duration_min: int
    parts_ready: bool
    parts_note: str | None
    notes: str | None
    completed_at: datetime | None
    completed_by: str | None
    assigned_to: int | None
    assignee: str | None  # display name; null = the tech's pool


class VisitIn(BaseModel):
    visit_type: str
    job_id: int | None = None
    community_id: int | None = None
    service_request_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    open_date: date | None = None
    close_date: date | None = None
    scheduled_date: date | None = None
    priority: int = 0
    duration_min: int | None = Field(default=None, ge=1)
    notes: str | None = None


class VisitPatch(BaseModel):
    status: str | None = None
    lat: float | None = None
    lon: float | None = None
    open_date: date | None = None
    close_date: date | None = None
    scheduled_date: date | None = None
    priority: int | None = None
    duration_min: int | None = Field(default=None, ge=1)
    notes: str | None = None
    assigned_to: int | None = None  # null (sent explicitly) puts it back in the tech's pool


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PlaceOut(BaseModel):
    community_id: int
    name: str
    account_name: str
    market: str | None
    lat: float | None
    lon: float | None
    active_houses: int
    last_phase_check: date | None
    phase_check_due: date | None


def _visit_query(db: Session):
    return db.query(Visit).options(
        joinedload(Visit.job).joinedload(Job.community),
        joinedload(Visit.community),
        joinedload(Visit.community).joinedload(Community.account),
        joinedload(Visit.service_request).joinedload(ServiceRequest.parts),
        joinedload(Visit.assignee),
    )


def _out(db: Session, v: Visit, today: date) -> VisitOut:
    ready, note = (True, None)
    if v.service_request:
        ready, note = parts_state(v.service_request, today)
    coords = effective_coords(v)
    houses, sweep_min = 0, None
    if v.visit_type == "phase_check" and v.community_id:
        houses, sweep_min, centroid = phase_check_metrics(db, v.community_id)
        if centroid is not None:
            coords = centroid
    po = float(v.job.po_amount) if v.job and v.job.po_amount is not None else None
    community = v.community or (v.job.community if v.job else None)
    return VisitOut(
        id=v.id,
        visit_type=v.visit_type,
        status=v.status,
        label=visit_label(v),
        job_id=v.job_id,
        job_code=v.job.job_code if v.job else None,
        community_id=community.id if community else None,
        community_name=community.name if community else None,
        service_request_id=v.service_request_id,
        lat=coords[0] if coords else None,
        lon=coords[1] if coords else None,
        has_location=coords is not None,
        open_date=v.open_date,
        close_date=v.close_date,
        scheduled_date=v.scheduled_date,
        priority=v.priority,
        duration_min=v.duration_min or sweep_min or visit_duration_min(v, po, houses),
        parts_ready=ready,
        parts_note=note,
        notes=v.notes,
        completed_at=v.completed_at,
        completed_by=v.completed_by,
        assigned_to=v.assigned_to,
        assignee=v.assignee.name if v.assignee else None,
    )


class JobLookupOut(BaseModel):
    id: int
    job_code: str | None
    address: str
    community_name: str | None


@router.get(
    "/autobot/jobs", response_model=list[JobLookupOut], dependencies=[Depends(autobot_access)]
)
def job_lookup(db: Session = Depends(get_db)):
    """Just enough of the job list for the tech to hang a visit on — the full
    office jobs API stays closed to the service_tech role."""
    from app.models import JobStatus

    jobs = (
        db.query(Job)
        .options(joinedload(Job.community))
        .filter(Job.status.notin_((JobStatus.closed, JobStatus.void)))
        .order_by(Job.job_code)
        .all()
    )
    return [
        JobLookupOut(
            id=j.id,
            job_code=j.job_code,
            address=j.address,
            community_name=j.community.name if j.community else None,
        )
        for j in jobs
    ]


@router.get("/autobot/visits", response_model=list[VisitOut], dependencies=[Depends(autobot_access)])
def list_visits(
    status_filter: str = "pending",
    visit_type: str | None = None,
    job_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = _visit_query(db)
    if status_filter and status_filter != "all":
        q = q.filter(Visit.status == status_filter)
    if visit_type:
        q = q.filter(Visit.visit_type == visit_type)
    if job_id:
        q = q.filter(Visit.job_id == job_id)
    visits = q.order_by(Visit.close_date.is_(None), Visit.close_date, Visit.id.desc()).all()
    # Closed/void jobs are archived — their still-pending visits never show
    # (the next auto-sync formally cancels them).
    from app.autobot import INACTIVE_JOB_STATUSES

    visits = [
        v for v in visits
        if not (v.status == "pending" and v.job and v.job.status in INACTIVE_JOB_STATUSES)
    ]
    today = date.today()
    return [_out(db, v, today) for v in visits]


@router.post("/autobot/visits", response_model=VisitOut, status_code=status.HTTP_201_CREATED)
def create_visit(
    payload: VisitIn, db: Session = Depends(get_db), user: User = Depends(autobot_do)
):
    if payload.visit_type not in VISIT_TYPES:
        raise HTTPException(422, f"visit_type must be one of: {', '.join(VISIT_TYPES)}")
    if payload.job_id and not db.get(Job, payload.job_id):
        raise HTTPException(404, "Job not found")
    if payload.community_id and not db.get(Community, payload.community_id):
        raise HTTPException(404, "Community not found")
    if payload.service_request_id and not db.get(ServiceRequest, payload.service_request_id):
        raise HTTPException(404, "Service request not found")
    if not payload.job_id and not payload.community_id and payload.lat is None:
        raise HTTPException(422, "Visit needs a job, a community, or its own coordinates")
    visit = Visit(**payload.model_dump(), created_by=user.full_name)
    db.add(visit)
    db.commit()
    v = _visit_query(db).filter(Visit.id == visit.id).one()
    return _out(db, v, date.today())


@router.patch("/autobot/visits/{visit_id}", response_model=VisitOut)
def patch_visit(
    visit_id: int,
    payload: VisitPatch,
    db: Session = Depends(get_db),
    user: User = Depends(autobot_do),
):
    visit = db.get(Visit, visit_id)
    if not visit:
        raise HTTPException(404, "Visit not found")
    data = payload.model_dump(exclude_unset=True)
    if "assigned_to" in data and data["assigned_to"] is not None:
        if not db.get(Worker, data["assigned_to"]):
            raise HTTPException(404, "Worker not found")
    new_status = data.pop("status", None)
    if new_status is not None:
        if new_status not in VISIT_STATUSES:
            raise HTTPException(422, f"status must be one of: {', '.join(VISIT_STATUSES)}")
        visit.status = new_status
        if new_status == "done":
            visit.completed_at = datetime.now(timezone.utc)
            visit.completed_by = user.full_name
        else:
            visit.completed_at = None
            visit.completed_by = None
    for key, value in data.items():
        setattr(visit, key, value)
    db.commit()
    v = _visit_query(db).filter(Visit.id == visit_id).one()
    return _out(db, v, date.today())


@router.post("/autobot/generate", dependencies=[Depends(autobot_write)])
def generate(db: Session = Depends(get_db), user: User = Depends(autobot_write)):
    created = generate_visits(db, date.today(), created_by=user.full_name)
    assigned = auto_assign(db)
    return {"created": created, "total": sum(created.values()), "assigned": assigned}


@router.get("/autobot/plan", dependencies=[Depends(autobot_access)])
def plan(
    day: date | None = None,
    real_drive: bool = True,
    worker_id: int | None = None,
    db: Session = Depends(get_db),
):
    return plan_day(db, day or date.today(), real_drive=real_drive, worker_id=worker_id)


@router.get("/autobot/forecast", dependencies=[Depends(autobot_access)])
def forecast(
    start: date | None = None,
    days: int = 10,
    real_drive: bool = True,
    worker_id: int | None = None,
    db: Session = Depends(get_db),
):
    """The rest of the schedule: each day's stops treated as completed so the
    following days show what's left of the backlog."""
    return plan_horizon(
        db, start or date.today(), days=min(days, 15), real_drive=real_drive, worker_id=worker_id
    )


class HouseOut(BaseModel):
    job_id: int
    job_code: str | None
    lot_number: str | None
    address: str
    plan: str | None
    phase: str | None
    phase_label: str | None
    phase_at: datetime | None
    phase_by: str | None


class PhaseLogIn(BaseModel):
    phase: str


@router.get("/autobot/communities/{community_id}/detail", dependencies=[Depends(autobot_access)])
def community_stop_detail(community_id: int, db: Session = Depends(get_db)):
    """What a stop needs in this community: every pending visit there, plus the
    active houses with their current construction phase (for phase sweeps)."""
    from sqlalchemy import func

    from app.phases import PHASE_LABELS, PHASE_TRACKED_STATUSES, PHASES

    community = db.get(Community, community_id)
    if not community:
        raise HTTPException(404, "Community not found")

    today = date.today()
    tasks = [
        _out(db, v, today)
        for v in _visit_query(db)
        .outerjoin(Job, Visit.job_id == Job.id)
        .filter(
            Visit.status == "pending",
            (Visit.community_id == community_id) | (Job.community_id == community_id),
        )
        .order_by(Visit.close_date.is_(None), Visit.close_date)
        .all()
        if not (v.job and v.job.status in INACTIVE_JOB_STATUSES)
    ]

    jobs = (
        db.query(Job)
        .filter(Job.community_id == community_id, Job.status.in_(PHASE_TRACKED_STATUSES))
        .all()
    )
    latest: dict[int, PhaseUpdate] = {}
    if jobs:
        sub = (
            db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("max_id"))
            .filter(PhaseUpdate.job_id.in_([j.id for j in jobs]))
            .group_by(PhaseUpdate.job_id)
            .subquery()
        )
        for row in db.query(PhaseUpdate).join(sub, PhaseUpdate.id == sub.c.max_id).all():
            latest[row.job_id] = row

    def lot_key(job: Job):
        lot = (job.lot_number or "").strip()
        return (0, int(lot)) if lot.isdigit() else (1, lot)

    houses = []
    for j in sorted(jobs, key=lot_key):
        cur = latest.get(j.id)
        houses.append(HouseOut(
            job_id=j.id, job_code=j.job_code, lot_number=j.lot_number, address=j.address,
            plan=j.plan,
            phase=cur.phase if cur else None,
            phase_label=PHASE_LABELS.get(cur.phase) if cur else None,
            phase_at=cur.noted_at if cur else None,
            phase_by=cur.noted_by if cur else None,
        ))
    return {
        "community": community.name,
        "phases": [{"code": c, "label": lbl} for c, lbl in PHASES],
        "tasks": tasks,
        "houses": houses,
    }


@router.post(
    "/autobot/jobs/{job_id}/phase", status_code=status.HTTP_201_CREATED
)
def log_phase(
    job_id: int,
    payload: PhaseLogIn,
    db: Session = Depends(get_db),
    user: User = Depends(autobot_do),
):
    """Log a phase from the field. Logging the SAME phase is meaningful too — it
    stamps 'verified unchanged on this date' into the history."""
    from app.phases import PHASE_CODES, PHASE_LABELS

    if not db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    if payload.phase not in PHASE_CODES:
        raise HTTPException(422, f"Unknown phase '{payload.phase}'")
    update = PhaseUpdate(
        job_id=job_id, phase=payload.phase, source="autobot", noted_by=user.full_name
    )
    db.add(update)
    db.commit()
    db.refresh(update)
    return {
        "job_id": job_id,
        "phase": update.phase,
        "phase_label": PHASE_LABELS.get(update.phase),
        "noted_by": update.noted_by,
        "noted_at": update.noted_at,
    }


@router.get("/autobot/geocode", dependencies=[Depends(autobot_access)])
def geocode(q: str):
    """Address → pin. Google when GOOGLE_MAPS_API_KEY is set, OSM otherwise."""
    found = geocode_address(q)
    if not found:
        raise HTTPException(404, "Address not found")
    return found


# ---------------------------------------------------------------- workers

class TimeOffOut(BaseModel):
    id: int
    worker_id: int
    start_date: date
    end_date: date
    note: str | None


class WorkerOut(BaseModel):
    id: int
    name: str
    is_tech: bool
    sales_match: str | None
    home_town: str | None
    lat: float | None
    lon: float | None
    radius_miles: float
    national_ok: bool
    active: bool
    off_today: bool
    time_off: list[TimeOffOut]


class WorkerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_tech: bool = False
    sales_match: str | None = Field(default=None, max_length=60)
    home_town: str | None = Field(default=None, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_miles: float = Field(default=30.0, gt=0, le=500)


class WorkerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_tech: bool | None = None
    sales_match: str | None = Field(default=None, max_length=60)
    home_town: str | None = Field(default=None, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_miles: float | None = Field(default=None, gt=0, le=500)
    national_ok: bool | None = None
    active: bool | None = None


def _worker_out(w: Worker) -> WorkerOut:
    today = date.today()
    upcoming = [t for t in w.time_off if t.end_date >= today]
    return WorkerOut(
        id=w.id, name=w.name, is_tech=w.is_tech, sales_match=w.sales_match,
        home_town=w.home_town, lat=w.lat, lon=w.lon,
        radius_miles=w.radius_miles, national_ok=w.national_ok, active=w.active,
        off_today=any(t.start_date <= today <= t.end_date for t in w.time_off),
        time_off=[TimeOffOut.model_validate(t, from_attributes=True) for t in upcoming],
    )


@router.get("/autobot/workers", response_model=list[WorkerOut], dependencies=[Depends(autobot_access)])
def list_workers(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(Worker)
    if not include_inactive:
        q = q.filter(Worker.active)
    return [_worker_out(w) for w in q.order_by(Worker.is_tech.desc(), Worker.name).all()]


@router.post(
    "/autobot/workers",
    response_model=WorkerOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(autobot_write)],
)
def create_worker(payload: WorkerIn, db: Session = Depends(get_db)):
    worker = Worker(**payload.model_dump())
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return _worker_out(worker)


@router.patch(
    "/autobot/workers/{worker_id}", response_model=WorkerOut, dependencies=[Depends(autobot_write)]
)
def patch_worker(worker_id: int, payload: WorkerPatch, db: Session = Depends(get_db)):
    worker = db.get(Worker, worker_id)
    if not worker:
        raise HTTPException(404, "Worker not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(worker, key, value)
    db.commit()
    db.refresh(worker)
    return _worker_out(worker)


# ---------------------------------------------------------------- time off

class TimeOffIn(BaseModel):
    worker_id: int
    start_date: date
    end_date: date
    note: str | None = Field(default=None, max_length=200)


@router.post(
    "/autobot/timeoff",
    response_model=TimeOffOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(autobot_write)],
)
def add_time_off(payload: TimeOffIn, db: Session = Depends(get_db)):
    if not db.get(Worker, payload.worker_id):
        raise HTTPException(404, "Worker not found")
    if payload.end_date < payload.start_date:
        raise HTTPException(422, "End date is before start date")
    row = WorkerTimeOff(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return TimeOffOut.model_validate(row, from_attributes=True)


@router.delete(
    "/autobot/timeoff/{timeoff_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(autobot_write)],
)
def delete_time_off(timeoff_id: int, db: Session = Depends(get_db)):
    row = db.get(WorkerTimeOff, timeoff_id)
    if not row:
        raise HTTPException(404, "Time off entry not found")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------- duty chart

class DutyRowOut(BaseModel):
    community_id: int
    name: str
    account_name: str
    national: bool  # national builders only take national_ok workers
    active_houses: int
    duties: dict[str, int | None | str]  # duty -> worker_id, None (explicit tech), or "rules"


class DutyCellIn(BaseModel):
    community_id: int
    duty: str
    worker_id: int | None = None  # null = explicitly the tech
    clear: bool = False           # true = drop the cell, fall back to the normal rules


@router.get("/autobot/duties", dependencies=[Depends(autobot_access)])
def duty_chart(db: Session = Depends(get_db)):
    """The chart: one row per community with jobs still tracking through
    blue-tape (1.0-Track … 4.1-Blue), one cell per duty. Missing cell =
    unassigned → the automatic rules (sold-it / territory / tech pool)."""
    cells: dict[int, dict[str, int | None]] = {}
    for d in db.query(DutyAssignment).all():
        cells.setdefault(d.community_id, {})[d.duty] = d.worker_id
    communities = (
        db.query(Community).options(joinedload(Community.account)).order_by(Community.name).all()
    )
    rows = []
    for c in communities:
        tracking = (
            db.query(Job)
            .filter(Job.community_id == c.id, Job.status.in_(TRACK_TO_BLUE_STATUSES))
            .count()
        )
        if tracking == 0:
            continue  # nothing left between tracking and blue-tape
        duties: dict[str, int | None | str] = {}
        for duty in DUTIES:
            duties[duty] = cells.get(c.id, {}).get(duty, "rules")
        rows.append(DutyRowOut(
            community_id=c.id, name=c.name, account_name=c.account.name,
            national=c.account.name.startswith(NATIONAL_PREFIXES),
            active_houses=tracking, duties=duties,
        ))
    return {"duties": list(DUTIES), "rows": rows}


@router.put("/autobot/duties", dependencies=[Depends(autobot_write)])
def set_duty(payload: DutyCellIn, db: Session = Depends(get_db)):
    """Set one chart cell, and point that community's pending visits of that
    duty at the new owner so the chart takes effect immediately."""
    if payload.duty not in DUTIES:
        raise HTTPException(422, f"duty must be one of: {', '.join(DUTIES)}")
    if not db.get(Community, payload.community_id):
        raise HTTPException(404, "Community not found")
    if payload.worker_id is not None and not db.get(Worker, payload.worker_id):
        raise HTTPException(404, "Worker not found")

    row = (
        db.query(DutyAssignment)
        .filter(DutyAssignment.community_id == payload.community_id,
                DutyAssignment.duty == payload.duty)
        .first()
    )
    if payload.clear:
        if row:
            db.delete(row)
    elif row:
        row.worker_id = payload.worker_id
    else:
        db.add(DutyAssignment(
            community_id=payload.community_id, duty=payload.duty, worker_id=payload.worker_id
        ))

    pending = (
        db.query(Visit)
        .outerjoin(Job, Visit.job_id == Job.id)
        .filter(
            Visit.status == "pending",
            (Visit.community_id == payload.community_id)
            | (Job.community_id == payload.community_id),
        )
        .all()
    )
    reassigned = 0
    for v in pending:
        if duty_of(v.visit_type) == payload.duty:
            # clear → release them so the normal rules re-place them below
            v.assigned_to = None if payload.clear else payload.worker_id
            reassigned += 1
    db.commit()
    if payload.clear:
        auto_assign(db)
    return {"ok": True, "reassigned": reassigned}


@router.get("/autobot/places", response_model=list[PlaceOut], dependencies=[Depends(autobot_access)])
def places(db: Session = Depends(get_db)):
    communities = (
        db.query(Community).options(joinedload(Community.account)).order_by(Community.name).all()
    )
    out = []
    for c in communities:
        houses = _active_house_count(db, c.id)
        last_done = (
            db.query(Visit)
            .filter(Visit.visit_type == "phase_check", Visit.community_id == c.id,
                    Visit.status == "done")
            .order_by(Visit.completed_at.desc())
            .first()
        )
        pending = (
            db.query(Visit)
            .filter(Visit.visit_type == "phase_check", Visit.community_id == c.id,
                    Visit.status == "pending")
            .first()
        )
        out.append(PlaceOut(
            community_id=c.id,
            name=c.name,
            account_name=c.account.name,
            market=c.market,
            lat=c.lat,
            lon=c.lon,
            active_houses=houses,
            last_phase_check=(
                last_done.completed_at.date() if last_done and last_done.completed_at else None
            ),
            phase_check_due=pending.close_date if pending else None,
        ))
    return out


@router.patch(
    "/autobot/communities/{community_id}/location",
    response_model=PlaceOut,
    dependencies=[Depends(autobot_write)],
)
def set_location(community_id: int, payload: LocationIn, db: Session = Depends(get_db)):
    community = db.get(Community, community_id)
    if not community:
        raise HTTPException(404, "Community not found")
    community.lat = payload.lat
    community.lon = payload.lon
    db.commit()
    return next(p for p in places(db) if p.community_id == community_id)

