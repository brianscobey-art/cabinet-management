"""Autobot — service tech scheduling & routing engine.

Builds the tech's daily loop out of the Dothan shop from pending Visit rows:
lock the hard anchors (due field measures, expiring 48-hour post-walks), route
them, pull forward phase checks that are going stale if he's already nearby,
then backfill remaining capacity with flexible work. See COAST/Autobot brief.

Drive times come from OSRM (public server, free) when asked for real drive
times; otherwise straight-line distance with a road factor. Any OSRM failure
falls back silently — the plan always builds.
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import (
    Community,
    DutyAssignment,
    Job,
    JobStatus,
    ServiceRequest,
    Visit,
    Worker,
    WorkerTimeOff,
)

# ---------------------------------------------------------------- durations

BASE_DURATION_MIN: dict[str, int] = {
    "field_measure": 20,
    "post_walk": 30,
    "punch_out": 60,
    "blue_tape": 30,
    "phase_check": 2,  # per active house — scaled below
    "service_t1": 60,
    "service_t2": 120,
    "service_t3": 180,
    "warranty_t1": 60,
    "warranty_t2_eval": 45,
    "warranty_t2_complete": 90,
}

# Cabinet-work visits scale off the PO amount (a $4k kitchen runs ~2x a $2k one).
PO_SCALED_TYPES = {"field_measure", "post_walk", "punch_out", "blue_tape"}
REFERENCE_PO = 2500.0  # PO amount that equals the standard time
PO_SCALE_MIN, PO_SCALE_MAX = 0.5, 3.0

PHASE_CHECK_MIN_PER_HOUSE = 2
PHASE_CHECK_INTERVAL_DAYS = 10
PHASE_CHECK_PULL_FORWARD_DAYS = 2   # within N days of stale → pull forward if nearby
PHASE_CHECK_MAX_DETOUR_MIN = 30     # "nearby" = adds at most this much drive

# The two non-negotiable deadline kinds; everything else flexes around them.
HARD_ANCHOR_TYPES = {"field_measure", "post_walk"}

# Accounts where the sold-it-so-you-walk-it rule does NOT apply (reps on national
# builders don't do their own field work — those assign by territory instead).
NATIONAL_PREFIXES = ("DR Horton", "Century")

# Visit types the salesperson rule covers on their own local sales.
SALESPERSON_VISIT_TYPES = {"field_measure", "post_walk"}

# Duty-chart columns in Brian's order: phase, measure, post, punch, blue-tape,
# then service. All service and warranty visit types roll up into "service".
DUTIES = ("phase_check", "field_measure", "post_walk", "punch_out", "blue_tape", "service")

# Punch and service always default to the truck — the territory radius never
# claims them. A duty-chart cell or a manual reassign can still move them.
TECH_DEFAULT_DUTIES = {"punch_out", "service"}


def duty_of(visit_type: str) -> str:
    return visit_type if visit_type in DUTIES else "service"

# Statuses that count as "under construction" for phase-check house counts.
ACTIVE_HOUSE_STATUSES = (
    JobStatus.track, JobStatus.preord, JobStatus.ndord, JobStatus.ordprcss,
    JobStatus.ordsub, JobStatus.ordpo, JobStatus.ord, JobStatus.inst,
)
# Jobs still ahead of their field measure.
PRE_MEASURE_STATUSES = (
    JobStatus.track, JobStatus.preord, JobStatus.ndord, JobStatus.ordprcss, JobStatus.ordsub,
)

# Closed/void jobs are archived in CabinetTron — Autobot never shows their work.
INACTIVE_JOB_STATUSES = (JobStatus.closed, JobStatus.void)

# "Tracking through blue-tape" — the stretch of the ladder where a community
# still has field work coming. EPO/closed/warranty/void are past it.
TRACK_TO_BLUE_STATUSES = (
    JobStatus.track, JobStatus.preord, JobStatus.ndord, JobStatus.ordprcss,
    JobStatus.ordsub, JobStatus.ordpo, JobStatus.ord, JobStatus.inst,
    JobStatus.ndqw, JobStatus.parts, JobStatus.punch, JobStatus.blue,
)

ROAD_FACTOR = 1.3       # straight-line → road miles
AVG_MPH = 45.0          # rural-highway average for the fallback estimate
OSRM_URL = "https://router.project-osrm.org"


def visit_duration_min(visit: Visit, po_amount: float | None, active_houses: int) -> int:
    if visit.duration_min:
        return visit.duration_min
    if visit.visit_type == "phase_check":
        return max(PHASE_CHECK_MIN_PER_HOUSE * max(active_houses, 1), 5)
    base = BASE_DURATION_MIN.get(visit.visit_type, 30)
    if visit.visit_type in PO_SCALED_TYPES and po_amount:
        scale = min(max(float(po_amount) / REFERENCE_PO, PO_SCALE_MIN), PO_SCALE_MAX)
        return round(base * scale)
    return base


# ---------------------------------------------------------------- geometry

def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _estimate_matrix(coords: list[tuple[float, float]]) -> list[list[float]]:
    n = len(coords)
    return [
        [
            0.0 if i == j
            else haversine_miles(coords[i], coords[j]) * ROAD_FACTOR / AVG_MPH * 60
            for j in range(n)
        ]
        for i in range(n)
    ]


def _osrm_matrix(coords: list[tuple[float, float]]) -> list[list[float]]:
    pairs = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
    url = f"{OSRM_URL}/table/v1/driving/{pairs}?annotations=duration"
    req = urllib.request.Request(url, headers={"User-Agent": "CarterKB-Autobot/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read())
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM: {data.get('code')}")
    return [[(cell or 0.0) / 60 for cell in row] for row in data["durations"]]


def drive_matrix(
    coords: list[tuple[float, float]], real_drive: bool
) -> tuple[list[list[float]], str]:
    """Minutes between every coordinate pair. Falls back to the estimate on any failure."""
    # The public OSRM table endpoint caps around 100 locations; estimate past that.
    if real_drive and 1 < len(coords) <= 80:
        try:
            return _osrm_matrix(coords), "osrm"
        except Exception:
            pass
    return _estimate_matrix(coords), "estimate"


# ---------------------------------------------------------------- geocoding

def _http_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "CarterKB-Autobot/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# Addresses we already asked Google about this process — don't burn quota
# re-asking every 10-minute sync for lots it can't find (TBD addresses etc).
_GEOCODE_TRIED: set[int] = set()


# A house pin farther than this from its community pin is a wrong-city geocode
# (e.g. "3182 Sawgrass Street" with no city matching a street in California).
PIN_SANITY_MILES = 40.0


def geocode_missing_job_pins(db: Session, limit: int = 25) -> int:
    """Give active jobs their own rooftop pin so routing goes to the house, not
    the community's front entrance. Only exact hits are stored, the community's
    market is appended when the address has no city of its own, and any result
    implausibly far from the community pin is rejected."""
    jobs = (
        db.query(Job)
        .options(joinedload(Job.community))
        .filter(Job.lat.is_(None), Job.status.in_(TRACK_TO_BLUE_STATUSES))
        .order_by(Job.id.desc())
        .all()
    )
    pinned = 0
    for j in jobs:
        if pinned >= limit:
            break
        if j.id in _GEOCODE_TRIED:
            continue
        _GEOCODE_TRIED.add(j.id)
        addr = (j.address or "").strip()
        if len(addr) < 8 or addr.upper().startswith("TBD") or addr.lower() == "retail":
            continue
        # Feed addresses often lack the city — anchor them to the community's market.
        if "," not in addr and j.community and (j.community.market or "").strip():
            addr = f"{addr}, {j.community.market.strip()}"
        found = geocode_address(addr)
        if not found or found["level"] != "exact":
            continue
        if (
            j.community
            and j.community.lat is not None
            and haversine_miles((found["lat"], found["lon"]),
                                (j.community.lat, j.community.lon)) > PIN_SANITY_MILES
        ):
            continue  # exact rooftop, wrong town — worse than the community fallback
        j.lat, j.lon = found["lat"], found["lon"]
        pinned += 1
    if pinned:
        db.commit()
    return pinned


def geocode_address(query: str) -> dict | None:
    """Address → pin. Google (exact rooftop hits, knows new construction) when a
    key is configured; Nominatim otherwise, with a city-level fallback when the
    street isn't in OSM. Returns {lat, lon, source, level} or None."""
    from urllib.parse import quote

    query = query.strip()
    if not query:
        return None
    key = get_settings().google_maps_api_key
    if key:
        try:
            data = _http_json(
                "https://maps.googleapis.com/maps/api/geocode/json?address="
                f"{quote(query + ', USA')}&key={quote(key)}"
            )
            if data.get("status") == "OK" and data["results"]:
                best = data["results"][0]
                loc = best["geometry"]["location"]
                rooftop = best["geometry"].get("location_type") in ("ROOFTOP", "RANGE_INTERPOLATED")
                return {"lat": loc["lat"], "lon": loc["lng"], "source": "google",
                        "level": "exact" if rooftop else "area"}
        except Exception:
            pass  # fall through to OSM so a Google hiccup never blocks a save

    def osm(q: str):
        results = _http_json(
            "https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + quote(q)
        )
        return results[0] if results else None

    try:
        hit = osm(query + ", USA")
        if hit:
            return {"lat": float(hit["lat"]), "lon": float(hit["lon"]),
                    "source": "osm", "level": "exact"}
        comma = query.find(",")
        if comma > 0:
            hit = osm(query[comma + 1:].strip() + ", USA")
            if hit:
                return {"lat": float(hit["lat"]), "lon": float(hit["lon"]),
                        "source": "osm", "level": "city"}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- parts gating

def parts_state(sr: ServiceRequest, day: date) -> tuple[bool, str]:
    """(ready, detail). Scheduled off the factory's *confirmed* date (due_date),
    not physical arrival; a received flag always counts. If any trade-blocking
    part is covered the visit goes — cosmetic leftovers become a follow-up trip.
    """
    parts = sr.parts
    if not parts:
        return True, "no parts needed"
    if (sr.material_status or "").lower() == "received":
        return True, "all material received"

    def covered(p) -> bool:
        return bool(p.received or (p.due_date and p.due_date <= day))

    blocking = [p for p in parts if p.trade_blocking]
    if blocking:
        missing = [p.part for p in blocking if not covered(p)]
        if not missing:
            leftovers = [p.part for p in parts if not p.trade_blocking and not covered(p)]
            note = "trade-blocking parts in/confirmed"
            if leftovers:
                note += f" — cosmetic still coming: {', '.join(leftovers[:4])}"
            return True, note
        return False, f"waiting on trade-blocking: {', '.join(missing[:4])}"

    missing = [p.part for p in parts if not covered(p)]
    if not missing:
        return True, "parts in/confirmed"
    return False, f"waiting on parts: {', '.join(missing[:4])}"


# ---------------------------------------------------------------- helpers

def effective_coords(visit: Visit) -> tuple[float, float] | None:
    """Most specific pin wins: the visit's own, then the house, then the community."""
    if visit.lat is not None and visit.lon is not None:
        return visit.lat, visit.lon
    if visit.job and visit.job.lat is not None and visit.job.lon is not None:
        return visit.job.lat, visit.job.lon
    community = visit.community or (visit.job.community if visit.job else None)
    if community and community.lat is not None and community.lon is not None:
        return community.lat, community.lon
    return None


def visit_label(visit: Visit) -> str:
    if visit.job:
        code = visit.job.job_code or f"#{visit.job.id}"
        return f"{code} — {visit.job.address}"
    if visit.community:
        return f"{visit.community.name} ({visit.community.account.name})"
    return f"visit #{visit.id}"


def _active_house_count(db: Session, community_id: int) -> int:
    """Tract houses under construction — phase checks are production-builder sweeps,
    so retail/custom catch-all 'communities' never spawn them."""
    from app.models.job import JobType

    return (
        db.query(Job)
        .filter(
            Job.community_id == community_id,
            Job.status.in_(ACTIVE_HOUSE_STATUSES),
            Job.job_type == JobType.tract,
        )
        .count()
    )


RESIDENTIAL_MPH = 20.0  # creeping between lots inside a community


def phase_check_metrics(db: Session, community_id: int) -> tuple[int, int, tuple[float, float] | None]:
    """(house_count, duration_min, start_coords) for a community sweep.

    Houses in a sprawling community (Compass Lakes) can be miles apart, so the
    sweep's time is per-house checking PLUS an estimated lot-to-lot drive: a
    nearest-neighbor walk over the pinned houses at residential speed. The stop
    itself anchors at the centroid of the pinned houses when we have them.
    """
    from app.models.job import JobType

    houses = (
        db.query(Job)
        .filter(
            Job.community_id == community_id,
            Job.status.in_(ACTIVE_HOUSE_STATUSES),
            Job.job_type == JobType.tract,
        )
        .all()
    )
    count = len(houses)
    pinned = [(j.lat, j.lon) for j in houses if j.lat is not None and j.lon is not None]
    # Outlier armor: a mis-geocoded house (wrong city entirely) must never turn
    # a 20-minute sweep into a 5-day one. Drop pins far from the pack's median.
    if len(pinned) >= 2:
        med = (
            sorted(p[0] for p in pinned)[len(pinned) // 2],
            sorted(p[1] for p in pinned)[len(pinned) // 2],
        )
        pinned = [p for p in pinned if haversine_miles(p, med) <= 15.0]
    base = max(PHASE_CHECK_MIN_PER_HOUSE * max(count, 1), 5)
    intra = 0.0
    if len(pinned) >= 2:
        remaining = pinned[1:]
        cur = pinned[0]
        while remaining:
            nxt = min(remaining, key=lambda p: haversine_miles(cur, p))
            intra += haversine_miles(cur, nxt) * ROAD_FACTOR / RESIDENTIAL_MPH * 60
            remaining.remove(nxt)
            cur = nxt
    centroid = (
        (sum(p[0] for p in pinned) / len(pinned), sum(p[1] for p in pinned) / len(pinned))
        if pinned else None
    )
    return count, base + round(intra), centroid


def _fmt(minutes: float) -> str:
    """Minutes-since-midnight → 12-hour clock (Brian: all times in 12hr)."""
    m = int(round(minutes))
    h, mm = divmod(m, 60)
    suffix = "AM" if h % 24 < 12 else "PM"
    return f"{h % 12 or 12}:{mm:02d} {suffix}"


# ---------------------------------------------------------------- generation

def cancel_visits_for_dead_jobs(db: Session) -> int:
    """A job that went closed/void in CabinetTron takes its pending visits with
    it — no measuring a voided house, no punch list on a closed one."""
    stale = (
        db.query(Visit)
        .join(Job, Visit.job_id == Job.id)
        .filter(Visit.status == "pending", Job.status.in_(INACTIVE_JOB_STATUSES))
        .all()
    )
    for v in stale:
        v.status = "canceled"
        v.notes = ((v.notes + " · ") if v.notes else "") + "auto-canceled — job closed/void"
    db.commit()
    return len(stale)


def generate_visits(db: Session, today: date, created_by: str | None = None) -> dict[str, int]:
    """Spawn pending visits from where jobs sit in CabinetTron. Idempotent —
    a job/community with a live (or done) visit of that type is left alone.
    """
    cancel_visits_for_dead_jobs(db)

    def exists(vtype: str, job_id: int | None = None, community_id: int | None = None,
               service_request_id: int | None = None) -> bool:
        q = db.query(Visit.id).filter(Visit.visit_type == vtype, Visit.status != "canceled")
        if job_id is not None:
            q = q.filter(Visit.job_id == job_id)
        if community_id is not None:
            q = q.filter(Visit.community_id == community_id)
        if service_request_id is not None:
            q = q.filter(Visit.service_request_id == service_request_id)
        return db.query(q.exists()).scalar()

    created: dict[str, int] = {}

    def add(vtype: str, **kw) -> None:
        db.add(Visit(visit_type=vtype, created_by=created_by, **kw))
        created[vtype] = created.get(vtype, 0) + 1

    # Field measures: framing floor = the measure date (never early), may slip one day late.
    measures = (
        db.query(Job)
        .filter(
            Job.measure_date.isnot(None),
            Job.measure_date >= today - timedelta(days=30),
            Job.status.in_(PRE_MEASURE_STATUSES),
        )
        .all()
    )
    for j in measures:
        if not exists("field_measure", job_id=j.id):
            add("field_measure", job_id=j.id, open_date=j.measure_date,
                close_date=j.measure_date + timedelta(days=1))

    # Post-walks: the 48-hour clock starts when the installer finishes (status 3.0-Nd QW).
    # Only recent installs — a job parked at Nd QW for months has no live 48h clock, and
    # spawning the whole backlog as due-today anchors would swamp every route. Old ones
    # stay visible on the Jobs board; add a visit manually if one still needs a walk.
    for j in db.query(Job).filter(Job.status == JobStatus.ndqw).all():
        if j.install_date and j.install_date < today - timedelta(days=14):
            continue
        if not exists("post_walk", job_id=j.id):
            start = j.install_date or today
            add("post_walk", job_id=j.id, open_date=start,
                close_date=max(start + timedelta(days=2), today))

    # Punch-outs: flexible, a few weeks out.
    for j in db.query(Job).filter(Job.status == JobStatus.punch).all():
        if not exists("punch_out", job_id=j.id):
            add("punch_out", job_id=j.id, open_date=today, close_date=today + timedelta(days=21))

    # Blue-tape: flexible but urgent before closing.
    for j in db.query(Job).filter(Job.status == JobStatus.blue).all():
        if not exists("blue_tape", job_id=j.id):
            add("blue_tape", job_id=j.id, open_date=today, close_date=today + timedelta(days=7))

    # Service / warranty requests with work left on them.
    requests = (
        db.query(ServiceRequest)
        .options(joinedload(ServiceRequest.lines), joinedload(ServiceRequest.job))
        .all()
    )
    for sr in requests:
        if sr.job and sr.job.status in INACTIVE_JOB_STATUSES:
            continue  # closed/void job — its service work is archived too
        if sr.lines and all(line.done for line in sr.lines):
            continue
        if exists_any_for_request(db, sr.id):
            continue
        vtype = "warranty_t1" if (sr.status or "").lower().startswith("warranty") else "service_t1"
        add(vtype, job_id=sr.job_id, service_request_id=sr.id,
            open_date=today, close_date=sr.scheduled_date)

    # Phase checks that ran dry — every house moved past phase tracking since the
    # sweep was scheduled — get canceled rather than sending him to nothing.
    for v in db.query(Visit).filter(
        Visit.visit_type == "phase_check", Visit.status == "pending"
    ).all():
        if v.community_id and _active_house_count(db, v.community_id) == 0:
            v.status = "canceled"
            v.notes = ((v.notes + " · ") if v.notes else "") + "auto-canceled — no houses left to phase-check"

    # Phase checks: every community with active houses, at least every 10 days.
    # Never checked → due now; checked → due 10 days after the last sweep.
    # "Retail" is the catch-all bucket for one-off jobs, not a subdivision to sweep.
    for c in db.query(Community).all():
        if c.name.strip().lower() == "retail":
            continue
        if _active_house_count(db, c.id) == 0 or _pending_phase_check(db, c.id):
            continue
        last_done = (
            db.query(Visit)
            .filter(Visit.visit_type == "phase_check", Visit.community_id == c.id,
                    Visit.status == "done")
            .order_by(Visit.completed_at.desc())
            .first()
        )
        due = (
            last_done.completed_at.date() + timedelta(days=PHASE_CHECK_INTERVAL_DAYS)
            if last_done and last_done.completed_at
            else today
        )
        add("phase_check", community_id=c.id, close_date=due)

    db.commit()
    return created


def _pending_phase_check(db: Session, community_id: int) -> bool:
    return db.query(
        db.query(Visit.id)
        .filter(Visit.visit_type == "phase_check", Visit.community_id == community_id,
                Visit.status == "pending")
        .exists()
    ).scalar()


def exists_any_for_request(db: Session, service_request_id: int) -> bool:
    return db.query(
        db.query(Visit.id)
        .filter(Visit.service_request_id == service_request_id, Visit.status != "canceled")
        .exists()
    ).scalar()


# ---------------------------------------------------------------- assignment

def default_tech(db: Session) -> Worker | None:
    return db.query(Worker).filter(Worker.is_tech, Worker.active).order_by(Worker.id).first()


def off_worker_ids(db: Session, day: date) -> set[int]:
    rows = (
        db.query(WorkerTimeOff.worker_id)
        .filter(WorkerTimeOff.start_date <= day, WorkerTimeOff.end_date >= day)
        .all()
    )
    return {r[0] for r in rows}


def auto_assign(db: Session) -> dict[str, int]:
    """Hand out unassigned pending visits by Brian's rules:

    1. Sold-it-so-you-walk-it — on local (non-national) accounts, the measure
       and post-walk go to the roster member who sold the job (Paula's rule).
    2. Duty chart — the per-community, per-task grid (how national-account
       territories are really split). A chart cell set to Tech pins the truck
       and skips the radius rule.
    3. Territory — anything sitting inside an area worker's radius goes to them
       (Brian around Chipley, Alex around Freeport).
    4. Otherwise it stays in the tech's pool. Manual assignments are never
       touched — reassign on the board when the tech can't get there.
    """
    workers = db.query(Worker).filter(Worker.active).all()
    sellers = [w for w in workers if w.sales_match]
    area = [w for w in workers if not w.is_tech and w.lat is not None and w.lon is not None]
    duty_map = {(d.community_id, d.duty): d.worker_id for d in db.query(DutyAssignment).all()}
    if not sellers and not area and not duty_map:
        return {}
    by_id = {w.id: w for w in workers}

    visits = (
        db.query(Visit)
        .options(
            joinedload(Visit.job).joinedload(Job.account),
            joinedload(Visit.job).joinedload(Job.community),
            joinedload(Visit.community),
        )
        .filter(Visit.status == "pending", Visit.assigned_to.is_(None))
        .all()
    )
    counts: dict[str, int] = {}
    for v in visits:
        who: Worker | None = None
        job = v.job
        if (
            job is not None
            and job.salesperson
            and v.visit_type in SALESPERSON_VISIT_TYPES
            and not job.account.name.startswith(NATIONAL_PREFIXES)
        ):
            sp = job.salesperson.strip().lower()
            who = next((w for w in sellers if sp.startswith(w.sales_match.strip().lower())), None)
        if who is None:
            comm_id = v.community_id or (job.community_id if job else None)
            key = (comm_id, duty_of(v.visit_type))
            if comm_id is not None and key in duty_map:
                who = by_id.get(duty_map[key])
                if who is None:
                    continue  # chart says explicitly the tech — stay in the pool
        if who is None and duty_of(v.visit_type) not in TECH_DEFAULT_DUTIES:
            account = job.account if job else (v.community.account if v.community else None)
            national = bool(account and account.name.startswith(NATIONAL_PREFIXES))
            eligible = [w for w in area if w.national_ok or not national]
            coords = effective_coords(v)
            if coords and eligible:
                in_range = [
                    (haversine_miles(coords, (w.lat, w.lon)), w)
                    for w in eligible
                    if haversine_miles(coords, (w.lat, w.lon)) <= w.radius_miles
                ]
                if in_range:
                    who = min(in_range, key=lambda t: t[0])[1]
        if who is not None:
            v.assigned_to = who.id
            counts[who.name] = counts.get(who.name, 0) + 1
    db.commit()
    return counts


# ---------------------------------------------------------------- planning

def plan_day(
    db: Session,
    day: date,
    real_drive: bool = False,
    exclude_ids: frozenset[int] = frozenset(),
    worker_id: int | None = None,
) -> dict:
    """Build one day's loop for one person. Default = the service tech, whose
    pool also holds every unassigned visit; an area worker's route starts and
    ends at their own house, not the shop. exclude_ids = visits already spoken
    for by earlier days when the forecast simulates the week ahead."""
    settings = get_settings()
    worker = db.get(Worker, worker_id) if worker_id else default_tech(db)
    if worker and worker.lat is not None and worker.lon is not None:
        depot = (worker.lat, worker.lon)
    else:
        depot = (settings.autobot_depot_lat, settings.autobot_depot_lon)
    tech_pool = worker is None or worker.is_tech  # unassigned work rides the truck
    day_start = settings.autobot_day_start_min
    day_end = settings.autobot_day_end_min

    off_today = off_worker_ids(db, day)
    if worker is not None and worker.id in off_today:
        return {
            "day": day.isoformat(),
            "worker": worker.name,
            "worker_id": worker.id,
            "time_off": True,
            "depot": {"lat": depot[0], "lon": depot[1]},
            "leave": _fmt(day_start), "back": _fmt(day_start),
            "workday_end": _fmt(day_end),
            "stops": [], "drive_min": 0, "onsite_min": 0, "total_min": 0,
            "overflow": False, "drive_source": "estimate", "skipped": [],
        }

    visits = (
        db.query(Visit)
        .options(
            joinedload(Visit.job).joinedload(Job.community),
            joinedload(Visit.job).joinedload(Job.account),
            joinedload(Visit.community).joinedload(Community.account),
            joinedload(Visit.service_request).joinedload(ServiceRequest.parts),
            joinedload(Visit.assignee),
        )
        .filter(Visit.status == "pending")
        .all()
    )

    candidates: list[dict] = []
    skipped: list[dict] = []
    for v in visits:
        if v.id in exclude_ids:
            continue  # handled on an earlier forecast day
        if v.job and v.job.status in INACTIVE_JOB_STATUSES:
            continue  # job archived in CabinetTron since the visit was made
        # Deadline rescue: an off worker's due measure/post-walk rides the truck.
        rescued = (
            tech_pool
            and v.assigned_to is not None
            and v.assigned_to in off_today
            and v.visit_type in HARD_ANCHOR_TYPES
            and v.close_date is not None
            and v.close_date <= day
        )
        if not rescued and worker is not None and v.assigned_to != worker.id and not (
            v.assigned_to is None and tech_pool
        ):
            continue  # someone else's stop
        label = visit_label(v)
        if rescued and v.assignee:
            label += f" (covering for {v.assignee.name} — off)"
        if v.scheduled_date and v.scheduled_date != day:
            continue  # pinned to another day
        if v.open_date and v.open_date > day:
            continue  # not open yet
        if v.service_request:
            ready, detail = parts_state(v.service_request, day)
            if not ready:
                skipped.append({"visit_id": v.id, "label": label, "visit_type": v.visit_type,
                                "reason": f"parts hold — {detail}"})
                continue
        coords = effective_coords(v)
        houses = 0
        if v.visit_type == "phase_check":
            houses, sweep_min, centroid = phase_check_metrics(db, v.community_id)
            if houses == 0:
                # Every house moved past phase tracking — never send him to nothing.
                skipped.append({"visit_id": v.id, "label": label, "visit_type": v.visit_type,
                                "reason": "no houses left to phase-check — auto-cancels on next sync"})
                continue
            if centroid is not None:
                coords = centroid  # anchor the sweep where the houses actually are
            duration = v.duration_min or sweep_min
        else:
            po = float(v.job.po_amount) if v.job and v.job.po_amount is not None else None
            duration = visit_duration_min(v, po, 0)
        if coords is None:
            skipped.append({"visit_id": v.id, "label": label, "visit_type": v.visit_type,
                            "reason": "no location — set the community pin on the Places tab"})
            continue
        candidates.append({
            "visit": v,
            "label": label,
            "coords": coords,
            "duration": duration,
            "houses": houses,
        })

    # Hard anchors: due/overdue field measures & post-walks, plus anything pinned today.
    def is_anchor(c: dict) -> bool:
        v = c["visit"]
        if v.scheduled_date == day:
            return True
        return (
            v.visit_type in HARD_ANCHOR_TYPES
            and v.close_date is not None
            and v.close_date <= day
        )

    anchors = [c for c in candidates if is_anchor(c)]
    flexible = [c for c in candidates if not is_anchor(c)]

    # One matrix over the shop + every candidate — a single OSRM call covers the day.
    all_pts = [depot] + [c["coords"] for c in candidates]
    matrix, source = drive_matrix(all_pts, real_drive)
    gi = {id(c): i + 1 for i, c in enumerate(candidates)}  # matrix index (0 = depot)

    def leg_min(a: dict | None, b: dict | None) -> float:
        return matrix[gi[id(a)] if a else 0][gi[id(b)] if b else 0]

    def route_minutes(stops: list[dict]) -> float:
        total, prev = 0.0, None
        for s in stops:
            total += leg_min(prev, s) + s["duration"]
            prev = s
        return total + leg_min(prev, None)

    # Route the anchors: nearest neighbor from the shop, then a 2-opt pass.
    route: list[dict] = []
    remaining = list(anchors)
    cur: dict | None = None
    while remaining:
        nxt = min(remaining, key=lambda c: leg_min(cur, c))
        route.append(nxt)
        remaining.remove(nxt)
        cur = nxt
    # 2-opt is O(n^3)-ish per pass — worth it for a normal day, skipped for a
    # pathological anchor pile-up where nearest-neighbor alone has to do.
    improved = len(route) <= 30
    while improved and len(route) > 2:
        improved = False
        for i in range(len(route) - 1):
            for j in range(i + 1, len(route)):
                trial = route[:i] + route[i:j + 1][::-1] + route[j + 1:]
                if route_minutes(trial) + 1e-9 < route_minutes(route):
                    route, improved = trial, True

    # Backfill: near-stale phase checks first (only if the detour is small), then
    # everything else by deadline/priority, cheapest insertion while the day fits.
    def sort_key(c: dict):
        v = c["visit"]
        stale_soon = (
            v.visit_type == "phase_check"
            and v.close_date is not None
            and v.close_date <= day + timedelta(days=PHASE_CHECK_PULL_FORWARD_DAYS)
        )
        return (
            0 if stale_soon else 1,
            v.close_date or date.max,
            -v.priority,
        )

    flexible.sort(key=sort_key)
    for cand in flexible:
        best = min(
            (route[:pos] + [cand] + route[pos:] for pos in range(len(route) + 1)),
            key=route_minutes,
        )
        base_total = route_minutes(route)
        best_total = route_minutes(best)
        added_drive = best_total - base_total - cand["duration"]
        v = cand["visit"]
        if day_start + best_total > day_end:
            skipped.append({"visit_id": v.id, "label": cand["label"], "visit_type": v.visit_type,
                            "reason": "day is full — didn't fit inside the workday"})
            continue
        if (
            v.visit_type == "phase_check"
            and not (v.close_date and v.close_date <= day)
            and added_drive > PHASE_CHECK_MAX_DETOUR_MIN
        ):
            skipped.append({"visit_id": v.id, "label": cand["label"], "visit_type": v.visit_type,
                            "reason": f"not nearby today (+{round(added_drive)} min detour) — waits for a closer trip"})
            continue
        route = best

    # Final timeline.
    stops, clock, prev, drive_total, onsite_total = [], float(day_start), None, 0.0, 0.0
    for n, c in enumerate(route, start=1):
        v = c["visit"]
        leg = leg_min(prev, c)
        clock += leg
        arrive = clock
        clock += c["duration"]
        drive_total += leg
        onsite_total += c["duration"]
        prev = c
        due_today = bool(v.close_date and v.close_date <= day)
        stops.append({
            "order": n,
            "visit_id": v.id,
            "visit_type": v.visit_type,
            "label": c["label"],
            "job_id": v.job_id,
            "community_id": v.community_id or (v.job.community_id if v.job else None),
            "lat": c["coords"][0],
            "lon": c["coords"][1],
            "drive_min": round(leg),
            "arrive": _fmt(arrive),
            "depart": _fmt(clock),
            "duration_min": c["duration"],
            "close_date": v.close_date.isoformat() if v.close_date else None,
            "due_today": due_today,
            "anchor": is_anchor(c),
            "houses": c["houses"] or None,
            "notes": v.notes,
        })
    leg_home = leg_min(prev, None) if route else 0.0
    clock += leg_home
    drive_total += leg_home

    # Flag on the rounded minute so the banner always matches the displayed time
    # (a day 20 seconds long isn't a crisis).
    overflow = round(clock) > day_end
    return {
        "day": day.isoformat(),
        "worker": worker.name if worker else "Service Tech",
        "worker_id": worker.id if worker else None,
        "depot": {"lat": depot[0], "lon": depot[1]},
        "leave": _fmt(day_start),
        "back": _fmt(clock),
        "workday_end": _fmt(day_end),
        "stops": stops,
        "drive_min": round(drive_total),
        "onsite_min": round(onsite_total),
        "total_min": round(clock - day_start),
        "overflow": overflow,
        "drive_source": source,
        "skipped": skipped,
    }


def plan_horizon(
    db: Session,
    start: date,
    days: int = 10,
    real_drive: bool = False,
    worker_id: int | None = None,
) -> dict:
    """The rest of the schedule: plan consecutive workdays, treating each day's
    stops as completed so the next day routes what's left. Weekends skipped.
    Shows how the current backlog drains — it doesn't re-run generation, so
    phase-check cycles that would respawn later aren't projected."""
    done: set[int] = set()
    day_plans: list[dict] = []
    day = start
    for _ in range(days):
        while day.weekday() >= 5:  # Sat/Sun
            day += timedelta(days=1)
        plan = plan_day(
            db, day, real_drive=real_drive, exclude_ids=frozenset(done), worker_id=worker_id
        )
        done.update(s["visit_id"] for s in plan["stops"])
        day_plans.append(plan)
        day += timedelta(days=1)
    while len(day_plans) > 1 and not day_plans[-1]["stops"]:
        day_plans.pop()  # trim trailing empty days
    leftovers = day_plans[-1]["skipped"] if day_plans else []
    return {
        "start": start.isoformat(),
        "days": day_plans,
        "total_stops": len(done),
        "leftover": leftovers,
    }
