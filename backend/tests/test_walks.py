"""Post walk, full punch, blue tape and parts — the house's walk-through record
in Autobot, and the punch board the office reads."""
from datetime import date, timedelta

from app.autobot import BLUE_TAPE_DAYS, POST_WALK_DAYS, PUNCH_AFTER_DAYS, generate_visits, house_board
from app.models import JobStatus, Role, ServicePart, ServiceRequest, Visit
from tests.conftest import login, make_user
from tests.test_autobot import TODAY, make_job, seed


def _tech(client, db):
    make_user(db, role=Role.service_tech, email="tech@example.com")
    return login(client, "tech@example.com")


def test_post_walk_and_punch_spawn_from_the_install_date(db):
    account, community = seed(db)
    fresh = make_job(db, account, community, status=JobStatus.inst,
                     install_date=TODAY - timedelta(days=1))
    old = make_job(db, account, community, status=JobStatus.ndqw,
                   install_date=TODAY - timedelta(days=40))
    db.commit()

    generate_visits(db, TODAY)

    pw = db.query(Visit).filter(Visit.visit_type == "post_walk", Visit.job_id == fresh.id).one()
    assert pw.open_date == fresh.install_date
    assert pw.close_date == fresh.install_date + timedelta(days=POST_WALK_DAYS)
    # a 40-day-old install has no live 48-hour clock
    assert db.query(Visit).filter(Visit.visit_type == "post_walk", Visit.job_id == old.id).count() == 0
    # 2.1-Inst with a date is not yet "installed" for punch purposes; 3.0 and up is
    assert db.query(Visit).filter(Visit.visit_type == "punch_out", Visit.job_id == fresh.id).count() == 0
    punch = db.query(Visit).filter(Visit.visit_type == "punch_out", Visit.job_id == old.id).one()
    assert punch.open_date == old.install_date + timedelta(days=PUNCH_AFTER_DAYS)


def test_finish_a_visit_and_a_return_trip(client, db):
    account, community = seed(db)
    job = make_job(db, account, community, status=JobStatus.punch,
                   install_date=TODAY - timedelta(days=20))
    db.commit()
    headers = _tech(client, db)
    generate_visits(db, TODAY)
    punch = db.query(Visit).filter(Visit.visit_type == "punch_out").one()

    # couldn't finish: the return date spawns trip 2, pinned to that day
    back = TODAY + timedelta(days=3)
    r = client.post(f"/autobot/visits/{punch.id}/complete", headers=headers,
                    json={"result": "incomplete", "notes": "two doors rubbing", "return_date": back.isoformat()})
    assert r.status_code == 200, r.text
    first, follow = r.json()
    assert first["status"] == "done" and first["result"] == "incomplete"
    assert follow["status"] == "pending" and follow["trip"] == 2
    assert follow["parent_visit_id"] == first["id"]
    assert follow["scheduled_date"] == back.isoformat() and follow["close_date"] == back.isoformat()

    # a result that didn't finish needs a return date
    r = client.post(f"/autobot/visits/{follow['id']}/complete", headers=headers,
                    json={"result": "no_access"})
    assert r.status_code == 422

    # trip 2 done: the house shows the punch complete
    r = client.post(f"/autobot/visits/{follow['id']}/complete", headers=headers,
                    json={"result": "complete", "photos_url": "https://example/photos/1"})
    assert r.status_code == 200
    assert r.json()[0]["photos_url"] == "https://example/photos/1"
    walks = client.get(f"/autobot/jobs/{job.id}/walks", headers=headers).json()
    assert [w["trip"] for w in walks] == [1, 2]


def test_blue_tape_request_is_due_by_the_closing_date(client, db):
    account, community = seed(db)
    job = make_job(db, account, community, status=JobStatus.punch,
                   install_date=TODAY - timedelta(days=60))
    db.commit()
    headers = _tech(client, db)

    closing = TODAY + timedelta(days=9)
    r = client.post(f"/autobot/jobs/{job.id}/blue-tape", headers=headers,
                    json={"requested_on": TODAY.isoformat(), "closing_date": closing.isoformat()})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["visit_type"] == "blue_tape" and v["closing_date"] == closing.isoformat()
    assert v["close_date"] == closing.isoformat()
    db.expire_all()
    assert db.get(type(job), job.id).status == JobStatus.blue

    # no closing date yet: four days after the request
    job2 = make_job(db, account, community, status=JobStatus.punch, install_date=TODAY - timedelta(days=30))
    db.commit()
    r = client.post(f"/autobot/jobs/{job2.id}/blue-tape", headers=headers, json={})
    assert r.json()["close_date"] == (TODAY_or_today() + timedelta(days=BLUE_TAPE_DAYS)).isoformat()


def TODAY_or_today():
    return date.today()


def test_parts_ride_on_one_ticket_and_count_on_the_board(client, db):
    account, community = seed(db)
    job = make_job(db, account, community, status=JobStatus.ndqw,
                   install_date=TODAY - timedelta(days=3))
    db.commit()
    headers = _tech(client, db)

    r = client.post(f"/autobot/jobs/{job.id}/parts", headers=headers,
                    json={"part": "L-Door", "cabinet": "W3636", "qty": 1, "reason": "damaged",
                          "found_on": "post_walk", "install_by": "tech"})
    assert r.status_code == 201, r.text
    p1 = r.json()
    assert p1["state"] == "needs_order"
    r = client.post(f"/autobot/jobs/{job.id}/parts", headers=headers,
                    json={"part": "Toe kick", "qty": 2, "reason": "missing", "found_on": "post_walk"})
    p2 = r.json()
    assert p2["service_request_id"] == p1["service_request_id"]   # one Parts ticket per house
    assert db.query(ServiceRequest).filter(ServiceRequest.job_id == job.id).count() == 1
    db.expire_all()
    assert db.get(type(job), job.id).status == JobStatus.parts

    # ordered -> received -> installed, with cost and who pays
    r = client.patch(f"/autobot/parts/{p1['id']}", headers=headers,
                     json={"order_number": "EV1234", "order_date": TODAY.isoformat(),
                           "due_date": (TODAY + timedelta(days=10)).isoformat(),
                           "cost": 48.5, "who_pays": "installer"})
    assert r.json()["state"] == "ordered" and r.json()["cost"] == 48.5
    r = client.patch(f"/autobot/parts/{p1['id']}", headers=headers, json={"received": True})
    assert r.json()["state"] == "received"
    r = client.patch(f"/autobot/parts/{p1['id']}", headers=headers,
                     json={"installed_at": TODAY.isoformat()})
    assert r.json()["state"] == "installed" and r.json()["installed_by"]

    board = house_board(db, TODAY)
    row = next(b for b in board if b["job_id"] == job.id)
    assert row["open_parts"] == 1          # the toe kick is still open
    assert db.query(ServicePart).count() == 2


def test_punch_board_walks_a_house_through_its_steps(client, db):
    account, community = seed(db)
    job = make_job(db, account, community, status=JobStatus.ndqw, address="7 Board Ln",
                   install_date=TODAY - timedelta(days=1), g_code="G1", i_code="I1")
    db.commit()
    headers = _tech(client, db)
    generate_visits(db, TODAY)

    def status():
        row = next(b for b in house_board(db, TODAY) if b["job_id"] == job.id)
        return row["house_status"], row

    st, row = status()
    assert st == "Post walk due" and row["g_code"] == "G1" and row["punch"]["open_date"]

    pw = db.query(Visit).filter(Visit.visit_type == "post_walk").one()
    client.post(f"/autobot/visits/{pw.id}/complete", headers=headers,
                json={"result": "issues", "notes": "scratched door", "completed_on": TODAY.isoformat()})
    st, _ = status()
    assert st == "Punch coming up"               # window opens at install + 14

    # the window opened, no date from the super yet -> ask
    later = TODAY + timedelta(days=PUNCH_AFTER_DAYS + 1)
    assert next(b for b in house_board(db, later) if b["job_id"] == job.id)["house_status"] == "REQUEST PUNCH"

    client.post(f"/autobot/jobs/{job.id}/punch-request", headers=headers,
                json={"requested_on": later.isoformat()})
    assert next(b for b in house_board(db, later) if b["job_id"] == job.id)["house_status"] == "Punch requested"
    sched = later + timedelta(days=2)
    client.post(f"/autobot/jobs/{job.id}/punch-request", headers=headers,
                json={"confirmed_with": "Super Bob", "scheduled_date": sched.isoformat()})
    assert next(b for b in house_board(db, later) if b["job_id"] == job.id)["house_status"] == "Punch scheduled"

    punch = db.query(Visit).filter(Visit.visit_type == "punch_out", Visit.status == "pending").one()
    client.post(f"/autobot/visits/{punch.id}/complete", headers=headers,
                json={"result": "complete", "completed_on": sched.isoformat()})
    assert next(b for b in house_board(db, sched) if b["job_id"] == job.id)["house_status"] == "Waiting on blue tape"

    closing = sched + timedelta(days=40)
    client.post(f"/autobot/jobs/{job.id}/blue-tape", headers=headers,
                json={"requested_on": (closing - timedelta(days=5)).isoformat(), "closing_date": closing.isoformat()})
    assert next(b for b in house_board(db, closing - timedelta(days=5)) if b["job_id"] == job.id)["house_status"] == "Blue tape requested"
    assert next(b for b in house_board(db, closing + timedelta(days=1)) if b["job_id"] == job.id)["house_status"] == "BLUE TAPE OVERDUE"
    blue = db.query(Visit).filter(Visit.visit_type == "blue_tape").one()
    client.post(f"/autobot/visits/{blue.id}/complete", headers=headers,
                json={"result": "complete", "completed_on": closing.isoformat()})
    assert next(b for b in house_board(db, closing) if b["job_id"] == job.id)["house_status"] == "Done"

    # the office reads the same board through the API
    make_user(db, role=Role.sales, email="office@example.com")
    r = client.get("/autobot/punch-board", headers=login(client, "office@example.com"))
    assert r.status_code == 200 and any(b["job_id"] == job.id for b in r.json())
