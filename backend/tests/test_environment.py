"""The test copy of the app (APP_ENV=test) must never write outside itself,
and the live default must stay exactly as it was."""

import pytest

from app.config import Settings
from app.models import Job, User

LIVE_LIKE = dict(  # noqa: C408 (keyword form reads like the Settings call)
    smartsheet_api_token="tok",
    smartsheet_job_sheet_id=123,
    smartsheet_po_sheet_id=456,
    sendgrid_api_key="sg",
    invite_from_email="from@example.com",
    r2_endpoint="https://r2.example.com",
    r2_bucket="bucket",
    r2_access_key_id="id",
    r2_secret_access_key="secret",
    domo_access_token="domo",
    orderpack_auto_stage4=True,
)


def test_production_is_the_default_and_untouched():
    s = Settings(_env_file=None, **LIVE_LIKE)
    assert s.app_env == "production" and not s.is_test
    assert s.smartsheet_push_enabled and s.smartsheet_job_sheet_id == 123
    assert s.email_enabled and s.r2_enabled and s.domo_access_token == "domo"
    assert s.orderpack_auto_stage4


def test_test_copy_switches_off_every_outside_write_even_with_live_keys():
    s = Settings(_env_file=None, app_env="test", **LIVE_LIKE)
    assert s.is_test
    assert not s.smartsheet_push_enabled
    assert s.smartsheet_job_sheet_id == 0 and s.smartsheet_po_sheet_id == 0
    assert s.smartsheet_api_token == ""
    assert not s.email_enabled
    assert not s.r2_enabled and not s.r2_pull_enabled
    assert s.domo_access_token == ""
    assert not s.orderpack_auto_stage4


def test_env_endpoint_reports_production_by_default(client):
    assert client.get("/env").json() == {"env": "production"}
    assert client.get("/api/env").json() == {"env": "production"}


def test_seed_refuses_on_live(db, monkeypatch):
    from scripts import seed_test_data

    monkeypatch.setattr(seed_test_data, "get_settings", lambda: Settings(_env_file=None))
    with pytest.raises(SystemExit):
        seed_test_data.seed(db, "admin@example.com", "Admin", "password123")
    assert db.query(Job).count() == 0


def test_seed_fills_an_empty_test_database_once(db, monkeypatch):
    from scripts import seed_test_data

    monkeypatch.setattr(seed_test_data, "get_settings",
                        lambda: Settings(_env_file=None, app_env="test"))
    result = seed_test_data.seed(db, "admin@example.com", "Admin", "password123")
    assert result["jobs"] == db.query(Job).count() == 9
    assert db.query(User).filter(User.email == "admin@example.com").count() == 1
    assert all(j.notes == "TEST DATA" for j in db.query(Job))
    with pytest.raises(SystemExit):       # second run: database is no longer empty
        seed_test_data.seed(db, "admin@example.com", "Admin", "password123")


def _file_db(path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base

    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    return eng, sessionmaker(bind=eng, expire_on_commit=False)


def _fake_live(tmp_path, monkeypatch):
    """A 'live' database on disk with sample sold jobs, quotes and a visit."""
    from decimal import Decimal

    from app.models import Order, Quote, QuoteLineItem, Supplier, Visit, Worker
    from scripts import seed_test_data

    eng, Session = _file_db(tmp_path / "live.db")
    monkeypatch.setattr(seed_test_data, "get_settings",
                        lambda: Settings(_env_file=None, app_env="test"))
    with Session() as s:
        seed_test_data.seed(s, "live-admin@example.com", "Live Admin", "password123")
        job = s.query(Job).filter(Job.job_code == "TEST-104").one()
        q = Quote(job_id=job.id, name="Option A")
        s.add(q)
        s.flush()
        s.add(QuoteLineItem(quote_id=q.id, sku="B18", qty=1,
                            list_price=Decimal(100)))
        s.add(Order(job_id=job.id, quote_id=q.id, supplier=Supplier.everluxe))
        w = Worker(name="Sample Tech", is_tech=True)
        s.add(w)
        s.flush()
        s.add(Visit(job_id=job.id, visit_type="punch_out", assigned_to=w.id))
        s.commit()
    return eng


def test_copy_from_live_is_read_only_masks_contacts_and_reruns_safely(tmp_path, monkeypatch):
    from sqlalchemy import func, select

    from app.database import Base
    from scripts import copy_jobs_from_live as C

    live_path = tmp_path / "live.db"
    _fake_live(tmp_path, monkeypatch)
    before = live_path.read_bytes()
    live = C.open_live_readonly(f"sqlite:///{live_path}")
    target, TSession = _file_db(tmp_path / "test.db")

    jobs = C.pick_jobs(live, None, 5)
    assert len(jobs) == 5 and len({j["status"] for j in jobs}) == 5   # spread out

    dry = C.copy_jobs(live, target, jobs, dry_run=True)
    assert dry["copied"]["jobs"] == 5
    with TSession() as s:
        assert s.query(Job).count() == 0                                # dry run wrote nothing

    out = C.copy_jobs(live, target, C.pick_jobs(live, ["TEST-104", "TEST-R1"], None))
    assert out["copied"]["jobs"] == 2 and out["copied"]["quote_line_items"] == 1
    assert out["copied"]["orders"] == 1 and out["copied"]["visits"] == 1
    with TSession() as s:
        emails = [j.sales_contact_email for j in s.query(Job)]
        assert all(e.endswith("@example.invalid") for e in emails)
        assert s.query(User).count() == 0                               # no live logins copied
    again = C.copy_jobs(live, target, C.pick_jobs(live, ["TEST-104"], None))
    assert again["skipped_already_in_test"] == ["TEST-104"]

    # Live is untouched and refuses writes outright.
    assert live_path.read_bytes() == before
    from sqlalchemy.exc import OperationalError

    with pytest.raises(OperationalError), live.begin() as c:
        c.execute(Base.metadata.tables["accounts"].delete())
    with live.connect() as c:
        assert c.execute(select(func.count()).select_from(Base.metadata.tables["jobs"])).scalar() == 9


def test_copy_refuses_on_live_or_same_database(monkeypatch, tmp_path):
    from scripts import copy_jobs_from_live as C

    url = f"sqlite:///{tmp_path / 'x.db'}"
    monkeypatch.setattr(C, "get_settings", lambda: Settings(_env_file=None, database_url=url))
    monkeypatch.setenv("LIVE_DATABASE_URL", url)
    with pytest.raises(SystemExit, match="APP_ENV"):
        C.main(["--pick", "1"])
    monkeypatch.setattr(C, "get_settings",
                        lambda: Settings(_env_file=None, app_env="test", database_url=url))
    with pytest.raises(SystemExit, match="same database"):
        C.main(["--pick", "1"])


def test_bootstrap_does_nothing_on_live(monkeypatch):
    from app import test_bootstrap

    monkeypatch.setattr(test_bootstrap, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setenv("TEST_ADMIN_EMAIL", "brian@example.com")
    assert test_bootstrap.run() == {"skipped": "not the test copy"}


def test_bootstrap_admin_link_sample_and_copy_once(tmp_path, monkeypatch, caplog):
    from sqlalchemy.orm import sessionmaker

    from app import test_bootstrap
    from app.database import Base  # noqa: F401
    from scripts import copy_jobs_from_live as C

    live_path = tmp_path / "live.db"
    _fake_live(tmp_path, monkeypatch)
    target, TSession = _file_db(tmp_path / "test.db")
    test_url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = Settings(_env_file=None, app_env="test", database_url=test_url)
    monkeypatch.setattr(test_bootstrap, "get_settings", lambda: cfg)
    monkeypatch.setattr(C, "get_settings", lambda: cfg)
    import app.database as D
    monkeypatch.setattr(D, "SessionLocal", sessionmaker(bind=target, expire_on_commit=False))
    monkeypatch.setattr(D, "engine", target)
    from scripts import seed_test_data
    monkeypatch.setattr(seed_test_data, "get_settings", lambda: cfg)
    monkeypatch.setenv("TEST_ADMIN_EMAIL", "Brian@Example.com")
    monkeypatch.setenv("TEST_SEED_SAMPLE", "1")
    monkeypatch.setenv("TEST_COPY_JOBS", "3")
    monkeypatch.setenv("LIVE_DATABASE_URL", f"sqlite:///{live_path}")

    with caplog.at_level("WARNING"):
        out = test_bootstrap.run()
    assert out["admin"] == "created"
    assert "set-password?token=" in caplog.text
    assert out["sample"].startswith("{")
    # Sample codes overlap the fake live codes, so all 3 picks are already there.
    assert out["copy"] == "0 jobs copied, 3 already in test"
    again = test_bootstrap.run()
    assert again["admin"] == "exists" and again["copy"].startswith("already done")
    with TSession() as s:
        u = s.query(User).filter(User.email == "brian@example.com").one()
        assert u.role.value == "admin"
