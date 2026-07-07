from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def test_installs_range_and_filter(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    other_id = client.post("/accounts", headers=headers, json={"name": "Century", "type": "builder"}).json()["id"]

    in_range = make_job(client, headers, account_id, community_id, job_code="DR-IN", install_date="2026-07-15")
    make_job(client, headers, account_id, community_id, job_code="DR-OUT", address="2 Out St",
             lot_number="9", install_date="2026-08-02")
    make_job(client, headers, other_id, None, job_code="CEN-1", address="3 Cen St",
             lot_number=None, install_date="2026-07-20")
    make_job(client, headers, account_id, community_id, job_code="DR-NODATE", address="4 No St", lot_number="8")

    resp = client.get("/schedule/installs?start=2026-07-01&end=2026-07-31", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert [i["job_code"] for i in items] == ["DR-IN", "CEN-1"]  # ordered by date
    assert items[0]["install_date"] == "2026-07-15"
    assert items[0]["account_name"]

    filtered = client.get(
        f"/schedule/installs?start=2026-07-01&end=2026-07-31&account_id={account_id}", headers=headers
    ).json()
    assert [i["job_code"] for i in filtered] == ["DR-IN"]
    assert in_range["id"] == filtered[0]["job_id"]
