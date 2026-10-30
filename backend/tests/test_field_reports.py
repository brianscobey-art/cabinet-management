from datetime import date, datetime, timedelta, timezone

from app.field_reports import sync_install_reports, sync_qc_reports
from app.models import InstallReport, PhaseUpdate, QcReport, Role, ServicePart, Visit
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account

TODAY = date(2026, 10, 30)


def _jobs(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    a = make_job(client, headers, account_id, community_id, job_code="DRT-0001")
    b = make_job(client, headers, account_id, community_id, job_code="DRT-0002", lot_number="43")
    c = make_job(client, headers, account_id, community_id, job_code="DRT-0003", lot_number="44")
    return headers, a, b, c


def test_install_reports_phase_clock_parts_once(client, db):
    headers, done, short, old = _jobs(client, db)
    recent = (TODAY - timedelta(days=1)).isoformat()
    rows = [
        (1, {"Job Code": "DRT-0001", "Install Date": recent, "Installer": "SNE Services LLC - Eddie",
             "Job Complete?": "Yes", "Damage or Parts Needed?": "No", "Sticks of Shoe on Site": 6.0,
             "Submitted": f"{recent}T23:00:00Z"}),
        (2, {"Job Code": "DRT-0002", "Install Date": recent, "Installer": "MJ Installers - Jacobs",
             "Job Complete?": "No", "Trade Stopping?": "Yes", "What Is Needed to Finish?": "Base 36 drawer front",
             "Damage or Parts Needed?": "Yes", "Damage / Parts Detail": "Door w 36x36"}),
        (3, {"Job Code": "DRT-0003", "Install Date": "2026-08-20", "Job Complete?": "Yes",
             "Damage or Parts Needed?": "Yes", "Damage / Parts Detail": "Shelf pins 4"}),  # backlog
        (4, {"Job Code": "NOPE-1", "Job Complete?": "Yes"}),
    ]
    out = sync_install_reports(db, rows, today=TODAY)
    db.commit()
    assert out == {"rows": 4, "new": 4, "acted": 3, "unmatched": 1}

    phases = {p.job_id: p.phase for p in db.query(PhaseUpdate).all()}
    assert phases == {done["id"]: "12", old["id"]: "12"}  # incomplete install doesn't get 12
    walk = db.query(Visit).filter(Visit.job_id == done["id"], Visit.visit_type == "post_walk").one()
    assert walk.open_date == TODAY - timedelta(days=1) and walk.status == "pending"
    parts = db.query(ServicePart).all()
    assert sorted(p.part for p in parts) == ["Base 36 drawer front", "Door w 36x36"]  # backlog parts skipped
    assert all(p.trade_blocking and p.found_on == "install" for p in parts)

    # a second read (Smartsheet row edited) never re-fires the actions
    sync_install_reports(db, rows, today=TODAY)
    db.commit()
    assert db.query(ServicePart).count() == 2 and db.query(PhaseUpdate).count() == 2

    card = client.get(f"/jobs/{short['id']}/field-reports", headers=headers).json()
    assert card["install_reports"][0]["needed_to_finish"] == "Base 36 drawer front"
    assert "2 part(s)" in card["install_reports"][0]["actions"]


def test_qc_reports_become_post_walk_history(client, db):
    headers, a, b, _ = _jobs(client, db)
    db.add(Visit(visit_type="post_walk", job_id=b["id"], status="done"))  # b already walked in Autobot
    db.commit()
    rows = [
        (10, {"PWID": "133.0", "Created By": "alex.talley@example.com", "Created": "2026-08-21T18:51:51Z",
              "Job Code": "DRT-0001", "Are the critical Dimensions good?": "Yes",
              "Are there service issues to address?": "Yes", "Repair or Replace": "Repair",
              "What's the damage?": "Right vanity paint chipped", "Island Pull - Fridge Side": "NA"}),
        (11, {"PWID": "170.0", "Job Code": "DRT-0002", "Created": "2026-09-28T15:50:50Z",
              "Are there service issues to address?": "No"}),
    ]
    out = sync_qc_reports(db, rows)
    db.commit()
    assert out == {"rows": 2, "new": 2, "post_walks_added": 1, "unmatched": 0}
    v = db.query(Visit).filter(Visit.job_id == a["id"], Visit.visit_type == "post_walk").one()
    assert v.status == "done" and v.result == "issues" and "paint chipped" in v.result_notes
    assert db.get(QcReport, 11).visit_id is None  # b keeps its Autobot post walk
    sync_qc_reports(db, rows)
    db.commit()
    assert db.query(Visit).filter(Visit.visit_type == "post_walk").count() == 2
