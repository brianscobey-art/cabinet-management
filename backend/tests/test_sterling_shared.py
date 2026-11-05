"""Sterling in the shared database, linked both ways with its Excel workbook
(Brian 11/5/26: "yes but link both ways")."""

from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.sterling_app import xlsx_store
from app.sterling_app.database import Base
from app.sterling_app.models import CatalogItem, SyncRow


@pytest.fixture()
def shared(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'sterling.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(xlsx_store, "SessionLocal", Session)
    monkeypatch.setattr(xlsx_store, "WORKBOOK_PATH", tmp_path / "CKB Pricing Data.xlsx")
    monkeypatch.setattr(xlsx_store, "SEED_PATH", tmp_path / "no-seed.xlsx")
    monkeypatch.setattr(xlsx_store, "SHARED", True)
    monkeypatch.setattr(xlsx_store, "_schedule", lambda delay: None)
    xlsx_store.state.update(dirty=False, locked=False, last_error=None, suppress=False)
    db = Session()
    db.add_all([
        CatalogItem(id=1, sku="B15", vendor="Everluxe", list_price=Decimal("210.00")),
        CatalogItem(id=2, sku="W3030", vendor="Everluxe", list_price=Decimal("185.50")),
    ])
    db.commit()
    assert xlsx_store.save_now()
    yield db
    db.close()


def _set_cell(sheet, row_id, header, value):
    wb = load_workbook(xlsx_store.WORKBOOK_PATH)
    ws = wb[sheet]
    cols = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == row_id:
            row[cols.index(header)].value = value
    wb.save(xlsx_store.WORKBOOK_PATH)


def _cell(sheet, row_id, header):
    wb = load_workbook(xlsx_store.WORKBOOK_PATH, read_only=True)
    rows = list(wb[sheet].iter_rows(values_only=True))
    wb.close()
    i = list(rows[0]).index(header)
    return next(r[i] for r in rows[1:] if r[0] == row_id)


def _price(db, i):
    db.expire_all()
    return db.get(CatalogItem, i).list_price


def test_save_records_every_row(shared):
    assert shared.query(SyncRow).filter(SyncRow.sheet == "Catalog").count() == 2


def test_excel_edit_flows_into_the_database(shared):
    _set_cell("Catalog", 1, "List Price", 225)
    out = xlsx_store.merge_workbook()
    assert out["from_excel"] == 1 and out["conflicts"] == []
    assert _price(shared, 1) == Decimal("225.00")


def test_app_edit_is_kept_and_written_back(shared):
    shared.get(CatalogItem, 2).list_price = Decimal("199.00")
    shared.commit()
    out = xlsx_store.merge_workbook()
    assert out["kept_app"] == 1
    assert _price(shared, 2) == Decimal("199.00")
    assert _cell("Catalog", 2, "List Price") == 199


def test_both_sides_changed_keeps_the_app_and_flags_it(shared):
    shared.get(CatalogItem, 1).list_price = Decimal("230.00")
    shared.commit()
    _set_cell("Catalog", 1, "List Price", 240)
    out = xlsx_store.merge_workbook()
    assert _price(shared, 1) == Decimal("230.00")
    assert len(out["conflicts"]) == 1
    c = out["conflicts"][0]
    assert (c["sheet"], c["row"], c["excel"]["list_price"], c["app"]["list_price"]) == ("Catalog", "1", "240", "230")


def test_rows_added_and_deleted_in_excel(shared):
    wb = load_workbook(xlsx_store.WORKBOOK_PATH)
    ws = wb["Catalog"]
    cols = [c.value for c in ws[1]]
    new = [None] * len(cols)
    new[cols.index("ID")], new[cols.index("SKU")], new[cols.index("Vendor")] = 3, "B18", "Everluxe"
    new[cols.index("List Price")] = 240
    ws.append(new)
    for row in ws.iter_rows(min_row=2):
        if row[0].value == 2:
            ws.delete_rows(row[0].row)
            break
    wb.save(xlsx_store.WORKBOOK_PATH)
    out = xlsx_store.merge_workbook()
    assert (out["added_from_excel"], out["deleted_from_excel"]) == (1, 1)
    shared.expire_all()
    assert sorted(c.sku for c in shared.query(CatalogItem).all()) == ["B15", "B18"]


def test_a_missing_tab_deletes_nothing(shared):
    wb = load_workbook(xlsx_store.WORKBOOK_PATH)
    del wb["Catalog"]
    wb.save(xlsx_store.WORKBOOK_PATH)
    out = xlsx_store.merge_workbook()
    assert "Catalog" in out["skipped_sheets"] and out["deleted_from_excel"] == 0
    shared.expire_all()
    assert shared.query(CatalogItem).count() == 2


def test_verify_finds_a_line_that_differs(shared):
    assert xlsx_store.verify_workbook()["match"] is True
    _set_cell("Catalog", 2, "List Price", 186)
    v = xlsx_store.verify_workbook()
    assert v["match"] is False
    assert v["differences"][0]["fields"]["list_price"] == {"database": "185.5", "workbook": "186"}


def test_first_boot_moves_the_workbook_in_and_checks_it(shared):
    shared.query(CatalogItem).delete()
    shared.query(SyncRow).delete()
    shared.commit()
    xlsx_store.startup_report.clear()
    xlsx_store.startup()
    assert xlsx_store.startup_report["moved"]["Catalog"] == 2
    assert xlsx_store.startup_report["verify"]["match"] is True
    assert _price(shared, 2) == Decimal("185.50")
