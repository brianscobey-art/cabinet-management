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
    client.patch(f"/jobs/{job['id']}", headers=headers, json={"status": "1.5-OrdPO"})
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

    # Stages 1-3 aren't built yet — refuse clearly rather than queueing a no-op.
    blocked = client.post("/ordering-platform/pack/runs", headers=headers,
                          json={"kind": "stage1"})
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


# --------------------------------------------------------------------------
# Stage 4 — the dollar gate and what it's allowed to stamp
# --------------------------------------------------------------------------
def _stage4(client, results):
    return client.post("/ordering-platform/pack/agent/stage4/apply",
                       headers=AGENT_HEADERS, json={"results": results}).json()


def test_stage4_success_files_the_job_and_walks_the_optimus_ladder(client, db):
    headers, job = setup_owner(client, db)
    client.patch(f"/jobs/{job['id']}", headers=headers, json={"status": "1.5-OrdPO"})

    summary = _stage4(client, [{
        "job_code": "DRID60-0115",
        "folder": "DRID60-0115 CREE 081326",
        "so_number": "SO46119",
        "carter_po_number": "750005026",
        "carter_po_total": "12345.67",
        "so_total": "12345.67",
        "sub_number": "22733",
        "installer_pay_sheet": True,
        "install_pay": "383.00",
        "moved_to_sold": True,
        "outcome": "ok",
    }])
    assert summary == {"updated": 1, "flagged": 0, "unmatched": 0}

    row = client.get("/ordering-platform/pack/board", headers=headers).json()[0]
    assert row["current_folder"] == "sold"
    assert row["moved_to_sold_date"] is not None
    assert row["carter_po_number"] == "750005026"
    assert str(row["install_pay"]) == "383.00"
    assert row["exception"] is None
    assert row["stage4_date"] is not None          # rollup ran

    # And Optimus moved with it, through its own ladder — not a direct write.
    assert client.get(f"/jobs/{job['id']}", headers=headers).json()["status"] == "2.0-Ord"
    platform = client.get("/ordering-platform/board?include_ordered=true",
                          headers=headers).json()[0]
    assert "s4.poFiled" in platform["steps"]


def test_stage4_total_mismatch_stamps_nothing(client, db):
    """The gate is the whole point: a mismatch records the exception and stops."""
    headers, job = setup_owner(client, db)
    client.patch(f"/jobs/{job['id']}", headers=headers, json={"status": "1.5-OrdPO"})
    before = client.get(f"/jobs/{job['id']}", headers=headers).json()["status"]

    summary = _stage4(client, [{
        "job_code": "DRID60-0115",
        "so_number": "SO46119",
        "carter_po_number": "750005026",
        "carter_po_total": "12345.67",
        "so_total": "12000.00",
        "moved_to_sold": False,
        "outcome": "mismatch",
        "exception": "Carter PO $12,345.67 != SO $12,000.00 (off by $345.67) — folder NOT moved",
    }])
    assert summary == {"updated": 0, "flagged": 1, "unmatched": 0}

    row = client.get("/ordering-platform/pack/board", headers=headers).json()[0]
    assert "off by $345.67" in row["exception"]
    assert row["moved_to_sold_date"] is None
    assert row["current_folder"] != "sold"
    assert row["stage4_date"] is None
    assert client.get(f"/jobs/{job['id']}", headers=headers).json()["status"] == before

    platform = client.get("/ordering-platform/board", headers=headers).json()[0]
    assert "s4.poFiled" not in platform["steps"]

    # It shows up on the queue that needs Brian.
    flagged = client.get("/ordering-platform/pack/board?exceptions_only=true",
                         headers=headers).json()
    assert [r["job_code"] for r in flagged] == ["DRID60-0115"]


def test_stage4_unreadable_pay_never_overwrites_a_typed_amount(client, db):
    """Install pay is never invented — and a blank reading must not wipe a number
    Brian read off the sheet himself."""
    headers, job = setup_owner(client, db)
    client.patch(f"/ordering-platform/pack/jobs/{job['id']}", headers=headers,
                 json={"install_pay": "425.00"})

    _stage4(client, [{
        "job_code": "DRID60-0115",
        "so_number": "SO46119", "carter_po_number": "750005026",
        "carter_po_total": "100.00", "so_total": "100.00",
        "sub_number": "22733",
        "installer_pay_sheet": True,
        "install_pay": None,
        "moved_to_sold": True, "outcome": "ok",
        "exception": "install pay not found on the pay sheet — read it yourself",
    }])

    row = client.get("/ordering-platform/pack/board", headers=headers).json()[0]
    assert str(row["install_pay"]) == "425.00"          # untouched
    assert row["installer_pay_sheet"] is True
    assert "read it yourself" in row["exception"]        # but the note is surfaced
    assert row["current_folder"] == "sold"               # the filing itself succeeded


def test_stage4_is_runnable_and_unknown_job_codes_are_counted(client, db):
    headers, _ = setup_owner(client, db)
    assert "stage4" in client.get("/ordering-platform/pack/meta", headers=headers).json()["runnable"]

    run = client.post("/ordering-platform/pack/runs", headers=headers,
                      json={"kind": "stage4"}).json()
    assert run["status"] == "queued" and run["stage"] == 4

    summary = _stage4(client, [{"job_code": "DRNOPE-9999", "outcome": "ok", "moved_to_sold": True},
                               {"job_code": None, "outcome": "skip"}])
    assert summary["unmatched"] == 2 and summary["updated"] == 0


# --------------------------------------------------------------------------
# The agent's stage-4 folder lookup (regression: it used to match _to_delete)
# --------------------------------------------------------------------------
def _load_stage4():
    """The agent module lives outside the backend package — load it by path."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "agent" / "stage4_pos.py"
    spec = importlib.util.spec_from_file_location("stage4_pos_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_find_job_folder_ignores_housekeeping_and_refuses_to_guess(tmp_path):
    """Found live 8/17/26: the original lookup returned the first directory
    holding a file with the SO number in it, so a superseded copy inside
    `_to_delete` won. The caller then unpacked "_to_delete".split() into two
    names and killed the whole batch with an IndexError."""
    stage4 = _load_stage4()
    so_dir = tmp_path / "3. SOs and Order Comparison"

    real = so_dir / "DROP-0094 BEAU 081226"
    real.mkdir(parents=True)
    (real / "DROP-0094 BEAU SO46089 081226.pdf").write_bytes(b"%PDF-")

    junk = so_dir / "_to_delete"
    junk.mkdir()
    (junk / "DROP-0094 BEAU SO46088 081226.pdf").write_bytes(b"%PDF-")

    (so_dir / "Archive").mkdir()
    (so_dir / "Archive" / "old SO46089 copy.pdf").write_bytes(b"%PDF-")

    find = stage4._safe_find_job_folder
    assert find(str(so_dir), "SO46089") == str(real)   # the Archive copy loses
    assert find(str(so_dir), "SO46088") is None        # _to_delete is not a job
    assert find(str(so_dir), "SO99999") is None

    # Two real folders claiming one SO is ambiguous — refuse, don't pick.
    twin = so_dir / "DROP-0095 BEAU 081226"
    twin.mkdir()
    (twin / "DROP-0095 BEAU SO46089 081226.pdf").write_bytes(b"%PDF-")
    assert find(str(so_dir), "SO46089") is None


def test_install_pay_out_of_range_comes_back_blank(tmp_path, monkeypatch):
    """Install pay is never invented. A number outside the sane window means the
    pay sheet changed shape, so it reports blank with a note."""
    stage4 = _load_stage4()
    folder = tmp_path / "DROP-0094 BEAU 081226"
    folder.mkdir()
    (folder / "DROP-0094 BEAU Installer Pay Sheet 081226.pdf").write_bytes(b"%PDF-")

    class FakePage:
        def __init__(self, text): self._t = text
        def extract_text(self): return self._t

    class FakePDF:
        def __init__(self, text): self.pages = [FakePage(text)]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import sys, types
    def install(text):
        fake = types.ModuleType("pdfplumber")
        fake.open = lambda _p: FakePDF(text)
        monkeypatch.setitem(sys.modules, "pdfplumber", fake)

    install("INSTALL PAY\nKITCHEN COLOR White $383.00\nI-CODE I7550042-148")
    present, pay, icode, note = stage4.read_pay_sheet(folder)
    assert (present, float(pay), icode, note) == (True, 383.00, "I7550042-148", None)

    install("INSTALL PAY\nKITCHEN COLOR White $91,383.00")
    present, pay, _icode, note = stage4.read_pay_sheet(folder)
    assert present is True and pay is None and "outside the expected" in note

    install("no pay label anywhere on this sheet")
    present, pay, _icode, note = stage4.read_pay_sheet(folder)
    assert present is True and pay is None and "read it yourself" in note

    # No pay sheet at all.
    (folder / "DROP-0094 BEAU Installer Pay Sheet 081226.pdf").unlink()
    present, pay, _icode, note = stage4.read_pay_sheet(folder)
    assert present is False and pay is None and "no installer pay sheet" in note
