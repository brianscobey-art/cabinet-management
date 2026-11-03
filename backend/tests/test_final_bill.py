import csv
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app import final_bill
from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def test_installed_not_final_billed(client, db, tmp_path, monkeypatch):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    billed = make_job(client, headers, account_id, community_id, job_code="FB-0001")
    open_ = make_job(client, headers, account_id, community_id, job_code="FB-0002", address="2 B St", lot_number="2")
    client.patch(f"/jobs/{billed['id']}", headers=headers, json={"g_code": "G7500042-120", "i_code": "I7500042-120"})
    client.patch(f"/jobs/{open_['id']}", headers=headers, json={"g_code": "G7500042-121", "i_code": "I7500042-121"})

    today = datetime.combine(date.today(), datetime.min.time())
    rows = [
        {"Job Code": "FB-0001", "Actual Install Date": today - timedelta(days=20)},  # billed on G
        {"Job Code": "FB-0002", "Actual Install Date": today - timedelta(days=10)},  # only I-code sales
        {"Job Code": "FB-0003", "Actual Install Date": today - timedelta(days=5), "Builder": "Walk-in",
         "Address": "3 C St", "G-Code": "NA"},                                       # not in CabinetTron, no G
        {"Job Code": "FB-0004", "Actual Install Date": today + timedelta(days=4)},   # not installed yet
        {"Job Code": "FB-0005", "Requested Install Date": today - timedelta(days=9)},  # requested only
    ]
    monkeypatch.setattr("app.smartsheet.api._tracker_rows", lambda: (rows, True, "3.0 Online Sales Tracker 110326.xlsm"))
    with (tmp_path / "DOMO Job Billing 110326.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(final_bill.COLS)
        w.writerows([["G7500042-0120", "5321.40", "31"],   # tracker pads, DOMO doesn't -- same account
                     ["I7500042-121", "1200", "4"]])
    monkeypatch.setattr(final_bill, "get_settings", lambda: SimpleNamespace(domo_billing_folder=str(tmp_path)))

    out = client.get("/reports/not-final-billed", headers=headers).json()
    assert out["billing_file"] == "DOMO Job Billing 110326.csv"
    assert out["installed"] == 3
    assert [r["job_code"] for r in out["rows"]] == ["FB-0002", "FB-0003"]  # oldest install first
    first, second = out["rows"]
    assert first["job_id"] == open_["id"] and first["reason"] == "no sales on the G-code"
    assert first["i_sales"] == 1200 and first["days_since_install"] == 10
    assert second["job_id"] is None and second["reason"] == "no G-code on file"

    since = (date.today() - timedelta(days=7)).isoformat()
    assert [r["job_code"] for r in client.get(f"/reports/not-final-billed?since={since}",
                                              headers=headers).json()["rows"]] == ["FB-0003"]
