"""Sterling, Optimus, the Order Pack agent and the builder feeds now go
through the COAST hand-off rules instead of writing CabinetTron directly."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.models import Job, JobEvent, JobStatus, OrderingChecklist
from app.suite import handoff

from tests.test_pack import AGENT_HEADERS, setup_owner


def _hold(db, job, code, source="autobot"):
    db.add(JobEvent(job_id=job.id, job_code=job.job_code, source=source, kind="field_measure",
                    level="hold", hold_code=code, issues=["Sink wall 3 in. short"]))
    db.commit()


def _job(db, code="DRID60-0115"):
    return db.query(Job).filter(Job.job_code == code).one()


def test_optimus_step_waits_on_an_open_measure_hold(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.status = JobStatus.ndord
    db.commit()
    _hold(db, job, "measure_discrepancy")
    assert handoff.optimus_move(db, job, JobStatus.ordprcss) is False
    db.commit()
    assert job.status is JobStatus.ndord
    blocked = db.query(JobEvent).filter(JobEvent.kind == "step_blocked").one()
    assert "Sink wall" in blocked.issues[0]


def test_optimus_untick_moves_back_and_is_logged(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.status = JobStatus.ordsub
    db.commit()
    assert handoff.optimus_move(db, job, JobStatus.ordprcss) is True
    db.commit()
    ev = db.query(JobEvent).filter(JobEvent.kind == "step").one()
    assert (ev.status_from, ev.status_to, ev.level) == ("1.4-OrdSub", "1.3-Ord Prcss", "warn")


def _stage4(client, **over):
    item = {"job_code": "DRID60-0115", "folder": "DRID60-0115 CREE 081326", "so_number": "SO46119",
            "carter_po_number": "750005026", "carter_po_total": "12345.67", "so_total": "12345.67",
            "moved_to_sold": True, "outcome": "ok", **over}
    return client.post("/ordering-platform/pack/agent/stage4/apply", headers=AGENT_HEADERS,
                       json={"results": [item]}).json()


def test_stage4_refuses_a_cancelled_carter_po(client, db):
    headers, j = setup_owner(client, db)
    client.patch(f"/jobs/{j['id']}", headers=headers, json={"status": "1.5-OrdPO"})
    assert _stage4(client, carter_po_number="750005976")["flagged"] == 1
    db.expire_all()
    assert _job(db).status is JobStatus.ordpo
    cl = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == j["id"]).one()
    assert "was cancelled" in cl.exception


def test_stage4_refuses_totals_a_cent_apart_then_files_when_fixed(client, db):
    headers, j = setup_owner(client, db)
    client.patch(f"/jobs/{j['id']}", headers=headers, json={"status": "1.5-OrdPO"})
    assert _stage4(client, carter_po_total="12345.66")["flagged"] == 1
    db.expire_all()
    assert _job(db).status is JobStatus.ordpo
    assert _stage4(client)["updated"] == 1
    db.expire_all()
    assert _job(db).status is JobStatus.ord
    assert not handoff.open_holds(db, _job(db))  # the earlier stage 4 hold cleared


def test_stage4_waits_on_a_measure_hold(client, db):
    headers, j = setup_owner(client, db)
    client.patch(f"/jobs/{j['id']}", headers=headers, json={"status": "1.5-OrdPO"})
    _hold(db, db.get(Job, j["id"]), "measure_discrepancy")
    assert _stage4(client)["flagged"] == 1
    db.expire_all()
    assert _job(db).status is JobStatus.ordpo


def test_builder_po_open_means_ready_to_order_not_ordered(client, db):
    from app.feeds import _bump_to_ordered

    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.status = JobStatus.track
    db.commit()
    assert _bump_to_ordered(job, "VendorSuite feed") is True
    db.commit()
    assert job.status is JobStatus.ndord
    ev = db.query(JobEvent).filter(JobEvent.kind == "builder_po_open").one()
    assert ev.actor == "VendorSuite feed"
    job.status = JobStatus.ordsub
    db.commit()
    assert _bump_to_ordered(job) is False and job.status is JobStatus.ordsub


def test_feed_po_change_goes_on_the_timeline(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    job.builder_po, job.po_amount = "201526", Decimal("4005.00")
    db.commit()
    handoff.feed_po_changed(db, job, "2015126", Decimal("4005.00"), "VendorSuite feed")
    db.commit()
    ev = db.query(JobEvent).filter(JobEvent.kind == "po_changed").one()
    assert "likely a typo" in ev.issues[0]


class _NoSheets:
    """Stands in for Sterling's session: no cover sheet on file."""

    def query(self, *_):
        return self

    def filter(self, *_):
        return self

    def order_by(self, *_):
        return self

    def first(self):
        return None


def _sterling_job(**over):
    from app.sterling_app.models import JobType

    line = SimpleNamespace(sku="B36", qty=1, list_price=Decimal("640.00"))
    room = SimpleNamespace(name="Kitchen", zone=None, cabinet_brand="Everluxe", series=None,
                           door_style="Shaker", finish="White", lines=[line])
    base = dict(id=7, name="Lot 62", builder="DR Horton", community="Liberty", lot_number="62",
                address="62 Test Ln", plan="Madison", job_type=JobType.tract, sales_contact_name="Brian",
                field_contact_name="DRH Superintendent", field_contact_phone=None, rooms=[room])
    base.update(over)
    return SimpleNamespace(**base)


def test_sterling_payload_borrows_the_subdivision_code_prefix(client, db):
    from app.models import Account, AccountType, Community, JobType
    from app.sterling_app.export_cabinettron import sold_payload

    acct = Account(name="DR Horton", type=AccountType.builder)
    db.add(acct)
    db.flush()
    comm = Community(account_id=acct.id, name="Liberty")
    db.add(comm)
    db.flush()
    db.add(Job(job_code="DRLB50-0061", account_id=acct.id, community_id=comm.id, lot_number="0061",
               address="61 Test Ln", job_type=JobType.tract, sales_contact_name="x", field_contact_name="y"))
    db.commit()
    data = sold_payload(_NoSheets(), db, _sterling_job())
    assert data.job_code == "DRLB50-0062"
    assert [ln.sku for ln in data.lines] == ["B36"]
    out = handoff.sterling_sold(db, data, None)
    assert out["status"] == "1.2-NdOrd"


def test_sterling_without_a_job_code_says_where_to_put_one(client, db):
    import pytest
    from app.sterling_app.export_cabinettron import ExportError, sold_payload

    with pytest.raises(ExportError, match="cover sheet"):
        sold_payload(_NoSheets(), db, _sterling_job(community=None, lot_number=None, builder="Smith Remodel"))


def test_timeline_rows_carry_the_system_actor(client, db):
    _, j = setup_owner(client, db)
    job = db.get(Job, j["id"])
    handoff.log_agent(db, job, "stage4", [], payload={"at": datetime.now(UTC).isoformat()})
    db.commit()
    assert db.query(JobEvent).one().actor == "Order Pack agent"
