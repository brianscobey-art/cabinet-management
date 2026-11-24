from datetime import date

from app import po_lines
from app.config import get_settings
from app.models import DomoPo, IAccountLine, PoLineItem, Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account

HEAD = ("Transaction Date,Order Number,Assigned Salesperson,Customer : Job,Supplier,SKU,Spec Description,"
        "Quantity Ordered,Ordered Cost,Quantity Received,Received Cost\n")
ACCT = '"I7550228-004: South Chesapeake LLC dba Paul Davis Restoration of the Emera - CAB PDAG0556"'
KC = "66892: KITCHEN CRAFT CABINETRY,C2283: CABINETS KITCHEN CRAFT SPECIAL ORDER"


def _csv():
    rows = [
        f"2026-09-11,750005436,c75008: Laurie Reel,{ACCT},{KC},'-,1.0,1,0,0",
        f"2026-09-11,750005436,c75008: Laurie Reel,{ACCT},{KC},STW3057,0.0,0,1,400",
        f"2026-09-11,750005436,c75008: Laurie Reel,{ACCT},{KC},SB36,0.0,0,1,763",
        f"2026-10-19,750005950,c75008: Laurie Reel,{ACCT},70322: HYPE MILL LLC,C2299: CABINETS OTHER SPECIAL ORDER,"
        "-,1.0,3903.1,0,0",
        f"2026-10-19,750005950,c75008: Laurie Reel,{ACCT},70322: HYPE MILL LLC,C2299: CABINETS OTHER SPECIAL ORDER,"
        "Hood - H-174122,0.0,0,1,3903",
    ]
    return HEAD + "\n".join(rows) + "\n"


def test_parse_header_items_alias_account():
    rows = po_lines.parse(_csv())
    assert [r["line_type"] for r in rows] == ["header", "item", "item", "header", "item"]
    head, item = rows[0], rows[1]
    assert head["item_code"] is None and float(head["ordered_cost"]) == 1
    assert item["item_code"] == "STW3057" and float(item["received_cost"]) == 400
    assert item["account"] == "I7550228-004" and item["cab_job_code"] == "PDAG0556"
    assert item["supplier_id"] == "66892" and item["supplier_name"] == "KITCHEN CRAFT CABINETRY"
    assert rows[4]["vendor_alias"] == "Hoodsly" and rows[4]["item_code"] == "Hood - H-174122"
    assert item["transaction_date"] == date(2026, 9, 11)


def test_ingest_replaces_per_po_links_job_and_checks(client, db, monkeypatch):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    job = make_job(client, headers, account_id, community_id, job_code="PDAG-0556")
    client.patch(f"/jobs/{job['id']}", headers=headers, json={"i_code": "I7550228-004"})
    db.add_all([
        DomoPo(our_po="750005436", received_cost=1163, ordered_cost=1, status="Closed"),
        DomoPo(our_po="750005950", received_cost=3800, ordered_cost=3903.1, status="Closed"),  # $103 off
        IAccountLine(g_account="G7550228-006", i_account="I7550228-004", sku="C2283", cost=500, sales=500),
        IAccountLine(g_account="G7550228-007", i_account="I7550228-005", sku="C2283", cost=500, sales=640),
    ])
    db.commit()
    monkeypatch.setattr(get_settings(), "po_lines_ingest_token", "t0ken")

    assert client.post("/feeds/ingest/po-lines", content=_csv()).status_code == 403
    r = client.post("/feeds/ingest/po-lines", content=_csv(), headers={"X-Ingest-Token": "t0ken"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["pos"] == 2 and out["items"] == 3 and out["linked_to_job"] == 5 and out["received_total"] == 5066
    c = out["checks"]
    assert [m["po_number"] for m in c["received_mismatch"]] == ["750005950"]
    assert [p["po_number"] for p in c["placeholder_pos"]] == ["750005436"]
    assert [a["i_account"] for a in c["posted_at_cost"]] == ["I7550228-004"]

    # a second pull of the same POs replaces, never doubles
    client.post("/feeds/ingest/po-lines", content=_csv(), headers={"X-Ingest-Token": "t0ken"})
    assert db.query(PoLineItem).count() == 5

    rep = client.get("/reports/po-lines?q=PDAG0556", headers=headers).json()
    assert rep["job_code"] == "PDAG-0556" and rep["po_count"] == 2 and rep["item_lines"] == 3
    assert rep["items_received"] == 5066
    hood = next(p for p in rep["pos"] if p["po_number"] == "750005950")
    assert hood["vendor_alias"] == "Hoodsly" and hood["received_ok"] is False
    kc = next(p for p in rep["pos"] if p["po_number"] == "750005436")
    assert kc["placeholder"] is True and kc["received_ok"] is True


def test_iaccount_ingest_keeps_prefixes(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "po_lines_ingest_token", "t0ken")
    text = ("Job Final Bill,Job,SKU,Status,Cost,Sales\n"
            "G7510029-635: PP 0189,I7510029-176: W/D PP 189,240892: TWIN WHT,Closed,352.565,356.91\n")
    r = client.post("/feeds/ingest/i-account-detail", content=text, headers={"X-Ingest-Token": "t0ken"})
    assert r.json() == {"lines": 1, "i_accounts": 1}
    line = db.query(IAccountLine).one()
    assert line.g_account == "G7510029-635" and line.i_account == "I7510029-176"
