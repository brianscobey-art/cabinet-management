from datetime import date, timedelta

from app.models import JobPo, PoReceipt, Role, ServiceRequest, Visit
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def test_ksr_summary_received_installs_service(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    today = date.today()
    mine = make_job(client, headers, account_id, community_id, job_code="DRT-0001")
    other = make_job(client, headers, account_id, community_id, job_code="DRT-0002", lot_number="43")
    client.patch(f"/jobs/{mine['id']}", headers=headers,
                 json={"ksr": "Paula Cook", "install_date": (today + timedelta(days=5)).isoformat()})
    client.patch(f"/jobs/{other['id']}", headers=headers, json={"ksr": "Laurie Reel"})

    db.add_all([
        JobPo(our_po="750001", job_code="DRT-0001", vendor="Everluxe", product="Cabinets"),
        JobPo(our_po="750002", job_code="DRT-0001", vendor="Hype Mill", product="Tops"),
        JobPo(our_po="750003", job_code="DRT-0002", vendor="Everluxe", product="Cabinets"),
        PoReceipt(receipt_number="R1", receipt_date=today - timedelta(days=2), order_number="750001", landed_cost=100),
        PoReceipt(receipt_number="R2", receipt_date=today - timedelta(days=90), order_number="750001", landed_cost=5),
        PoReceipt(receipt_number="R3", receipt_date=today, order_number="750003", landed_cost=7),
        Visit(visit_type="service_t1", job_id=mine["id"], status="pending", scheduled_date=today + timedelta(days=3)),
        Visit(visit_type="punch_out", job_id=mine["id"], status="pending"),
        ServiceRequest(job_id=mine["id"], title="Replace door", scheduled_date=today + timedelta(days=9)),
    ])
    db.commit()

    out = client.get("/my/summary?ksr=paula", headers=headers).json()
    assert out["ksr"] == "Paula Cook"
    assert [r["receipt_number"] for r in out["received"]] == ["R1"]       # 30-day window, her jobs only
    assert out["installs"][0]["job_code"] == "DRT-0001"
    assert out["installs"][0]["material"] == "partial"                      # 750002 not received
    assert [s["kind"] for s in out["service"]] == ["Service (small)", "Replace door"]

    everything = client.get("/my/summary?ksr=Paula Cook&days=0", headers=headers).json()
    assert {r["receipt_number"] for r in everything["received"]} == {"R1", "R2"}
