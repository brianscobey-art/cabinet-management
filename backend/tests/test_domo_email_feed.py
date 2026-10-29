import csv
from datetime import date

from app.job_accounts import load_pairs
from app.models import PoReceipt
from app.po_receipts import _upsert_receipts
from scripts import domo_email_feed as feed


def _csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def test_job_account_card_pairs_i_and_g_by_name(tmp_path):
    src = _csv(tmp_path / "Job Account.csv", ["Job"], [
        ["I7510029-304: DR HORTON PC ONLY - CAB CESF 24"], ["G7510029-A2Z: DR HORTON PC ONLY - CAB CESF 24"],
        ["G7510082-016: SUZANNE VICKERS CONSTRUCTION INC - C"],  # not a CAB account
    ])
    out = _csv(tmp_path / "DOMO CAB Accounts 102926.csv", feed.ACCT_COLS, feed.accounts(src))
    pairs = load_pairs(out)
    assert [(p["g"], p["i"], p["name"]) for p in pairs] == [("G7510029-A2Z", "I7510029-304", "CAB CESF 24")]


def test_po_card_to_job_pos(tmp_path):
    src = _csv(tmp_path / "ALL Purchase Orders by Customer and Supplier.csv",
               ["Transaction Date", "Order Number", "Assigned Salesperson", "Customer : Job", "Supplier",
                "Landed Cost", "Received Cost"], [
        ["2026-10-02", "750005759", "c75012: Alex Talley", "I7510029-304: DR HORTON PC ONLY - CAB CESF 24",
         "70408: EVERYTHING BUILDING PRODUCTS LLC", "1908.63", "1907"],
        ["2026-10-21", "750005991", "", "I7510029-306: DR HORTON PC ONLY - CAB CETH 121", "70408: X", "2235.93", "0"],
        ["2026-09-11", "750005436", "", "I7550228-004: PAUL DAVIS - CAB PDAG0556", "66892: KC", "1", "17163"],
        ["2026-10-28", "755003688", "", "", "61322: WOODGRAIN INC", "500", "0"],  # stock PO
    ])
    rows = {r[0]: dict(zip(feed.PO_COLS, r)) for r in feed.job_pos(src)}
    assert set(rows) == {"750005759", "750005991", "750005436"}
    assert rows["750005759"]["Status"] == "Closed" and rows["750005991"]["Status"] == "Open"
    assert rows["750005436"]["Status"] == "Closed"  # $1 special-order placeholder


def test_receipts_merge_not_replace(db):
    db.add(PoReceipt(receipt_number="OLD", receipt_date=date(2025, 12, 30), order_number="1"))
    db.commit()
    _upsert_receipts(db, [{"Receipt #": "NEW", "Receipt Date": "2026-01-02", "Order #": "2"}])
    db.commit()
    assert {r.receipt_number for r in db.query(PoReceipt).all()} == {"OLD", "NEW"}
