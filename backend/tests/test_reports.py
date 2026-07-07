from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def test_phase_report_grouping_and_sort(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")

    # builder B first alphabetically? use names that test sorting
    zeta_id, zeta_comm = setup_account(client, headers, name="Zeta Homes", community="Alpha Cove")
    acme_id, acme_comm = setup_account(client, headers, name="Acme Builders", community="Briar Ridge")
    retail_id = client.post("/accounts", headers=headers, json={"name": "Jane Doe", "type": "retail"}).json()["id"]

    make_job(client, headers, zeta_id, zeta_comm, job_code="Z-10", lot_number="10", address="10 A St")
    make_job(client, headers, zeta_id, zeta_comm, job_code="Z-2", lot_number="2", address="2 A St")
    make_job(client, headers, acme_id, acme_comm, job_code="A-1", lot_number="1", address="1 B St")
    closed = make_job(client, headers, acme_id, acme_comm, job_code="A-9", lot_number="9", address="9 B St")
    client.patch(f"/jobs/{closed['id']}", headers=headers, json={"status": "closed"})
    make_job(client, headers, retail_id, None, job_code="RET-1", address="5 Retail Ln", lot_number=None)

    client.post(f"/jobs/{closed['id']}/phase", headers=headers, json={"phase": "9"})  # closed job phase ignored
    resp = client.post("/jobs/1/phase", headers=headers, json={"phase": "4"})
    assert resp.status_code == 201

    report = client.get("/reports/phases", headers=headers).json()
    codes = [r["job_code"] for r in report]
    # builder alphabetical, then community, then numeric lot; closed + retail excluded
    assert codes == ["A-1", "Z-2", "Z-10"]
    z2 = next(r for r in report if r["job_code"] == "Z-2")
    assert z2["account_name"] == "Zeta Homes"
    assert z2["community_name"] == "Alpha Cove"
    first = next(r for r in report if r["job_id"] == 1)
    assert first["phase_label"] == "4 - Framing Complete (Measure)"
