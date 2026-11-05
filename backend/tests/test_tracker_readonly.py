"""The 3.0 Online Sales Tracker is a read-only export of CabinetTron's status now
(Brian 11/5/26). Its import never moves an existing job's CONST LVL or dates;
a difference goes on the job's timeline once."""

from datetime import date, datetime

from app.models import Job, JobEvent, JobStatus
from scripts.import_tracker import run_sync
from tests.test_pack import setup_owner


def _row(code, **over):
    return {"Job Code": code, "CONST LVL": None, "Actual Install Date": None,
            "Requested Install Date": None, "Actual Measure Date": None, **over}


def _events(db, kind="tracker_disagrees"):
    return db.query(JobEvent).filter(JobEvent.kind == kind).order_by(JobEvent.id).all()


def test_tracker_status_never_overwrites_cabinettron(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.status = JobStatus.ordsub
    db.commit()
    counts = run_sync(db, [_row(job.job_code, **{"CONST LVL": "2.0-Ord"})])
    db.commit()
    assert job.status is JobStatus.ordsub
    assert counts["disagreements"] == 1
    ev = _events(db)[0]
    assert ev.level == "warn"
    assert "Tracker CONST LVL is 2.0-Ord, CabinetTron has 1.4-OrdSub" in ev.issues[0]


def test_same_disagreement_is_logged_once(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.status = JobStatus.ordsub
    db.commit()
    for _ in range(3):
        counts = run_sync(db, [_row(job.job_code, **{"CONST LVL": "2.0-Ord"})])
        db.commit()
    assert counts["disagreements"] == 1  # still counted every sync
    assert len(_events(db)) == 1          # but logged once
    job.status = JobStatus.ordpo          # CabinetTron moves on, tracker still stale
    db.commit()
    run_sync(db, [_row(job.job_code, **{"CONST LVL": "2.0-Ord"})])
    db.commit()
    assert len(_events(db)) == 2


def test_matching_tracker_logs_nothing(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    counts = run_sync(db, [_row(job.job_code, **{"CONST LVL": job.status.value})])
    db.commit()
    assert counts["disagreements"] == 0
    assert _events(db) == []


def test_tracker_fills_blank_dates_but_flags_different_ones(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.install_date = None
    job.measure_date = date(2026, 10, 1)
    db.commit()
    run_sync(db, [_row(job.job_code, **{"Actual Install Date": datetime(2026, 11, 20),
                                         "Actual Measure Date": datetime(2026, 10, 3)})])
    db.commit()
    assert job.install_date == date(2026, 11, 20)  # blank, so filled
    assert job.measure_date == date(2026, 10, 1)   # set, so kept
    ev = _events(db)[0]
    assert ev.payload["tracker"] == {"measure_date": "2026-10-03"}


def test_tracker_closed_does_not_close_an_open_job(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.status = JobStatus.inst
    db.commit()
    run_sync(db, [_row(job.job_code, **{"CONST LVL": "6.0-Clsd"})])
    db.commit()
    assert job.status is JobStatus.inst


def test_new_tracker_job_is_seeded_once(client, db):
    setup_owner(client, db)
    counts = run_sync(db, [_row("DRID60-0199", **{"CONST LVL": "1.2-NdOrd", "Full Builder": "DR Horton",
                                                 "Community": "Cree", "Lot #": 199})])
    db.commit()
    assert counts["imported"] == 1
    job = db.query(Job).filter(Job.job_code == "DRID60-0199").one()
    assert job.status is JobStatus.ndord
    assert [e.status_to for e in _events(db, "tracker_seeded")] == ["1.2-NdOrd"]


def test_status_live_csv_exports_const_lvl(client, db):
    _, j = setup_owner(client, db)
    from app.api.reports import TRACKER_EXPORT_KEY
    from app.models import set_setting

    set_setting(db, TRACKER_EXPORT_KEY, "tok")
    db.commit()
    assert client.get("/reports/status/live.csv?token=bad").status_code == 404
    body = client.get("/reports/status/live.csv?token=tok").text
    lines = body.strip().splitlines()
    assert lines[0] == "Job Code,CONST LVL,Install Date,Measure Date,Builder PO,Pulled"
    assert any(ln.startswith(j["job_code"] + ",") for ln in lines[1:])
