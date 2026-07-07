from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def setup(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    return headers, account_id, community_id


def test_phase_definitions(client, db):
    headers, _, _ = setup(client, db)
    phases = client.get("/phases", headers=headers).json()
    assert phases[0] == {"code": "0", "label": "0 - Dirt/Staked"}
    assert phases[-1] == {"code": "12", "label": "12 - IC Cab Installed"}
    assert len(phases) == 18


def test_set_phase_and_board(client, db):
    headers, account_id, community_id = setup(client, db)
    job5 = make_job(client, headers, account_id, community_id, job_code="DR-5", lot_number="5")
    make_job(client, headers, account_id, community_id, job_code="DR-12", lot_number="12",
             address="12 Other St")
    closed = make_job(client, headers, account_id, community_id, job_code="DR-99", lot_number="99",
                      address="99 Done St")
    client.patch(f"/jobs/{closed['id']}", headers=headers, json={"status": "closed"})

    resp = client.post(f"/jobs/{job5['id']}/phase", headers=headers, json={"phase": "4.2"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["phase"] == "4.2"
    assert body["noted_at"] is not None
    assert body["noted_by"] == "Test User"

    # invalid phase rejected
    assert client.post(f"/jobs/{job5['id']}/phase", headers=headers, json={"phase": "13"}).status_code == 422

    board = client.get(f"/phase-board?community_id={community_id}", headers=headers).json()
    assert [r["job_code"] for r in board] == ["DR-5", "DR-12"]  # numeric lot order, closed excluded
    assert board[0]["phase"] == "4.2"
    assert board[0]["phase_label"] == "4.2 - Roof Complete"
    assert board[1]["phase"] is None

    # updating again: latest wins, history keeps both
    client.post(f"/jobs/{job5['id']}/phase", headers=headers, json={"phase": "5"})
    board = client.get(f"/phase-board?community_id={community_id}", headers=headers).json()
    assert board[0]["phase"] == "5"
    history = client.get(f"/jobs/{job5['id']}/phases", headers=headers).json()
    assert [h["phase"] for h in history] == ["5", "4.2"]

    # closed shows up only when asked
    with_closed = client.get(f"/phase-board?community_id={community_id}&include_closed=true", headers=headers).json()
    assert len(with_closed) == 3


def test_field_role_can_set_phase(client, db):
    headers, account_id, community_id = setup(client, db)
    job = make_job(client, headers, account_id, community_id)
    make_user(db, email="field@example.com", role=Role.field)
    field = login(client, "field@example.com")
    resp = client.post(f"/jobs/{job['id']}/phase", headers=field, json={"phase": "3"})
    assert resp.status_code == 201

    make_user(db, email="inspector@example.com", role=Role.inspector)
    inspector = login(client, "inspector@example.com")
    assert client.post(f"/jobs/{job['id']}/phase", headers=inspector, json={"phase": "3"}).status_code == 403
