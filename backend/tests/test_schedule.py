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


def test_installs_green_when_cabinets_received(client, db):
    from datetime import date

    from app.models import JobPo, PoReceipt

    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    make_job(client, headers, account_id, community_id, job_code="RCV-1", install_date="2026-07-10")
    make_job(client, headers, account_id, community_id, job_code="RCV-2", address="2 B St", lot_number="2",
             install_date="2026-07-11")
    make_job(client, headers, account_id, community_id, job_code="RCV-3", address="3 C St", lot_number="3",
             install_date="2026-07-12")
    db.add_all([
        # RCV-1: cabinets in; the open tops PO doesn't hold it back
        JobPo(our_po="750101", job_code="RCV-1", vendor="70408: EVERYTHING BUILDING PRODUCTS LLC",
              product="CABINETS EVERLUX"),
        JobPo(our_po="750102", job_code="RCV-1", vendor="70649: PRECISION STONEWORKS OF FL",
              product="TOPS SOLID SURFACE SPECIAL ORDER"),
        PoReceipt(receipt_number="R101", receipt_date=date(2026, 7, 1), order_number="750101"),
        # RCV-2: two cabinet POs, only one received -> not yet
        JobPo(our_po="750201", job_code="RCV-2", vendor="66190: LEGACY CABINETS", product="CABINETS LEGACY SPECIAL ORDER"),
        JobPo(our_po="750202", job_code="RCV-2", vendor="66190: LEGACY CABINETS", product="CABINETS LEGACY SPECIAL ORDER"),
        PoReceipt(receipt_number="R201", receipt_date=date(2026, 7, 2), order_number="750201"),
        # RCV-3: only the hardware came in
        JobPo(our_po="750301", job_code="RCV-3", vendor="66190: LEGACY CABINETS", product="CABINETS LEGACY SPECIAL ORDER"),
        JobPo(our_po="750302", job_code="RCV-3", vendor="66848: HARDWARE RESOURCES", product="CABINETS OTHER SPECIAL ORDER"),
        PoReceipt(receipt_number="R302", receipt_date=date(2026, 7, 3), order_number="750302"),
    ])
    db.commit()

    items = {i["job_code"]: i for i in
             client.get("/schedule/installs?start=2026-07-01&end=2026-07-31", headers=headers).json()}
    assert items["RCV-1"]["cabinets_in"] is True
    assert items["RCV-1"]["cabinets_received"] == "2026-07-01"
    assert items["RCV-2"]["cabinets_in"] is False
    assert items["RCV-3"]["cabinets_in"] is False
