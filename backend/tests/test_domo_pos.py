import csv
from datetime import date, timedelta

from app import domo_pos
from app.models import DomoPo, JobPo, PoReceipt, Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def _csv(tmp_path, rows):
    f = tmp_path / "DOMO Job POs 102926.csv"
    with f.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(domo_pos.COLS)
        w.writerows(rows)
    return f


def test_domo_pos_match_by_code_and_show_on_job(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(domo_pos, "_ash_index", lambda: {})
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    job = make_job(client, headers, account_id, community_id, job_code="DRCESF-0024")
    client.patch(f"/jobs/{job['id']}", headers=headers, json={"i_code": "I7510029-304", "g_code": "G7510029-A2Z"})
    past = (date.today() - timedelta(days=3)).isoformat()

    f = _csv(tmp_path, [
        # received: DOMO PO detail has the receipt (number + 20261020-style date)
        ["750005759", "2026-10-02", "2026-10-09", "Closed", "2026-10-20", "70408: EVERYTHING BUILDING PRODUCTS LLC",
         "CABINETS EVERLUX", "I7510029-304: DR HORTON PC ONLY - CAB CESF 24", "75000017646", "1908.63", "1907",
         "20261020", "750005794", "c75012: Alex Talley", "750: Dothan", "48"],
        # open and past due; special order $1 placeholder cost
        ["750006100", "2026-10-20", past, "Open", "", "66892: KITCHEN CRAFT CABINETRY",
         "CABINETS KITCHEN CRAFT SPECIAL ORDER", "I7510029-304: DR HORTON PC ONLY - CAB CESF 24", "75000017999",
         "1", "0", "", "", "c75012: Alex Talley", "750: Dothan", "3"],
        # nobody's job
        ["750009999", "2026-10-21", "2026-10-28", "Open", "", "1: X", "CABINETS", "I9999999-001: NOBODY - CAB ZZ 1",
         "", "10", "0", "", "", "", "750: Dothan", "1"],
    ])
    out = domo_pos.apply(db, f)
    assert (out["pos"], out["matched"], out["unmatched"], out["open"]) == (3, 2, 1, 2)
    assert db.get(DomoPo, "750005759").last_receipt_date == date(2026, 10, 20)

    # the tracker sheet also knows 750005759 (its product wins) and one PO DOMO doesn't
    db.add_all([JobPo(our_po="750005759", job_code="DRCESF-0024", vendor="Everluxe", product="Cabinets"),
                JobPo(our_po="750001234", job_code="DRCESF-0024", vendor="Hype Mill", product="Tops")])
    db.add(PoReceipt(receipt_number="750005794", receipt_date=date(2026, 10, 20), order_number="750005759",
                     landed_cost=1908.63))
    db.commit()
    pos = {p["our_po"]: p for p in client.get(f"/jobs/{job['id']}/purchase-orders", headers=headers).json()["purchase_orders"]}
    assert set(pos) == {"750005759", "750006100", "750001234"}
    assert pos["750005759"]["product"] == "Cabinets" and pos["750005759"]["source"] == "DOMO + tracker"
    assert pos["750005759"]["received"] and pos["750005759"]["receipts"][0]["landed_cost"] == 1908.63
    assert pos["750006100"]["status"] == "Open" and not pos["750006100"]["received"]
    assert pos["750006100"]["days_overdue"] == 3
    assert pos["750006100"]["cost"] == 0  # $1 placeholder is not a cost
    assert pos["750001234"]["source"] == "tracker"
