from datetime import date, datetime, timedelta, timezone

from app.autobot import (
    auto_assign,
    generate_visits,
    parts_state,
    plan_day,
    plan_horizon,
    visit_duration_min,
)
from app.models import (
    Account,
    AccountType,
    Community,
    DutyAssignment,
    Job,
    JobStatus,
    JobType,
    Role,
    ServicePart,
    ServiceRequest,
    Visit,
    Worker,
    WorkerTimeOff,
)
from tests.conftest import login, make_user

TODAY = date(2026, 8, 6)


def seed(db, *, community_coords=(31.0, -85.6)):
    account = Account(name="DR Horton Dothan", type=AccountType.builder)
    db.add(account)
    db.flush()
    community = Community(
        account_id=account.id, name="Bellwood", market="Dothan AL",
        lat=community_coords[0], lon=community_coords[1],
    )
    db.add(community)
    db.flush()
    return account, community


def make_job(db, account, community, *, status=JobStatus.track, po=None, **kw):
    job = Job(
        account_id=account.id,
        community_id=community.id if community else None,
        address=kw.pop("address", "100 Test St"),
        job_type=JobType.tract,
        status=status,
        sales_contact_name="Sales",
        field_contact_name="Field",
        po_amount=po,
        **kw,
    )
    db.add(job)
    db.flush()
    return job


# ---------------------------------------------------------------- durations

def test_duration_scales_off_po(db):
    account, community = seed(db)
    small = make_job(db, account, community, po=1250)
    big = make_job(db, account, community, po=5000)
    v_small = Visit(visit_type="punch_out", job_id=small.id)
    v_big = Visit(visit_type="punch_out", job_id=big.id)
    # $1,250 = half the $2,500 reference; $5,000 = double it
    assert visit_duration_min(v_small, 1250, 0) == 30
    assert visit_duration_min(v_big, 5000, 0) == 120


def test_duration_clamps_and_fallback(db):
    v = Visit(visit_type="field_measure")
    assert visit_duration_min(v, None, 0) == 20        # no PO → flat default
    assert visit_duration_min(v, 100000, 0) == 60      # clamped at 3x
    assert visit_duration_min(Visit(visit_type="phase_check"), None, 12) == 24  # 2 min/house
    override = Visit(visit_type="post_walk", duration_min=45)
    assert visit_duration_min(override, 9999, 0) == 45


# ---------------------------------------------------------------- parts gating

def test_parts_gate_trade_blocking_dispatches_partial(db):
    account, community = seed(db)
    job = make_job(db, account, community)
    sr = ServiceRequest(job_id=job.id)
    db.add(sr)
    db.flush()
    db.add(ServicePart(service_request_id=sr.id, part="Base cabinet", trade_blocking=True,
                       received=True))
    db.add(ServicePart(service_request_id=sr.id, part="Warranty door", trade_blocking=False))
    db.flush()
    db.refresh(sr)
    ready, note = parts_state(sr, TODAY)
    assert ready  # blocking part is in → go now, cosmetic door becomes a follow-up
    assert "Warranty door" in note


def test_parts_gate_blocks_on_missing_blocking_part(db):
    account, community = seed(db)
    job = make_job(db, account, community)
    sr = ServiceRequest(job_id=job.id)
    db.add(sr)
    db.flush()
    db.add(ServicePart(service_request_id=sr.id, part="Tall pantry", trade_blocking=True))
    db.flush()
    db.refresh(sr)
    ready, note = parts_state(sr, TODAY)
    assert not ready
    assert "Tall pantry" in note


def test_parts_gate_schedules_off_confirmed_date(db):
    account, community = seed(db)
    job = make_job(db, account, community)
    sr = ServiceRequest(job_id=job.id)
    db.add(sr)
    db.flush()
    part = ServicePart(service_request_id=sr.id, part="Crown", due_date=TODAY + timedelta(days=3))
    db.add(part)
    db.flush()
    db.refresh(sr)
    ready, _ = parts_state(sr, TODAY)
    assert not ready  # confirmed for 3 days out — not schedulable today
    ready, _ = parts_state(sr, TODAY + timedelta(days=3))
    assert ready      # schedulable the day the factory confirmed, ahead of arrival


def test_sprawling_community_sweep_counts_lot_to_lot_driving(db):
    from app.autobot import phase_check_metrics

    account, community = seed(db)
    # Two houses ~4.3 miles apart (Compass Lakes situation) + one unpinned.
    make_job(db, account, community).lat, _ = 31.00, None
    a = make_job(db, account, community, address="1 Far End")
    b = make_job(db, account, community, address="2 Other End")
    a.lat, a.lon = 31.00, -85.60
    b.lat, b.lon = 31.00, -85.5275  # ≈ 4.3 miles east
    db.commit()

    count, duration, centroid = phase_check_metrics(db, community.id)
    assert count == 3
    base = max(2 * count, 5)
    assert duration >= base + 15  # ~4.3 mi at residential speed ≈ 17 min of lot-to-lot driving
    assert abs(centroid[1] - (-85.60 - 85.5275) / 2) < 0.01  # anchored between the houses

    # tight community: houses on top of each other → no meaningful intra drive
    tight = Community(account_id=account.id, name="Tight", lat=31.0, lon=-85.6)
    db.add(tight)
    db.flush()
    for i in range(3):
        j = make_job(db, account, tight, address=f"{i} Close St")
        j.lat, j.lon = 31.0001 + i * 0.0001, -85.6
    db.commit()
    _, tight_duration, _ = phase_check_metrics(db, tight.id)
    assert tight_duration <= max(2 * 3, 5) + 1


# ---------------------------------------------------------------- generation

def test_generate_spawns_and_is_idempotent(db):
    account, community = seed(db)
    make_job(db, account, community, status=JobStatus.track, measure_date=TODAY)
    make_job(db, account, community, status=JobStatus.ndqw, install_date=TODAY - timedelta(days=1))
    make_job(db, account, community, status=JobStatus.punch)
    make_job(db, account, community, status=JobStatus.blue)
    db.commit()

    created = generate_visits(db, TODAY)
    assert created["field_measure"] == 1
    assert created["post_walk"] == 1
    assert created["punch_out"] == 1
    assert created["blue_tape"] == 1
    assert created["phase_check"] == 1  # community has active houses

    assert generate_visits(db, TODAY) == {}  # second run creates nothing

    pw = db.query(Visit).filter(Visit.visit_type == "post_walk").one()
    assert pw.close_date == TODAY + timedelta(days=1)  # install + 48h


def test_generate_phase_check_due_10_days_after_last_sweep(db):
    account, community = seed(db)
    make_job(db, account, community, status=JobStatus.ord)
    done = Visit(
        visit_type="phase_check", community_id=community.id, status="done",
        completed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    db.add(done)
    db.commit()
    generate_visits(db, TODAY)
    pending = db.query(Visit).filter(
        Visit.visit_type == "phase_check", Visit.status == "pending"
    ).one()
    assert pending.close_date == date(2026, 8, 11)


# ---------------------------------------------------------------- planning

def test_plan_anchors_first_and_capacity(db):
    account, community = seed(db)
    far = Community(account_id=account.id, name="Pensacola East", market="Pensacola FL",
                    lat=30.47, lon=-87.19)
    db.add(far)
    db.flush()

    measure_job = make_job(db, account, community, status=JobStatus.track)
    walk_job = make_job(db, account, far, status=JobStatus.ndqw, address="200 Gulf Ave")
    punch_job = make_job(db, account, community, status=JobStatus.punch, address="300 Oak Ln")

    db.add(Visit(visit_type="field_measure", job_id=measure_job.id, open_date=TODAY,
                 close_date=TODAY))
    db.add(Visit(visit_type="post_walk", job_id=walk_job.id, open_date=TODAY, close_date=TODAY))
    db.add(Visit(visit_type="punch_out", job_id=punch_job.id, open_date=TODAY,
                 close_date=TODAY + timedelta(days=21)))
    db.commit()

    plan = plan_day(db, TODAY, real_drive=False)
    assert len(plan["stops"]) == 3
    anchors = [s for s in plan["stops"] if s["anchor"]]
    assert {s["visit_type"] for s in anchors} == {"field_measure", "post_walk"}
    assert plan["drive_min"] > 0
    assert plan["drive_source"] == "estimate"
    assert not plan["overflow"]


def test_plan_skips_parts_blocked_and_unlocated(db):
    account, community = seed(db)
    job = make_job(db, account, community)
    sr = ServiceRequest(job_id=job.id)
    db.add(sr)
    db.flush()
    db.add(ServicePart(service_request_id=sr.id, part="End panel", trade_blocking=True))
    db.add(Visit(visit_type="service_t1", job_id=job.id, service_request_id=sr.id,
                 open_date=TODAY))

    lost_account = Account(name="Retail", type=AccountType.retail)
    db.add(lost_account)
    db.flush()
    lost_job = Job(
        account_id=lost_account.id, address="No Pin Rd", job_type=JobType.remodel,
        status=JobStatus.punch, sales_contact_name="s", field_contact_name="f",
    )
    db.add(lost_job)
    db.flush()
    db.add(Visit(visit_type="punch_out", job_id=lost_job.id, open_date=TODAY))
    db.commit()

    plan = plan_day(db, TODAY, real_drive=False)
    assert plan["stops"] == []
    reasons = {s["reason"][:5] for s in plan["skipped"]}
    assert len(plan["skipped"]) == 2
    assert any(r.startswith("parts") for r in reasons)
    assert any(r.startswith("no lo") for r in reasons)


def test_plan_overflow_flag(db):
    account, community = seed(db)
    for i in range(12):
        j = make_job(db, account, community, status=JobStatus.punch, po=7500,
                     address=f"{i} Long Day Dr")
        db.add(Visit(visit_type="post_walk", job_id=j.id, open_date=TODAY, close_date=TODAY,
                     duration_min=90))
    db.commit()
    plan = plan_day(db, TODAY, real_drive=False)
    assert plan["overflow"]  # 12 forced 90-minute walks cannot fit a 10-hour day
    assert len(plan["stops"]) == 12  # anchors are never dropped — the flag surfaces the crisis


def test_forecast_drains_backlog_across_workdays(db):
    # 12 hour-long punch-outs ≈ 2-3 per day with drive time — the horizon spreads
    # them out, each day assuming the previous day's stops got done.
    account, community = seed(db)
    for i in range(12):
        j = make_job(db, account, community, status=JobStatus.punch, address=f"{i} Spread St")
        db.add(Visit(visit_type="punch_out", job_id=j.id, open_date=TODAY,
                     close_date=TODAY + timedelta(days=21), duration_min=60))
    db.commit()

    friday = date(2026, 8, 7)
    fc = plan_horizon(db, friday, days=10, real_drive=False)
    assert fc["total_stops"] == 12  # everything lands somewhere in the horizon
    ids = [s["visit_id"] for p in fc["days"] for s in p["stops"]]
    assert len(ids) == len(set(ids))  # a completed visit never reappears
    assert len(fc["days"]) > 1  # too much for one day — it actually spreads
    planned_days = [p["day"] for p in fc["days"]]
    assert "2026-08-08" not in planned_days  # Saturday
    assert "2026-08-09" not in planned_days  # Sunday


def test_times_are_12_hour(db):
    account, community = seed(db)
    j = make_job(db, account, community, status=JobStatus.punch)
    db.add(Visit(visit_type="punch_out", job_id=j.id, open_date=TODAY))
    db.commit()
    plan = plan_day(db, TODAY, real_drive=False)
    assert plan["leave"] == "7:00 AM"
    assert plan["workday_end"] == "5:00 PM"
    assert plan["stops"][0]["arrive"].endswith(("AM", "PM"))


def test_closed_and_void_jobs_drop_out_of_autobot(db):
    account, community = seed(db)
    live = make_job(db, account, community, status=JobStatus.punch)
    dead = make_job(db, account, community, status=JobStatus.punch, address="9 Gone St")
    keep = Visit(visit_type="punch_out", job_id=live.id, open_date=TODAY)
    drop = Visit(visit_type="punch_out", job_id=dead.id, open_date=TODAY)
    db.add_all([keep, drop])
    db.commit()

    dead.status = JobStatus.void  # voided in CabinetTron after the visit existed
    db.commit()

    plan = plan_day(db, TODAY, real_drive=False)
    assert [s["visit_id"] for s in plan["stops"]] == [keep.id]  # dead job never routes

    generate_visits(db, TODAY)  # sync formally cancels it
    db.refresh(drop)
    assert drop.status == "canceled"
    assert "job closed/void" in drop.notes
    db.refresh(keep)
    assert keep.status == "pending"


def test_generate_skips_service_requests_on_dead_jobs(db):
    account, community = seed(db)
    job = make_job(db, account, community, status=JobStatus.closed)
    sr = ServiceRequest(job_id=job.id)
    db.add(sr)
    db.commit()
    created = generate_visits(db, TODAY)
    assert "service_t1" not in created and "warranty_t1" not in created


# ---------------------------------------------------------------- assignment

def make_worker(db, name, **kw):
    w = Worker(name=name, **kw)
    db.add(w)
    db.flush()
    return w


def test_salesperson_rule_measure_and_walk_on_local_sales(db):
    local = Account(name="Welch Homes", type=AccountType.builder)
    db.add(local)
    db.flush()
    community = Community(account_id=local.id, name="Welch", lat=30.7, lon=-86.1)
    db.add(community)
    db.flush()
    job = Job(
        account_id=local.id, community_id=community.id, address="1 Local Ln",
        job_type=JobType.custom, status=JobStatus.track, salesperson="Paula Cook",
        sales_contact_name="s", field_contact_name="f",
    )
    db.add(job)
    db.flush()
    make_worker(db, "Service Tech", is_tech=True, lat=31.2571, lon=-85.4035)
    paula = make_worker(db, "Paula Cook", sales_match="Paula")
    measure = Visit(visit_type="field_measure", job_id=job.id)
    walk = Visit(visit_type="post_walk", job_id=job.id)
    punch = Visit(visit_type="punch_out", job_id=job.id)
    db.add_all([measure, walk, punch])
    db.commit()

    counts = auto_assign(db)
    assert counts.get("Paula Cook") == 2
    assert measure.assigned_to == paula.id
    assert walk.assigned_to == paula.id
    assert punch.assigned_to is None  # the rest rides the truck (no territory match)


def test_national_jobs_assign_by_territory_not_seller(db):
    account, community = seed(db)  # DR Horton, community at (31.0, -85.6)
    job = make_job(db, account, community)
    job.salesperson = "Alex Talley"
    make_worker(db, "Service Tech", is_tech=True, lat=31.2571, lon=-85.4035)
    # Alex sells this national job but lives far away — neither rule applies.
    alex = make_worker(db, "Alex Talley", sales_match="Alex",
                       lat=30.4983, lon=-86.1361, radius_miles=30)
    # Brian's house sits right by the community — territory rule picks him up.
    brian = make_worker(db, "Brian Scobey", lat=31.01, lon=-85.61, radius_miles=30)
    v = Visit(visit_type="field_measure", job_id=job.id)
    far = Visit(visit_type="punch_out", job_id=make_job(db, account, community).id, lat=27.9, lon=-82.4)
    db.add_all([v, far])
    db.commit()

    auto_assign(db)
    assert v.assigned_to == brian.id      # national → territory, not the seller
    assert alex.id not in (v.assigned_to, far.assigned_to)
    assert far.assigned_to is None        # Tampa is in nobody's radius → tech pool


def test_manual_assignment_survives_auto_assign(db):
    account, community = seed(db)
    job = make_job(db, account, community)
    tech = make_worker(db, "Service Tech", is_tech=True)
    nearby = make_worker(db, "Brian Scobey", lat=31.0, lon=-85.6, radius_miles=30)
    v = Visit(visit_type="punch_out", job_id=job.id, assigned_to=tech.id)  # manually pinned
    db.add(v)
    db.commit()
    auto_assign(db)
    assert v.assigned_to == tech.id  # never overridden
    assert nearby.id != v.assigned_to


def test_punch_and_service_always_default_to_tech(db):
    account, community = seed(db)
    make_worker(db, "Service Tech", is_tech=True, lat=31.2571, lon=-85.4035)
    brian = make_worker(db, "Brian Scobey", lat=31.01, lon=-85.61, radius_miles=30)  # in radius
    punch = Visit(visit_type="punch_out", job_id=make_job(db, account, community).id)
    service = Visit(visit_type="service_t2", job_id=make_job(db, account, community).id)
    blue = Visit(visit_type="blue_tape", job_id=make_job(db, account, community).id)
    db.add_all([punch, service, blue])
    db.commit()

    auto_assign(db)
    assert punch.assigned_to is None    # punch rides the truck even inside a radius
    assert service.assigned_to is None  # so does service work
    assert blue.assigned_to == brian.id  # other duties still follow territory


def test_local_only_workers_never_get_national_work(db):
    account, community = seed(db)  # DR Horton at (31.0, -85.6)
    make_worker(db, "Service Tech", is_tech=True, lat=31.2571, lon=-85.4035)
    paula = make_worker(db, "Paula Cook", lat=31.01, lon=-85.61, radius_miles=30,
                        national_ok=False)  # right next door, but local-only

    local = Account(name="Welch Homes", type=AccountType.builder)
    db.add(local)
    db.flush()
    local_comm = Community(account_id=local.id, name="Welch", lat=31.02, lon=-85.62)
    db.add(local_comm)
    db.flush()
    local_job = Job(
        account_id=local.id, community_id=local_comm.id, address="9 Local Way",
        job_type=JobType.custom, status=JobStatus.blue,
        sales_contact_name="s", field_contact_name="f",
    )
    db.add(local_job)
    db.flush()

    national_visit = Visit(visit_type="blue_tape", job_id=make_job(db, account, community).id)
    local_visit = Visit(visit_type="blue_tape", job_id=local_job.id)
    db.add_all([national_visit, local_visit])
    db.commit()

    auto_assign(db)
    assert national_visit.assigned_to is None      # DR Horton work skips her
    assert local_visit.assigned_to == paula.id     # local work in her radius is fine


def test_duty_chart_beats_territory_and_can_pin_tech(db):
    account, community = seed(db)  # community at (31.0, -85.6)
    make_worker(db, "Service Tech", is_tech=True, lat=31.2571, lon=-85.4035)
    brian = make_worker(db, "Brian Scobey", lat=31.01, lon=-85.61, radius_miles=30)  # in radius
    alex = make_worker(db, "Alex Talley", lat=30.4983, lon=-86.1361, radius_miles=30)  # far away
    # The chart says: punch-outs here are Alex's, phase checks stay on the truck.
    db.add(DutyAssignment(community_id=community.id, duty="punch_out", worker_id=alex.id))
    db.add(DutyAssignment(community_id=community.id, duty="phase_check", worker_id=None))
    punch = Visit(visit_type="punch_out", job_id=make_job(db, account, community).id)
    phase = Visit(visit_type="phase_check", community_id=community.id)
    walk = Visit(visit_type="post_walk", job_id=make_job(db, account, community).id)
    db.add_all([punch, phase, walk])
    db.commit()

    auto_assign(db)
    assert punch.assigned_to == alex.id     # chart wins over Brian's radius
    assert phase.assigned_to is None        # chart pinned the truck — radius skipped
    assert walk.assigned_to == brian.id     # uncharted duty falls back to territory


def test_time_off_empties_their_day_and_truck_rescues_deadlines(db):
    account, community = seed(db)
    make_worker(db, "Service Tech", is_tech=True, lat=31.2571, lon=-85.4035)
    brian = make_worker(db, "Brian Scobey", lat=30.78, lon=-85.54, radius_miles=30)
    db.add(WorkerTimeOff(worker_id=brian.id, start_date=TODAY, end_date=TODAY + timedelta(days=3)))
    due_walk = Visit(visit_type="post_walk", job_id=make_job(db, account, community).id,
                     open_date=TODAY, close_date=TODAY, assigned_to=brian.id)
    loose_punch = Visit(visit_type="punch_out", job_id=make_job(db, account, community).id,
                        open_date=TODAY, assigned_to=brian.id)
    db.add_all([due_walk, loose_punch])
    db.commit()

    brians = plan_day(db, TODAY, real_drive=False, worker_id=brian.id)
    assert brians["time_off"] and brians["stops"] == []

    techs = plan_day(db, TODAY, real_drive=False)
    labels = [s["label"] for s in techs["stops"]]
    assert len(techs["stops"]) == 1                      # only the expiring deadline is rescued
    assert "covering for Brian Scobey" in labels[0]
    assert techs["stops"][0]["visit_id"] == due_walk.id  # the loose punch waits for Brian

    after = plan_day(db, TODAY + timedelta(days=4), real_drive=False, worker_id=brian.id)
    assert not after.get("time_off")                     # back to work after the range


def test_plan_for_worker_routes_from_their_home(db):
    account, community = seed(db)
    make_worker(db, "Service Tech", is_tech=True, lat=31.2571, lon=-85.4035)
    brian = make_worker(db, "Brian Scobey", lat=30.78, lon=-85.54, radius_miles=30)
    mine = make_job(db, account, community)
    his = make_job(db, account, community, address="2 His House Rd")
    db.add(Visit(visit_type="punch_out", job_id=mine.id, open_date=TODAY, assigned_to=brian.id))
    db.add(Visit(visit_type="punch_out", job_id=his.id, open_date=TODAY))  # tech pool
    db.commit()

    brians = plan_day(db, TODAY, real_drive=False, worker_id=brian.id)
    techs = plan_day(db, TODAY, real_drive=False)
    assert brians["worker"] == "Brian Scobey"
    assert brians["depot"] == {"lat": 30.78, "lon": -85.54}
    assert len(brians["stops"]) == 1
    assert techs["worker"] == "Service Tech"
    assert techs["depot"]["lat"] == 31.2571
    assert len(techs["stops"]) == 1  # only the unassigned pool visit
    assert brians["stops"][0]["visit_id"] != techs["stops"][0]["visit_id"]


# ---------------------------------------------------------------- API

def test_visit_api_crud_and_plan(client, db):
    make_user(db, role=Role.service_tech)
    headers = login(client, "user@example.com")
    account, community = seed(db)
    job = make_job(db, account, community, status=JobStatus.punch, po=2500)
    db.commit()

    resp = client.post(
        "/autobot/visits",
        json={"visit_type": "punch_out", "job_id": job.id, "open_date": TODAY.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    visit = resp.json()
    assert visit["duration_min"] == 60
    assert visit["has_location"]  # inherited the community pin

    resp = client.get("/autobot/visits", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get(f"/autobot/plan?day={TODAY.isoformat()}&real_drive=false", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["stops"]) == 1

    resp = client.patch(
        f"/autobot/visits/{visit['id']}", json={"status": "done"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["completed_by"] == "Test User"

    resp = client.get(f"/autobot/plan?day={TODAY.isoformat()}&real_drive=false", headers=headers)
    assert resp.json()["stops"] == []  # done visits leave the pool


def test_stop_detail_and_field_phase_logging(client, db):
    from app.models import PhaseUpdate

    make_user(db, role=Role.service_tech)
    headers = login(client, "user@example.com")
    account, community = seed(db)
    lot5 = make_job(db, account, community, lot_number="5", status=JobStatus.ord)
    lot12 = make_job(db, account, community, lot_number="12", status=JobStatus.track)
    db.add(PhaseUpdate(job_id=lot5.id, phase="4.2", noted_by="Office"))
    db.add(Visit(visit_type="phase_check", community_id=community.id, open_date=TODAY))
    db.commit()

    resp = client.get(f"/autobot/communities/{community.id}/detail", headers=headers)
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert [h["lot_number"] for h in detail["houses"]] == ["5", "12"]  # numeric lot order
    assert detail["houses"][0]["phase_label"] == "4.2 - Roof Complete"
    assert detail["houses"][1]["phase"] is None  # never logged
    assert len(detail["phases"]) == 18
    assert any(t["visit_type"] == "phase_check" for t in detail["tasks"])

    # Logging the SAME phase still writes a stamped row — "verified unchanged".
    for _ in range(2):
        resp = client.post(
            f"/autobot/jobs/{lot5.id}/phase", json={"phase": "4.2"}, headers=headers
        )
        assert resp.status_code == 201, resp.text
    logged = resp.json()
    assert logged["noted_by"] == "Test User"
    assert logged["noted_at"] is not None
    history = db.query(PhaseUpdate).filter(PhaseUpdate.job_id == lot5.id).all()
    assert len(history) == 3  # office row + two field confirmations
    assert history[-1].source == "autobot"

    resp = client.post(f"/autobot/jobs/{lot5.id}/phase", json={"phase": "99"}, headers=headers)
    assert resp.status_code == 422


def test_places_and_location(client, db):
    make_user(db, role=Role.admin, email="admin@example.com")
    headers = login(client, "admin@example.com")
    account, community = seed(db, community_coords=(None, None))
    make_job(db, account, community)
    db.commit()

    resp = client.get("/autobot/places", headers=headers)
    assert resp.status_code == 200
    place = resp.json()[0]
    assert place["active_houses"] == 1
    assert place["lat"] is None

    resp = client.patch(
        f"/autobot/communities/{community.id}/location",
        json={"lat": 31.25, "lon": -85.4},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["lat"] == 31.25


def test_autobot_is_tech_and_admin_only(client, db):
    # Office roles don't work in this arena — Autobot is closed to them.
    make_user(db, role=Role.sales, email="office@example.com")
    headers = login(client, "office@example.com")
    assert client.get("/autobot/visits", headers=headers).status_code == 403
    assert client.post("/autobot/generate", headers=headers).status_code == 403


def test_service_tech_sees_only_autobot(client, db):
    # The tech gets his piece and nothing else: no jobs, quotes, or reports API.
    make_user(db, role=Role.service_tech, email="tech@example.com")
    headers = login(client, "tech@example.com")
    assert client.get("/jobs", headers=headers).status_code == 403
    assert client.get("/accounts", headers=headers).status_code == 403
    assert client.get("/autobot/visits", headers=headers).status_code == 200
    assert client.get("/autobot/jobs", headers=headers).status_code == 200
    assert client.get("/autobot/places", headers=headers).status_code == 200
