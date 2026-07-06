from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def setup(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    job = make_job(client, headers, account_id, community_id, job_code="DRTEST-0001")
    return headers, account_id, job


def test_checklist_starts_empty_and_toggles(client, db):
    headers, _, job = setup(client, db)

    checklist = client.get(f"/jobs/{job['id']}/ordering", headers=headers).json()
    assert checklist["stage1_done"] is False
    assert checklist["stage1_date"] is None

    resp = client.patch(
        f"/jobs/{job['id']}/ordering", headers=headers,
        json={"stage1_done": True, "stage2_done": True, "notes": "PO 201646 processed"},
    )
    body = resp.json()
    assert body["stage1_done"] is True
    assert body["stage1_date"] is not None
    assert body["stage3_done"] is False
    assert body["notes"] == "PO 201646 processed"

    # unchecking clears the date
    body = client.patch(f"/jobs/{job['id']}/ordering", headers=headers, json={"stage2_done": False}).json()
    assert body["stage2_done"] is False
    assert body["stage2_date"] is None


def test_board_lists_builder_jobs(client, db):
    headers, account_id, job = setup(client, db)
    # retail job should NOT appear on the national builder board
    retail_id = client.post("/accounts", headers=headers, json={"name": "Jane Smith", "type": "retail"}).json()["id"]
    make_job(client, headers, retail_id, job_code="SMITH-01", address="9 Oak Ln", lot_number=None)

    board = client.get("/ordering", headers=headers).json()
    codes = [r["job_code"] for r in board]
    assert "DRTEST-0001" in codes
    assert "SMITH-01" not in codes
    row = next(r for r in board if r["job_code"] == "DRTEST-0001")
    assert row["checklist"]["stage1_done"] is False

    # closed jobs drop off unless requested
    client.patch(f"/jobs/{job['id']}", headers=headers, json={"status": "closed"})
    assert client.get("/ordering", headers=headers).json() == []
    assert len(client.get("/ordering?include_closed=true", headers=headers).json()) == 1


def test_checklist_seeds_from_documents(client, db, tmp_path):
    headers, _, job = setup(client, db)
    for doc_type in ("po", "selections", "order", "layout"):
        f = tmp_path / f"{doc_type}.pdf"
        f.write_bytes(b"%PDF-1.4 test")
        client.post(
            f"/jobs/{job['id']}/documents", headers=headers,
            json={"file_path": str(f), "doc_type": doc_type},
        )
    checklist = client.get(f"/jobs/{job['id']}/ordering", headers=headers).json()
    assert checklist["stage1_done"] is True   # po + selections present
    assert checklist["stage2_done"] is True   # order + layout present
    assert checklist["stage3_done"] is False  # no SO yet
    assert checklist["stage4_done"] is False


def test_field_role_cannot_update_checklist(client, db):
    headers, _, job = setup(client, db)
    make_user(db, email="field@example.com", role=Role.field)
    field = login(client, "field@example.com")
    assert client.get(f"/jobs/{job['id']}/ordering", headers=field).status_code == 200
    resp = client.patch(f"/jobs/{job['id']}/ordering", headers=field, json={"stage1_done": True})
    assert resp.status_code == 403
