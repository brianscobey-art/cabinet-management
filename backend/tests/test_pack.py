"""Order Pack (private mode inside Optimus) — Phase A.

Covers the two things Phase A has to get right: only Brian can see the page,
and the agent's folder scan makes the board reflect physical reality.
"""

from app.api.pack import _job_code_from_folder, _pick
from app.config import get_settings
from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account

OWNER = "brian.scobey@townsendbuildingsupply.com"
AGENT_HEADERS = {"X-Pack-Key": get_settings().orderpack_agent_key}


def setup_owner(client, db):
    make_user(db, email=OWNER, role=Role.admin)
    headers = login(client, OWNER)
    account_id, community_id = setup_account(client, headers, name="DR Horton Pensacola East")
    job = make_job(client, headers, account_id, community_id, job_code="DRID60-0115")
    return headers, job


# --------------------------------------------------------------------------
# Folder-name parsing
# --------------------------------------------------------------------------
def test_job_code_parsed_from_folder_names():
    assert _job_code_from_folder("DRID60-0115 CREE 081326") == "DRID60-0115"
    # Stage 3 appends " REVIEW" to a folder that failed the comparison.
    assert _job_code_from_folder("DRPREX-0112 CREE 081226 REVIEW") == "DRPREX-0112"
    # Century plan names carry spaces; the code is still the first token.
    assert _job_code_from_folder("CCGO-0014 CC Beaumont 36in STD 072126") == "CCGO-0014"
    # Housekeeping folders and pre-rename BUID folders are not jobs.
    assert _job_code_from_folder("Archive") is None
    assert _job_code_from_folder("227530042") is None
    assert _job_code_from_folder("") is None


def test_pick_takes_the_newest_matching_file():
    files = [
        "DRID60-0115 CREE PO 081326.PDF",
        "DRID60-0115 CREE PO 081426.PDF",
        "DRID60-0115 CREE Selections 081326.PDF",
        "DRID60-0115 CREE Installer Pay Sheet 081426.pdf",
    ]
    assert _pick(files, " PO ") == "DRID60-0115 CREE PO 081426.PDF"   # MMDDYY, not string order
    assert _pick(files, " Selections ") == "DRID60-0115 CREE Selections 081326.PDF"
    assert _pick(files, " Summary ") is None


# --------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------
def test_page_is_owner_only(client, db):
    make_user(db, email="someone@example.com", role=Role.admin)
    other = login(client, "someone@example.com")
    # An admin who isn't on the allowlist gets nothing — not even a hint.
    assert client.get("/ordering-platform/pack/board", headers=other).status_code == 403
    assert client.get("/ordering-platform/pack/meta", headers=other).status_code == 403
    assert client.get("/ordering-platform/pack/board").status_code == 401

    headers, _ = setup_owner(client, db)
    assert client.get("/ordering-platform/pack/board", headers=headers).status_code == 200


def test_agent_endpoints_need_the_shared_secret(client, db):
    assert client.post("/ordering-platform/pack/agent/heartbeat").status_code == 403
    bad = client.post("/ordering-platform/pack/agent/heartbeat", headers={"X-Pack-Key": "nope"})
    assert bad.status_code == 403
    ok = client.post("/ordering-platform/pack/agent/heartbeat", headers=AGENT_HEADERS)
    assert ok.status_code == 200 and ok.json()["ok"] is True


# --------------------------------------------------------------------------
# The scan — the whole point of Phase A
# --------------------------------------------------------------------------
def test_scan_puts_the_job_where_its_folder_actually_is(client, db):
    headers, job = setup_owner(client, db)

    payload = {
        "agent_version": "test",
        "stages": {
            "stage3": [{
                "folder": "DRID60-0115 CREE 081326",
                "files": [
                    "DRID60-0115 CREE PO 081326.PDF",
                    "DRID60-0115 CREE Selections 081326.PDF",
                    "DRID60-0115 CREE Summary 081326.PDF",
                    "DRID60-0115 CREE SO46119 081426.pdf",
                ],
            }],
            "stage1": [{"folder": "DRNOPE-9999 XXXX 081326", "files": []}],
        },
        "loose_files": {"stage4": ["Purchase Order 750005026.pdf"]},
    }
    summary = client.post("/ordering-platform/pack/agent/scan",
                          headers=AGENT_HEADERS, json=payload).json()
    assert summary["matched"] == 1
    assert [u["folder"] for u in summary["unmatched"]] == ["DRNOPE-9999 XXXX 081326"]

    row = next(r for r in client.get("/ordering-platform/pack/board", headers=headers).json()
               if r["job_id"] == job["id"])
    assert row["current_folder"] == "stage3"
    assert row["folder_name"] == "DRID60-0115 CREE 081326"
    assert row["plan_abbr"] == "CREE"
    assert row["po_file"] == "DRID60-0115 CREE PO 081326.PDF"
    assert row["summary_file"] == "DRID60-0115 CREE Summary 081326.PDF"
    assert len(row["folder_files"]) == 4
    assert row["review"] is False
    assert row["last_scan_at"] is not None


def test_review_suffix_surfaces_and_a_vanished_folder_is_flagged(client, db):
    headers, job = setup_owner(client, db)
    base = {"loose_files": {}}

    client.post("/ordering-platform/pack/agent/scan", headers=AGENT_HEADERS,
                json={**base, "stages": {"stage3": [
                    {"folder": "DRID60-0115 CREE 081326 REVIEW", "files": []}]}})
    row = client.get("/ordering-platform/pack/board", headers=headers).json()[0]
    assert row["review"] is True

    # Next scan, the folder is gone and stage 4 never completed: that's not
    # "done", that's "someone moved it" — and Brian needs to see it.
    summary = client.post("/ordering-platform/pack/agent/scan", headers=AGENT_HEADERS,
                          json={**base, "stages": {"stage3": []}}).json()
    assert summary["left_the_chain"] == 1
    row = client.get("/ordering-platform/pack/board", headers=headers).json()[0]
    assert row["current_folder"] == "missing"

    exceptions = client.get("/ordering-platform/pack/board?exceptions_only=false",
                            headers=headers).json()
    assert any(r["current_folder"] == "missing" for r in exceptions)


def test_scan_never_touches_optimus_steps_or_status(client, db):
    """Phase A reports physical reality; it must not move the job through the
    1.2->2.0 ladder or stamp Optimus sub-steps."""
    headers, job = setup_owner(client, db)
    before = client.get(f"/jobs/{job['id']}", headers=headers).json()["status"]
    steps_before = client.get("/ordering-platform/board", headers=headers).json()

    client.post("/ordering-platform/pack/agent/scan", headers=AGENT_HEADERS, json={
        "stages": {"stage4": [{"folder": "DRID60-0115 CREE 081326", "files": []}]},
        "loose_files": {},
    })
    after = client.get(f"/jobs/{job['id']}", headers=headers).json()["status"]
    assert after == before
    steps_after = client.get("/ordering-platform/board", headers=headers).json()
    assert [r["steps"] for r in steps_after] == [r["steps"] for r in steps_before]


# --------------------------------------------------------------------------
# The run queue
# --------------------------------------------------------------------------
def test_run_queue_round_trip(client, db):
    headers, _ = setup_owner(client, db)

    run = client.post("/ordering-platform/pack/runs", headers=headers,
                      json={"kind": "scan"}).json()
    assert run["status"] == "queued" and run["requested_by"] == OWNER

    # A second request doesn't stack identical work.
    again = client.post("/ordering-platform/pack/runs", headers=headers,
                        json={"kind": "scan"}).json()
    assert again["id"] == run["id"]

    # Stages aren't built yet — refuse clearly rather than queueing a no-op.
    blocked = client.post("/ordering-platform/pack/runs", headers=headers,
                          json={"kind": "stage4"})
    assert blocked.status_code == 409

    claimed = client.get("/ordering-platform/pack/agent/runs/next", headers=AGENT_HEADERS).json()
    assert claimed["id"] == run["id"] and claimed["status"] == "running"
    assert client.get("/ordering-platform/pack/agent/runs/next",
                      headers=AGENT_HEADERS).json() is None  # nothing left to claim

    client.post(f"/ordering-platform/pack/agent/runs/{run['id']}/log",
                headers=AGENT_HEADERS, json={"line": "3. SOs and Order Comparison: 12 job folders"})
    client.post(f"/ordering-platform/pack/agent/runs/{run['id']}/finish",
                headers=AGENT_HEADERS, json={"status": "done", "result": {"matched": 12}})

    done = client.get(f"/ordering-platform/pack/runs/{run['id']}", headers=headers).json()
    assert done["status"] == "done"
    assert "12 job folders" in done["log"]
    assert done["result"] == {"matched": 12}
    assert done["finished_at"] is not None


def test_install_pay_is_typed_never_invented(client, db):
    headers, job = setup_owner(client, db)
    row = client.patch(f"/ordering-platform/pack/jobs/{job['id']}", headers=headers,
                       json={"install_pay": "425.00", "notes": "read off the pay sheet"}).json()
    assert str(row["install_pay"]) == "425.00"
    assert row["notes"] == "read off the pay sheet"

    cleared = client.patch(f"/ordering-platform/pack/jobs/{job['id']}", headers=headers,
                           json={"exception": None}).json()
    assert cleared["exception"] is None
