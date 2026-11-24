"""Account Code Match -- Brian's test cases from the 11/23/26 data (11/24/26)."""
from datetime import date

from app import account_codes as ac
from app.config import get_settings
from app.models import AccountCodeFlag, Job, Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account

ACCOUNTS = [
    "G7550228-006: Paul Davis - CAB PDAG0556", "I7550228-004: Paul Davis - CAB PDAG0556",
    "G7550228-008: Paul Davis - CAB PDGI2553", "I7550228-006: Paul Davis - CAB PDGI2553",
    "G7510189-002: Quintessential - CAB QUGR3650", "I7510189-001: Quintessential - CAB QUGR3650",
    "G7510189-003: Quintessential - CAB QUWS0241", "I7510189-002: Quintessential - CAB QUWS0241",
    "I7510082-002: Vickers - CAB SVCC0225", "I7510082-001: Vickers - CAB SVCC0229",
    "G7510082-016: Vickers - CAB SVCC3160", "I7510082-004: Vickers - CAB SVCC3160",
    "G7500042-120: Jubilee - CAB JBBA3303", "I7500042-038: Jubilee - CAB JBBA3303",
    "G750-000-023: Quick Installed Sales - CAB TRAN1506", "I750-000-022: Quick Installed Sales - CAB TRAN1506",
    "I7550079-004: Holley - CAB HOFL0300", "G7550079-016: Holley - CAB HOFL0300",
    "G7550241-008: Grantham - CAB MGJO2142", "G7550241-009: Grantham - CAB MGPR1482",
    "G7500107-002: Barron Construction LLC - Guffy Job",
]
JOBS = {  # job code: (I-code, G-code) as stored on 11/23
    "PDAG0556": ("I7550228-004", "G7550228-006"),
    "PDGI2553": ("7550228-006", "G7550228-008"),
    "QUGR3650": ("7510189-001", "7510189-002"),
    "QUWS0241": ("7510189-002", "G7510189-0103"),
    "SVCC0225": ("I7510082-001", None),
    "SVCC0229": ("I7510082-002", None),
    "SVCC3160": (None, None),
    "JBBA3303": ("I7500042-038", "G7500042-0120"),
    "TRAN1506": ("I750-000-022", "G750-00-023"),
    "HOFL0200": ("I7550079-004", None),
    "MGJO2142": (None, "G7550241-008"),
    "MGPR1482": (None, "G7550241-008"),
    "GUFF-0001": ("G7500107-002", "G7500107-002"),
}
SETUPS = [{"g_account": "G7550228-006", "i_account": "I7550228-004", "ashley_code": "CAB PDAG0556"},
          {"g_account": "G7510189-002", "i_account": "I7510189-001", "ashley_code": "CAB QUGR3650"}]


def _accounts():
    text = "Job Account\n" + "\n".join(f'"{a}"' for a in ACCOUNTS) + "\n"
    return ac.parse_accounts(text, "test")


def _problems():
    jobs = [{"job_id": None, "job_code": c, "i_code": i, "g_code": g, "ashley": None} for c, (i, g) in JOBS.items()]
    out = {}
    for p in ac.find_problems(jobs, _accounts(), SETUPS):
        out.setdefault(p["job_code"], []).append(p)
    return out


def _one(probs, code, field):
    hits = [p for p in probs.get(code, []) if p["field"] == field]
    assert len(hits) == 1, (code, field, hits)
    return hits[0]


def test_keys_and_near_codes():
    assert ac.job_key("BURN-0104.2") == ac.job_key("burn01042")
    assert ac.near_code("G7500042-0120", "G7500042-120")
    assert ac.near_code("G750-00-023", "G750-000-023")
    assert ac.near_code("G7510189-0103", "G7510189-003")
    assert not ac.near_code("G7510189-003", "G7510189-003")
    assert not ac.near_code("G7510189-003", "G7510189-012")


def test_brians_cases():
    p = _problems()
    assert "PDAG0556" not in p  # matches DOMO

    x = _one(p, "PDGI2553", "I")
    assert x["flag"] == "No prefix" and x["domo"] == "I7550228-006" and "PDAG0556" in x["detail"]
    assert _one(p, "PDGI2553", "-")["flag"] == "No setup request"

    x = _one(p, "QUGR3650", "G")
    assert x["flag"] == "No prefix" and x["domo"] == "G7510189-002" and "QUWS0241" in x["detail"]
    assert _one(p, "QUGR3650", "I")["flag"] == "No prefix"
    assert not [q for q in p["QUGR3650"] if q["field"] == "-"]  # has a setup request

    assert _one(p, "QUWS0241", "I")["flag"] == "No prefix"
    x = _one(p, "QUWS0241", "G")
    assert x["flag"] == "Digit difference" and x["domo"] == "G7510189-003"

    x = _one(p, "SVCC0225", "I")
    assert x["flag"] == "Belongs to another job" and x["domo"] == "I7510082-002" and "SVCC0229" in x["detail"]
    assert _one(p, "SVCC0229", "I")["domo"] == "I7510082-001"

    assert {(q["field"], q["flag"], q["domo"]) for q in p["SVCC3160"] if q["field"] != "-"} == {
        ("I", "Missing code", "I7510082-004"), ("G", "Missing code", "G7510082-016")}

    x = _one(p, "JBBA3303", "G")
    assert x["flag"] == "Digit difference" and x["domo"] == "G7500042-120"
    x = _one(p, "TRAN1506", "G")
    assert x["flag"] == "Digit difference" and x["domo"] == "G750-000-023"

    x = _one(p, "HOFL0200", "I")
    assert x["flag"] == "Name mismatch" and x["domo"] is None and "HOFL0300" in x["detail"]

    x = _one(p, "MGPR1482", "G")
    assert x["flag"] == "Belongs to another job" and x["domo"] == "G7550241-009" and "MGJO2142" in x["detail"]
    assert "MGJO2142" not in p

    x = _one(p, "GUFF-0001", "I")
    assert x["flag"] == "Wrong prefix"
    assert not [q for q in p["GUFF-0001"] if q["field"] == "G"]  # non-CAB account, nothing to check against


def test_run_tracks_flags_and_fix(client, db, monkeypatch):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    jb = make_job(client, headers, account_id, community_id, job_code="JBBA3303")
    client.patch(f"/jobs/{jb['id']}", headers=headers, json={"g_code": "G7500042-0120", "i_code": "I7500042-038"})
    monkeypatch.setattr(get_settings(), "po_lines_ingest_token", "t0ken")
    tok = {"X-Ingest-Token": "t0ken"}
    text = "Job Account\n" + "\n".join(f'"{a}"' for a in ACCOUNTS) + "\n"
    assert client.post("/feeds/ingest/job-accounts", content=text, headers=tok).json()["accounts"] == len(ACCOUNTS)
    # jobs-snapshot is refused outside the test copy
    assert client.post("/feeds/ingest/jobs-snapshot", content="Job Code\nX\n", headers=tok).status_code == 403

    out = ac.run(db, today=date(2026, 11, 23))
    assert out["new"] == 1 and out["open"] == 1
    rep = client.get("/reports/code-check", headers=headers).json()
    (f,) = rep["flags"]
    assert f["flag"] == "Digit difference" and f["domo_code"] == "G7500042-120" and f["can_fix"]

    # a re-run the next day keeps it open, not new
    out = ac.run(db, today=date(2026, 11, 24))
    assert out["new"] == 0 and out["new_since_yesterday"] == 0 and out["open"] == 1

    r = client.post(f"/reports/code-check/{f['id']}/fix", headers=headers)
    assert r.status_code == 200, r.text
    assert db.get(Job, jb["id"]).g_code == "G7500042-120"
    out = ac.run(db, today=date(2026, 11, 25))
    assert out["open"] == 0
    assert db.get(AccountCodeFlag, f["id"]).status == "fixed"


def test_fixed_in_the_record_closes_itself(client, db, monkeypatch):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    jb = make_job(client, headers, account_id, community_id, job_code="MGPR1482")
    client.patch(f"/jobs/{jb['id']}", headers=headers, json={"g_code": "G7550241-008"})
    monkeypatch.setattr(get_settings(), "po_lines_ingest_token", "t0ken")
    text = "Job Account\n" + "\n".join(f'"{a}"' for a in ACCOUNTS) + "\n"
    client.post("/feeds/ingest/job-accounts", content=text, headers={"X-Ingest-Token": "t0ken"})
    ac.run(db, today=date(2026, 11, 23))
    (f,) = db.query(AccountCodeFlag).all()
    assert f.flag == "Belongs to another job"

    # someone fixes the job by hand (Alex): the next run marks the flag Fixed
    client.patch(f"/jobs/{jb['id']}", headers=headers, json={"g_code": "G7550241-009"})
    out = ac.run(db, today=date(2026, 11, 24))
    db.refresh(f)
    assert out["fixed"] == 1 and f.status == "fixed" and f.resolved_by == "matches DOMO"

    # Ignored stays ignored even when the problem comes back
    client.patch(f"/jobs/{jb['id']}", headers=headers, json={"g_code": "G7550241-008"})
    ac.run(db, today=date(2026, 11, 25))
    db.refresh(f)
    assert f.status == "open" and f.first_seen == date(2026, 11, 25)
    client.post(f"/reports/code-check/{f.id}/status", headers=headers, json={"status": "ignored"})
    ac.run(db, today=date(2026, 11, 26))
    db.refresh(f)
    assert f.status == "ignored"
