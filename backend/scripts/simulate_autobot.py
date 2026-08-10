"""Autobot month-long fuzz simulation.

Builds a random world (communities, jobs, workers, duty chart, service requests,
vacations), then simulates ~22 workdays: every day jobs advance/void/appear,
parts arrive or slip, the sync generates + assigns visits, every worker's route
is planned, and routed stops get completed. After each plan a battery of
invariants is checked. Run N seeds, report every violation by rule.

Usage (from backend/):
    python -m scripts.simulate_autobot [runs=100] [days=22]
"""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.autobot import (
    HARD_ANCHOR_TYPES,
    NATIONAL_PREFIXES,
    TECH_DEFAULT_DUTIES,
    _active_house_count,
    auto_assign,
    duty_of,
    generate_visits,
    parts_state,
    plan_day,
)
from app.models import (
    Account,
    AccountType,
    Community,
    DutyAssignment,
    Job,
    JobStatus,
    JobType,
    ServicePart,
    ServiceRequest,
    Visit,
    Worker,
    WorkerTimeOff,
)

START = date(2026, 8, 10)  # a Monday

LADDER = [
    JobStatus.track, JobStatus.preord, JobStatus.ndord, JobStatus.ordprcss,
    JobStatus.ordsub, JobStatus.ordpo, JobStatus.ord, JobStatus.inst,
    JobStatus.ndqw, JobStatus.punch, JobStatus.blue, JobStatus.epo, JobStatus.closed,
]
INACTIVE = (JobStatus.closed, JobStatus.void)

# Panhandle-ish coordinate box
LAT = (30.1, 31.4)
LON = (-87.3, -85.0)


def fresh_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def build_world(db, rng: random.Random):
    nat1 = Account(name="DR Horton Simville", type=AccountType.builder)
    nat2 = Account(name="Century Sim", type=AccountType.builder)
    loc = Account(name="Sim Local Homes", type=AccountType.builder)
    db.add_all([nat1, nat2, loc])
    db.flush()

    communities = []
    for i in range(rng.randint(5, 9)):
        acct = rng.choice([nat1, nat1, nat2, loc])
        pinned = rng.random() > 0.15  # some communities are missing pins
        c = Community(
            account_id=acct.id, name=f"Sim {i}", market="Simville",
            lat=rng.uniform(*LAT) if pinned else None,
            lon=rng.uniform(*LON) if pinned else None,
        )
        db.add(c)
        communities.append(c)
    db.flush()

    tech = Worker(name="Sim Tech", is_tech=True, lat=31.2571, lon=-85.4035, radius_miles=500)
    area1 = Worker(name="Area North", lat=rng.uniform(*LAT), lon=rng.uniform(*LON), radius_miles=30)
    area2 = Worker(name="Area South", lat=rng.uniform(*LAT), lon=rng.uniform(*LON), radius_miles=30)
    local_only = Worker(name="Local Lucy", national_ok=False,
                        lat=rng.uniform(*LAT), lon=rng.uniform(*LON), radius_miles=30)
    seller = Worker(name="Paula Sim", sales_match="Paula")
    db.add_all([tech, area1, area2, local_only, seller])
    db.flush()

    # random duty-chart cells
    for c in rng.sample(communities, k=min(3, len(communities))):
        for duty in rng.sample(["phase_check", "field_measure", "post_walk", "punch_out", "service"],
                               k=rng.randint(0, 3)):
            db.add(DutyAssignment(
                community_id=c.id, duty=duty,
                worker_id=rng.choice([None, area1.id, area2.id]),
            ))

    # vacations scattered through the month
    for w in (area1, area2, local_only):
        if rng.random() < 0.7:
            off = START + timedelta(days=rng.randint(0, 18))
            db.add(WorkerTimeOff(worker_id=w.id, start_date=off,
                                 end_date=off + timedelta(days=rng.randint(0, 6))))

    jobs = []
    for i in range(rng.randint(25, 45)):
        c = rng.choice(communities)
        acct = db.get(Account, c.account_id)
        national = acct.name.startswith(NATIONAL_PREFIXES)
        job = Job(
            account_id=c.account_id, community_id=c.id,
            lot_number=str(i + 1), address=f"{i + 1} Sim St",
            job_type=JobType.tract if national else rng.choice([JobType.custom, JobType.remodel]),
            status=rng.choice(LADDER[:9]),
            salesperson=None if national else rng.choice(["Paula Sim", "Randy Rep", None]),
            sales_contact_name="s", field_contact_name="f",
            po_amount=rng.choice([None, 1500, 2500, 4000, 7000]),
        )
        db.add(job)
        jobs.append(job)
    db.flush()
    for j in jobs:
        idx = LADDER.index(j.status)
        if idx >= 2:
            j.measure_date = START + timedelta(days=rng.randint(-10, 3))
        if idx >= 7:
            j.install_date = START + timedelta(days=rng.randint(-10, 5))
    db.commit()
    return communities, jobs, [tech, area1, area2, local_only, seller]


def evolve(db, rng, day, communities, jobs):
    """One day of the real world happening."""
    for j in jobs:
        if j.status in INACTIVE:
            continue
        r = rng.random()
        if r < 0.004:
            j.status = JobStatus.void
            continue
        if r < 0.18:  # advance a rung
            idx = LADDER.index(j.status) if j.status in LADDER else None
            if idx is not None and idx < len(LADDER) - 1:
                j.status = LADDER[idx + 1]
                if j.status == JobStatus.ndord and j.measure_date is None:
                    j.measure_date = day + timedelta(days=rng.randint(0, 6))
                if j.status == JobStatus.ordpo and j.install_date is None:
                    j.install_date = day + timedelta(days=rng.randint(3, 12))
        # tracker moves a measure date around sometimes
        if j.measure_date and rng.random() < 0.02:
            j.measure_date = j.measure_date + timedelta(days=rng.randint(1, 5))
    # new jobs appear
    if rng.random() < 0.5:
        c = rng.choice(communities)
        acct = db.get(Account, c.account_id)
        n = 1000 + rng.randint(0, 100000)
        j = Job(
            account_id=c.account_id, community_id=c.id, lot_number=str(n),
            address=f"{n} Sim St", job_type=JobType.tract,
            status=JobStatus.track, sales_contact_name="s", field_contact_name="f",
            po_amount=rng.choice([2000, 3000, 5000]),
        )
        db.add(j)
        jobs.append(j)
    # service requests appear on installed houses
    if rng.random() < 0.35:
        done_jobs = [j for j in jobs if j.status in (JobStatus.punch, JobStatus.blue, JobStatus.war)]
        if done_jobs:
            j = rng.choice(done_jobs)
            sr = ServiceRequest(job_id=j.id, status=rng.choice(["Installed", "Warranty"]))
            db.add(sr)
            db.flush()
            for _ in range(rng.randint(0, 3)):
                db.add(ServicePart(
                    service_request_id=sr.id, part=f"Part{rng.randint(1, 99)}",
                    trade_blocking=rng.random() < 0.4,
                    received=rng.random() < 0.3,
                    due_date=day + timedelta(days=rng.randint(-2, 10)) if rng.random() < 0.8 else None,
                ))
    # parts arrive or slip
    for p in db.query(ServicePart).all():
        if not p.received and rng.random() < 0.15:
            p.received = True
        elif p.due_date and rng.random() < 0.05:
            p.due_date = p.due_date + timedelta(days=rng.randint(2, 7))
    db.commit()


def check_plan(db, plan, worker, day, off_ids, seen_today, violations):
    v_by_id = {v.id: v for v in db.query(Visit).all()}
    end_min = 17 * 60

    def note(rule, detail):
        violations[rule].append(f"day {plan['day']} {worker or 'TECH'}: {detail}")

    back_h, back_rest = plan["back"].split(":")
    back_min = (int(back_h) % 12) * 60 + int(back_rest.split(" ")[0]) + (720 if "PM" in plan["back"] else 0)
    if plan["stops"] and (back_min > end_min) != plan["overflow"]:
        note("overflow-flag-wrong", f"back={plan['back']} overflow={plan['overflow']}")

    for s in plan["stops"]:
        v = v_by_id[s["visit_id"]]
        job = db.get(Job, v.job_id) if v.job_id else None
        if job and job.status in INACTIVE:
            note("routed-dead-job", f"{v.visit_type} for {job.status.value} job {job.id}")
        if v.visit_type == "phase_check" and _active_house_count(db, v.community_id) == 0:
            note("routed-empty-phase-check", f"community {v.community_id}")
        if v.open_date and v.open_date > day:
            note("routed-before-open", f"{v.visit_type} opens {v.open_date}, planned {day}")
        if v.status != "pending":
            note("routed-nonpending", f"visit {v.id} status {v.status}")
        if s["visit_id"] in seen_today:
            note("double-scheduled", f"visit {v.id} on two routes the same day")
        seen_today.add(s["visit_id"])
        if v.service_request_id:
            sr = db.get(ServiceRequest, v.service_request_id)
            ready, why = parts_state(sr, day)
            if not ready:
                note("routed-parts-blocked", f"visit {v.id}: {why}")
        wid = plan.get("worker_id")
        if worker is None:  # tech plan
            if v.assigned_to is not None and not (
                v.assigned_to in off_ids
                and v.visit_type in HARD_ANCHOR_TYPES
                and v.close_date and v.close_date <= day
            ):
                note("tech-took-someone-elses", f"visit {v.id} assigned to {v.assigned_to}")
        else:
            if v.assigned_to != wid:
                note("wrong-workers-stop", f"visit {v.id} assigned {v.assigned_to} on {worker}")

    if plan.get("time_off") and plan["stops"]:
        note("routed-on-vacation", "stops while off")


def check_assignments(db, day, violations):
    for v in db.query(Visit).filter(Visit.status == "pending", Visit.assigned_to.isnot(None)).all():
        w = db.get(Worker, v.assigned_to)
        job = db.get(Job, v.job_id) if v.job_id else None
        acct = db.get(Account, job.account_id) if job else (
            db.get(Account, db.get(Community, v.community_id).account_id) if v.community_id else None
        )
        national = bool(acct and acct.name.startswith(NATIONAL_PREFIXES))
        comm_id = v.community_id or (job.community_id if job else None)
        charted = comm_id and db.query(DutyAssignment).filter(
            DutyAssignment.community_id == comm_id,
            DutyAssignment.duty == duty_of(v.visit_type),
            DutyAssignment.worker_id == v.assigned_to,
        ).first()
        if national and w and not w.national_ok and not charted:
            violations["local-only-got-national"].append(
                f"day {day}: visit {v.id} ({v.visit_type}) -> {w.name}"
            )


def run_once(seed: int, days: int, violations):
    rng = random.Random(seed)
    db = fresh_db()
    communities, jobs, workers = build_world(db, rng)
    tech = workers[0]
    day = START
    for _ in range(days):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        evolve(db, rng, day, communities, jobs)
        created = generate_visits(db, day)
        again = generate_visits(db, day)
        if again:
            violations["generate-not-idempotent"].append(f"day {day}: second run created {again}")
        auto_assign(db)
        check_assignments(db, day, violations)

        off_ids = {
            t.worker_id for t in db.query(WorkerTimeOff).all()
            if t.start_date <= day <= t.end_date
        }
        seen_today: set[int] = set()
        plans = [(None, plan_day(db, day, real_drive=False))]
        for w in workers[1:]:
            plans.append((w.name, plan_day(db, day, real_drive=False, worker_id=w.id)))
        for wname, plan in plans:
            check_plan(db, plan, wname, day, off_ids, seen_today, violations)

        # the day happens: every routed stop gets completed
        for wname, plan in plans:
            for s in plan["stops"]:
                v = db.get(Visit, s["visit_id"])
                v.status = "done"
                v.completed_at = datetime(day.year, day.month, day.day, 15, tzinfo=timezone.utc)
        db.commit()
        day += timedelta(days=1)

    # month-end: hard anchors that existed >3 workdays and never got done
    for v in db.query(Visit).filter(Visit.status == "pending").all():
        job = db.get(Job, v.job_id) if v.job_id else None
        if job and job.status in INACTIVE:
            continue
        if (
            v.visit_type in HARD_ANCHOR_TYPES
            and v.close_date and v.close_date < day - timedelta(days=4)
        ):
            coords_ok = True
            from app.autobot import effective_coords
            if effective_coords(v) is None:
                coords_ok = False
            if coords_ok:
                if v.service_request_id:
                    sr = db.get(ServiceRequest, v.service_request_id)
                    if not parts_state(sr, day)[0]:
                        continue
                violations["anchor-never-scheduled"].append(
                    f"seed {seed}: {v.visit_type} visit {v.id} due {v.close_date} still pending at month end"
                )
    db.close()


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 22
    violations: dict[str, list[str]] = defaultdict(list)
    for seed in range(runs):
        run_once(seed, days, violations)
        if (seed + 1) % 20 == 0:
            print(f"...{seed + 1}/{runs} runs done", flush=True)
    print("\n=== RESULTS ===")
    if not violations:
        print("clean: no invariant violations across", runs, "month-long runs")
        return
    counts = Counter({rule: len(v) for rule, v in violations.items()})
    for rule, n in counts.most_common():
        print(f"\n[{rule}] {n} hits — examples:")
        for example in violations[rule][:4]:
            print("   ", example)


if __name__ == "__main__":
    main()
