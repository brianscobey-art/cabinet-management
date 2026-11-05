"""25 test jobs for the COAST hand-offs, each carrying one real problem from
Brian's order history. Shared by tests/test_suite_handoffs.py (pytest) and
scripts/suite_test_run.py (the report).

Job codes, SKUs, PO numbers and amounts come from real jobs and emails; the
rest of each job (contacts, addresses, line prices) is filled in so the job is
complete. Nothing here touches the live database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.auth.security import hash_password
from app.models import Job, JobStatus, OrderingChecklist, Role, User, Visit
from app.pricing import line_total

TODAY = date.today()
PW = "password123"


@dataclass
class Scenario:
    n: int
    job: str
    issue: str
    expect: str
    run: callable


class Suite:
    """Talks to the hand-off API as each role would."""

    def __init__(self, client, db):
        self.c = client
        self.db = db
        self.tokens: dict[str, dict] = {}
        for role in Role:
            self.user(role.value, role, full_name=f"{role.value.title()} Person")

    def user(self, key: str, role: Role, full_name: str) -> None:
        email = f"{key}@test.local"
        self.db.add(User(email=email, full_name=full_name, hashed_password=hash_password(PW), role=role))
        self.db.commit()
        r = self.c.post("/auth/token", data={"username": email, "password": PW})
        assert r.status_code == 200, r.text
        self.tokens[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def post(self, path: str, body: dict, as_: str = "admin"):
        return self.c.post(f"/suite{path}", json=body, headers=self.tokens[as_])

    def ok(self, path: str, body: dict, as_: str = "admin") -> dict:
        r = self.post(path, body, as_)
        assert r.status_code == 200, f"{path} expected 200, got {r.status_code}: {r.text}"
        return r.json()

    def refused(self, path: str, body: dict, as_: str = "admin", code: int = 422) -> dict:
        r = self.post(path, body, as_)
        assert r.status_code == code, f"{path} expected {code}, got {r.status_code}: {r.text}"
        return r.json().get("detail", {})

    def job(self, code: str) -> Job:
        self.db.expire_all()
        return self.db.query(Job).filter(Job.job_code == code).one()

    def status(self, code: str) -> str:
        return self.job(code).status.value

    def checklist(self, code: str) -> OrderingChecklist | None:
        return self.db.query(OrderingChecklist).filter(OrderingChecklist.job_id == self.job(code).id).first()

    def timeline(self, code: str) -> dict:
        r = self.c.get(f"/suite/jobs/{code}/timeline", headers=self.tokens["admin"])
        assert r.status_code == 200, r.text
        return r.json()

    # ---- the normal path, one step at a time -------------------------------

    LINES = [("B36", 1, "640.00"), ("W3636", 2, "410.00"), ("SB36", 1, "590.00"), ("DB18-3", 1, "520.00")]

    def sold(self, code: str, *, lines=None, rooms=None, **kw) -> dict:
        lines = self.LINES if lines is None else lines
        body = {
            "job_code": code,
            "account_name": kw.pop("account", "DR Horton"),
            "account_type": "builder",
            "job_type": "tract",
            "community": kw.pop("community", "Liberty"),
            "lot_number": kw.pop("lot", None) or code.split("-")[-1][-4:],
            "address": kw.pop("address", f"{int(code.split('-')[-1][-4:])} Test Lane, Freeport FL"),
            "plan": kw.pop("plan", "DRH Madison STD"),
            "sales_contact_name": "Builder Purchasing",
            "field_contact_name": kw.pop("field_contact", "DRH Superintendent"),
            "builder_po": kw.pop("builder_po", None),
            "po_amount": kw.pop("po_amount", None),
            "rooms": rooms if rooms is not None else [{"room": "Kitchen", "door_style": "Shaker", "finish": "White"}],
            "lines": [{"sku": s, "qty": q, "list_price": p, "room": "Kitchen"} for s, q, p in lines],
        }
        body.update(kw)
        return body

    @staticmethod
    def net(lines) -> list[dict]:
        return [{"sku": s, "qty": q, "price": str(line_total(Decimal(p), 1))} for s, q, p in lines]

    @staticmethod
    def total(lines) -> str:
        return str(sum((line_total(Decimal(p), 1) * q for s, q, p in lines), Decimal(0)))

    def order(self, code: str, lines=None, **kw) -> dict:
        lines = self.LINES if lines is None else lines
        return {"job_code": code, "vendor": "Everluxe", "lines": self.net(lines), "order_total": self.total(lines), **kw}

    def so(self, code: str, so_number: str, lines=None, **kw) -> dict:
        lines = self.LINES if lines is None else lines
        sub = Decimal(self.total(lines))
        boxes = sum(q for _, q, _ in lines)
        return {"job_code": code, "so_number": so_number, "so_subtotal": str(sub),
                "so_total": str(sub + 10 * boxes + Decimal("85.00")), "lines": self.net(lines), **kw}

    def po(self, code: str, po_number: str, so_number: str, total: str, **kw) -> dict:
        return {"job_code": code, "carter_po_number": po_number, "carter_po_total": total,
                "carter_po_date": TODAY.isoformat(), "so_number": so_number, **kw}

    def to_ordered(self, code: str, so_number: str, po_number: str, **sold_kw) -> None:
        self.ok("/sterling/sold", self.sold(code, **sold_kw))
        self.ok("/optimus/order-sent", self.order(code))
        so = self.ok("/optimus/so-back", self.so(code, so_number))
        assert so["status"] == "1.4-OrdSub", so
        total = str(self.checklist(code).so_total)
        po = self.ok("/optimus/po-back", self.po(code, po_number, so_number, total))
        assert po["status"] == "2.0-Ord", po


def codes(answer: dict) -> str:
    return " | ".join(answer.get("issues", []))


def expect_issue(answer: dict, text: str) -> None:
    assert any(text.lower() in i.lower() for i in answer.get("issues", [])), f"expected '{text}' in {answer}"


# --------------------------------------------------------------------------- the 25


def s01(s: Suite):
    """PO typo between the schedule email and the tracker (same dollars)."""
    early = s.ok("/feeds/schedule", {"builder_po": "201526", "community": "Liberty", "lot_number": "0135",
                                     "measure_date": (TODAY + timedelta(days=2)).isoformat()})
    assert early["level"] == "warn", early  # no job yet: parked
    s.ok("/sterling/sold", s.sold("DRID60-0135", builder_po="201526", po_amount="4005.00"))
    assert s.job("DRID60-0135").measure_date == TODAY + timedelta(days=2), "parked schedule row never landed on the job"
    a = s.ok("/feeds/schedule", {"builder_po": "2015126", "po_amount": "4005.00", "community": "Liberty",
                                 "lot_number": "0135", "measure_date": (TODAY + timedelta(days=3)).isoformat()})
    assert a["level"] == "warn", a
    expect_issue(a, "likely a typo")
    assert s.job("DRID60-0135").measure_date == TODAY + timedelta(days=3)


def s02(s: Suite):
    """Supplier swapped RW SKUs for the plain ones; SO came back $162.54 short."""
    lines = [("B36", 1, "640.00"), ("W3636", 1, "410.00"), ("SB36", 1, "590.00")]
    s.ok("/sterling/sold", s.sold("DROP-0060", lines=lines))
    s.ok("/optimus/order-sent", s.order("DROP-0060", lines))
    bad = [("RWB36", 1, "640.00"), ("RWW3636", 1, "410.00"), ("SB36", 1, "590.00")]
    body = s.so("DROP-0060", "SO-60060", bad)
    body["so_subtotal"] = str(Decimal(s.total(lines)) - Decimal("162.54"))
    a = s.ok("/optimus/so-back", body)
    assert a["level"] == "hold", a
    expect_issue(a, "RWB36 in place of B36")
    expect_issue(a, "off by $-162.54")
    assert s.status("DROP-0060") == "1.3-Ord Prcss"
    fixed = s.ok("/optimus/so-back", s.so("DROP-0060", "SO-60060", lines))
    assert fixed["status"] == "1.4-OrdSub" and not s.timeline("DROP-0060")["open_holds"], fixed


def s03(s: Suite):
    """Out of stock on the SO (SWW3924); goes on, with a warning."""
    lines = [("B36", 1, "640.00"), ("SWW3924", 2, "355.00")]
    s.ok("/sterling/sold", s.sold("DROP-0055", lines=lines))
    s.ok("/optimus/order-sent", s.order("DROP-0055", lines))
    a = s.ok("/optimus/so-back", s.so("DROP-0055", "SO-60055", lines, out_of_stock=["SWW3924"]))
    assert a["level"] == "warn" and a["status"] == "1.4-OrdSub", a
    expect_issue(a, "SWW3924 is out of stock")
    clean_total = str(s.checklist("DROP-0055").so_total)
    revised = s.ok("/optimus/so-back", s.so("DROP-0055", "SO-60055", [("RWB36", 1, "640.00"), ("SWW3924", 2, "355.00")]))
    assert revised["level"] == "hold", revised
    po = s.ok("/optimus/po-back", s.po("DROP-0055", "750006155", "SO-60055", clean_total))
    assert po["level"] == "hold" and po["status"] == "1.4-OrdSub", f"PO went through on a held SO: {po}"


def s04(s: Suite):
    """Drawing shows 2 x W3636 that never made it onto the order."""
    s.ok("/sterling/sold", s.sold("DRHACR-2016"))
    short = [ln for ln in s.LINES if ln[0] != "W3636"]
    a = s.ok("/optimus/order-sent", s.order("DRHACR-2016", short))
    assert a["level"] == "hold" and a["status"] == "1.2-NdOrd", a
    expect_issue(a, "Sold 2 x W3636 but ordered 0")
    b = s.ok("/optimus/order-sent", s.order("DRHACR-2016"))
    assert b["status"] == "1.3-Ord Prcss" and not s.timeline("DRHACR-2016")["open_holds"], b


def s05(s: Suite):
    """Two different jobs ordered with identical lines (DRSABR-1012 / DROPE-3021)."""
    s.ok("/sterling/sold", s.sold("DRSABR-1012", community="Sabal Ridge"))
    s.ok("/sterling/sold", s.sold("DROPE-3021", community="Oak Preserve"))
    s.ok("/optimus/order-sent", s.order("DRSABR-1012"))
    a = s.ok("/optimus/order-sent", s.order("DROPE-3021"))
    assert a["level"] == "warn", a
    expect_issue(a, "Identical lines to the order for DRSABR-1012")


def s06(s: Suite):
    """Same lot ID 268340074 in two subdivisions must stay two jobs."""
    s.ok("/sterling/sold", s.sold("DRLB50-0074", community="Liberty", lot="268340074"))
    s.ok("/sterling/sold", s.sold("DRCOMP-0074", community="Compass Lakes", lot="268340074"))
    a = s.ok("/feeds/schedule", {"community": "Compass Lakes", "lot_number": "268340074",
                                 "install_date": (TODAY + timedelta(days=20)).isoformat()})
    assert a["job_code"] == "DRCOMP-0074", a
    assert s.job("DRLB50-0074").install_date is None
    d = s.refused("/sterling/sold", s.sold("DRLB50-0999", community="Liberty", lot="268340074"))
    expect_issue(d, "already job DRLB50-0074")


def s07(s: Suite):
    """Century PO written with an underscore in one place and not the other."""
    s.ok("/feeds/job-setup", {"request_number": "7700", "builder_po": "8211023000583", "po_amount": "3900.00",
                              "g_code": "G-583", "i_code": "I-583"})  # arrives before the sale
    s.ok("/sterling/sold", s.sold("CCOL-0583", account="Century Complete", community="Clear Lake",
                                  builder_po="8211023_000583", po_amount="3900.00"))
    assert s.job("CCOL-0583").g_code == "G-583", "parked setup email never landed on the job"
    s.ok("/sterling/sold", s.sold("CCOL-0582", account="Century Complete", community="Clear Lake",
                                  builder_po="8211023_000582", po_amount="3870.00"))
    a = s.ok("/feeds/job-setup", {"request_number": "7701", "builder_po": "8211023000582",
                                  "po_amount": "3870.00", "g_code": "G-582", "i_code": "I-582"})
    assert a["job_code"] == "CCOL-0582" and a["level"] == "ok", a
    j = s.job("CCOL-0582")
    assert (j.g_code, j.i_code) == ("G-582", "I-582")
    again = s.ok("/feeds/job-setup", {"request_number": "7701", "builder_po": "8211023000582",
                                      "g_code": "G-999"})
    assert again["level"] == "warn" and s.job("CCOL-0582").g_code == "G-582", again


def s08(s: Suite):
    """A cancelled Carter PO (750005976) comes back on the job."""
    s.ok("/sterling/sold", s.sold("DROP-0009"))
    s.ok("/optimus/order-sent", s.order("DROP-0009"))
    s.ok("/optimus/so-back", s.so("DROP-0009", "SO-60009"))
    total = str(s.checklist("DROP-0009").so_total)
    d = s.refused("/optimus/po-back", s.po("DROP-0009", "750005976", "SO-60009", total))
    expect_issue(d, "was cancelled")
    assert s.status("DROP-0009") == "1.4-OrdSub"
    a = s.ok("/optimus/po-back", s.po("DROP-0009", "750006120", "SO-60009", total))
    assert a["status"] == "2.0-Ord", a


def s09(s: Suite):
    """Ashley's setup code CAB OMD60 135 with a PO that doesn't match CabinetTron."""
    s.ok("/sterling/sold", s.sold("DRID60-0136", community="Indian Lakes", builder_po="201536", po_amount="4005.00"))
    a = s.ok("/feeds/job-setup", {"request_number": "7702", "builder_po": "2015136", "po_amount": "4005.00",
                                  "ashley_code": "CAB OMD60 136", "g_code": "G-136"})
    assert a["level"] == "hold" and a["job_code"] == "DRID60-0136", a
    expect_issue(a, "likely a typo on one side")
    assert s.job("DRID60-0136").g_code is None  # nothing written while the PO is in question


def s10(s: Suite):
    """Appliance placeholders on the quote, and one slipped onto the order."""
    lines = s.LINES + [("RANGE1.30", 1, "0"), ("REF.2D.36", 1, "0"), ("DISHW24", 1, "0")]
    a = s.ok("/sterling/sold", s.sold("DRGALA-0210", lines=lines))
    for sku in ("RANGE1.30", "REF.2D.36", "DISHW24"):
        expect_issue(a, f"Dropped {sku}")
    d = s.refused("/optimus/order-sent", s.order("DRGALA-0210", s.LINES + [("DISHW24", 1, "100.00")]))
    expect_issue(d, "DISHW24 is an appliance placeholder")
    assert s.status("DRGALA-0210") == "1.2-NdOrd"


def s11(s: Suite):
    """Install marked complete with a future date (scheduled is not installed)."""
    s.to_ordered("DRPAG-0044", "SO-44", "750006144")
    d = s.refused("/tailgate/install", {"job_code": "DRPAG-0044", "installed_on": (TODAY + timedelta(days=2)).isoformat(),
                                        "complete": True, "photos": 6})
    expect_issue(d, "in the future")
    assert s.status("DRPAG-0044") == "2.0-Ord"


def s12(s: Suite):
    """A void job keeps getting schedule rows and a PO."""
    s.ok("/sterling/sold", s.sold("DRGVTH-0012", builder_po="300112"))
    j = s.job("DRGVTH-0012")
    j.status = JobStatus.void  # the office voids it
    s.db.commit()
    a = s.ok("/feeds/schedule", {"job_code": "DRGVTH-0012", "install_date": (TODAY + timedelta(days=9)).isoformat()})
    assert a["level"] == "warn" and s.job("DRGVTH-0012").install_date is None, a
    d = s.refused("/optimus/po-back", s.po("DRGVTH-0012", "750006112", "SO-12", "100.00"))
    expect_issue(d, "never order or bill a void job")


def s13(s: Suite):
    """Installer tries to close out a job that isn't theirs, then their own."""
    s.to_ordered("DRHB60-0031", "SO-31", "750006131")
    j = s.job("DRHB60-0031")
    j.installer = "Installer Person"
    s.db.commit()
    s.to_ordered("DRHB60-0032", "SO-32", "750006132")
    s.refused("/tailgate/install", {"job_code": "DRHB60-0032", "installed_on": TODAY.isoformat(), "complete": True,
                                    "photos": 4}, as_="installer", code=403)
    a = s.ok("/tailgate/install", {"job_code": "DRHB60-0031", "installed_on": TODAY.isoformat(), "complete": True,
                                   "photos": 4, "install_pay": "850.00"}, as_="installer")
    assert a["status"] == "2.1-Inst", a
    s.ok("/tailgate/install", {"job_code": "DRHB60-0031", "installed_on": TODAY.isoformat(), "complete": True,
                               "photos": 4, "install_pay": "850.00"}, as_="installer")  # sent twice
    walk = s.db.query(Visit).filter(Visit.job_id == j.id, Visit.visit_type == "post_walk").one()
    assert walk.close_date == TODAY + timedelta(days=2)
    mine = s.c.get("/suite/tailgate/my-installs", headers=s.tokens["installer"]).json()
    assert [m["job_code"] for m in mine] == ["DRHB60-0031"], mine


def s14(s: Suite):
    """Each role only reaches the apps its job needs."""
    s.ok("/sterling/sold", s.sold("DRHBP3-0014"))
    s.refused("/optimus/order-sent", s.order("DRHBP3-0014"), as_="sales", code=403)
    s.refused("/sterling/sold", s.sold("DRHBP3-0015"), as_="field", code=403)
    s.refused("/sterling/sold", s.sold("DRHBP3-0015"), as_="ordering", code=403)
    s.refused("/autobot/field-check", {"job_code": "DRHBP3-0014", "visit_type": "field_measure",
                                       "done_on": TODAY.isoformat(), "passed": True}, as_="service_tech", code=403)
    s.refused("/tailgate/install", {"job_code": "DRHBP3-0014", "installed_on": TODAY.isoformat(), "complete": True},
              as_="field", code=403)
    a = s.ok("/optimus/order-sent", s.order("DRHBP3-0014"), as_="ordering")
    assert a["status"] == "1.3-Ord Prcss", a
    acc = s.c.get("/suite/access", headers=s.tokens["installer"]).json()
    assert acc["apps"] == {"cabinettron": "none", "sterling": "none", "optimus": "none", "autobot": "none",
                           "tailgate": "own"}, acc


def s15(s: Suite):
    """Field measure doesn't match the drawing; ordering must wait."""
    s.ok("/sterling/sold", s.sold("DRLB50-0062"))
    a = s.ok("/autobot/field-check", {"job_code": "DRLB50-0062", "visit_type": "field_measure", "done_on": TODAY.isoformat(),
                                      "passed": False, "discrepancies": ["Sink wall 3 in. short of the layout"]}, as_="field")
    assert a["level"] == "hold", a
    expect_issue(a, "send to DRH Superintendent")
    d = s.refused("/optimus/order-sent", s.order("DRLB50-0062"))
    expect_issue(d, "measure_discrepancy")
    s.ok("/autobot/field-check", {"job_code": "DRLB50-0062", "visit_type": "field_measure", "done_on": TODAY.isoformat(),
                                  "passed": True}, as_="field")
    b = s.ok("/optimus/order-sent", s.order("DRLB50-0062"))
    assert b["status"] == "1.3-Ord Prcss", b
    s.ok("/sterling/sold", s.sold("DRLB50-0063"))
    s.ok("/optimus/order-sent", s.order("DRLB50-0063"))
    s.ok("/optimus/so-back", s.so("DRLB50-0063", "SO-63"))
    s.ok("/autobot/field-check", {"job_code": "DRLB50-0063", "visit_type": "field_measure", "done_on": TODAY.isoformat(),
                                  "passed": False, "discrepancies": ["Range wall 2 in. long"]}, as_="field")
    po = s.ok("/optimus/po-back", s.po("DRLB50-0063", "750006163", "SO-63", str(s.checklist("DRLB50-0063").so_total)))
    assert po["level"] == "hold" and po["status"] == "1.4-OrdSub", f"Carter PO cut over an open measure problem: {po}"


def s16(s: Suite):
    """Carter PO total a few cents off the SO total."""
    s.ok("/sterling/sold", s.sold("DROP-0016"))
    s.ok("/optimus/order-sent", s.order("DROP-0016"))
    s.ok("/optimus/so-back", s.so("DROP-0016", "SO-16"))
    total = s.checklist("DROP-0016").so_total
    a = s.ok("/optimus/po-back", s.po("DROP-0016", "750006116", "SO-16", str(total - Decimal("0.03"))))
    assert a["level"] == "hold" and a["status"] == "1.4-OrdSub", a
    expect_issue(a, "must match to the cent")
    b = s.ok("/optimus/po-back", s.po("DROP-0016", "750006116", "SO-16", str(total)))
    assert b["status"] == "2.0-Ord" and not s.timeline("DROP-0016")["open_holds"], b


def s17(s: Suite):
    """Carter PO arrives before the SO."""
    s.ok("/sterling/sold", s.sold("DROP-0017"))
    s.ok("/optimus/order-sent", s.order("DROP-0017"))
    a = s.ok("/optimus/po-back", s.po("DROP-0017", "750006117", "SO-17", "1000.00"))
    assert a["level"] == "hold" and a["status"] == "1.3-Ord Prcss", a
    expect_issue(a, "before a clean SO")


def s18(s: Suite):
    """Sold without a finish picked for the island."""
    rooms = [{"room": "Kitchen", "door_style": "Shaker", "finish": "White"},
             {"room": "Island", "door_style": "Shaker", "finish": ""}]
    a = s.ok("/sterling/sold", s.sold("CCGO-0118", account="Century Complete", community="Gulf Oaks", rooms=rooms))
    assert a["level"] == "hold" and a["status"] == "1.1-PreOrd", a
    expect_issue(a, "Island is missing finish")
    d = s.refused("/optimus/order-sent", s.order("CCGO-0118"))
    expect_issue(d, "selections_incomplete")
    rooms[1]["finish"] = "Navy"
    b = s.ok("/sterling/sold", s.sold("CCGO-0118", account="Century Complete", community="Gulf Oaks", rooms=rooms))
    assert b["status"] == "1.2-NdOrd" and not s.timeline("CCGO-0118")["open_holds"], b


def s19(s: Suite):
    """Sterling's total doesn't match list x 0.217."""
    body = s.sold("DRPAG-0119")
    body["quote_total"] = "999.99"
    a = s.ok("/sterling/sold", body)
    assert a["level"] == "hold", a
    expect_issue(a, "at 0.217")


def s20(s: Suite):
    """Sterling resends a quote after the job is already ordered."""
    s.ok("/sterling/sold", s.sold("DRHB60-0021"))
    s.ok("/optimus/order-sent", s.order("DRHB60-0021"))
    mid = s.ok("/sterling/sold", s.sold("DRHB60-0021", lines=s.LINES + [("W3036", 1, "380.00")]))
    assert mid["level"] == "hold", f"quote changed after the order went out, nobody told: {mid}"
    s.to_ordered("DRHB60-0020", "SO-20", "750006220")
    d = s.refused("/sterling/sold", s.sold("DRHB60-0020", lines=s.LINES + [("W3036", 1, "380.00")]))
    expect_issue(d, "change order")
    assert s.status("DRHB60-0020") == "2.0-Ord"


def s21(s: Suite):
    """Feed tries to move an install date the office already set."""
    s.ok("/sterling/sold", s.sold("DRLB50-0021", builder_po="400121"))
    j = s.job("DRLB50-0021")
    j.install_date = TODAY + timedelta(days=14)
    s.db.commit()
    a = s.ok("/feeds/schedule", {"builder_po": "400121", "install_date": (TODAY + timedelta(days=10)).isoformat()})
    assert a["level"] == "warn", a
    assert s.job("DRLB50-0021").install_date == TODAY + timedelta(days=14)


def s22(s: Suite):
    """Install pay: never invented, never zero."""
    s.to_ordered("CCOL-0122", "SO-122", "750006222", account="Century Complete", community="Clear Lake")
    d = s.refused("/tailgate/install", {"job_code": "CCOL-0122", "installed_on": TODAY.isoformat(), "complete": True,
                                        "photos": 3, "install_pay": "0"})
    expect_issue(d, "isn't a real amount")
    a = s.ok("/tailgate/install", {"job_code": "CCOL-0122", "installed_on": TODAY.isoformat(), "complete": True,
                                   "photos": 3}, as_="installer_coordinator")
    assert a["level"] == "warn" and s.checklist("CCOL-0122").install_pay is None, a


def s23(s: Suite):
    """Walks out of order, then parts, punch and blue tape in order."""
    s.to_ordered("DRGALA-0023", "SO-23", "750006223")
    walk = {"job_code": "DRGALA-0023", "visit_type": "post_walk", "done_on": TODAY.isoformat(), "passed": True}
    d = s.refused("/autobot/field-check", walk, as_="inspector")
    expect_issue(d, "needs the install done")
    s.ok("/tailgate/install", {"job_code": "DRGALA-0023", "installed_on": TODAY.isoformat(), "complete": True,
                               "photos": 5, "install_pay": "900.00"}, as_="installer_coordinator")
    a = s.ok("/autobot/field-check", {**walk, "passed": False, "parts_needed": ["Door W3036 scratched"]}, as_="inspector")
    assert a["status"] == "3.1-Parts", a
    b = s.ok("/autobot/field-check", walk, as_="inspector")
    assert b["status"] == "4.0-Punch", b
    c = s.ok("/autobot/field-check", {**walk, "visit_type": "punch_out"}, as_="inspector")
    assert c["status"] == "4.1-Blue" and not s.timeline("DRGALA-0023")["open_holds"], c


def s24(s: Suite):
    """Ashley's FERR0001 style code instead of a CabinetTron job code."""
    d = s.refused("/sterling/sold", s.sold("FERR0001", lot="0001"))
    expect_issue(d, "not in the PREFIX-0000 format")
    tl = s.c.get("/suite/jobs/FERR0001/timeline", headers=s.tokens["admin"])
    assert tl.status_code == 404  # refused, so no job was made
    un = s.c.get("/suite/unmatched", headers=s.tokens["admin"])
    assert un.status_code == 200 and any(e["job_code"] == "FERR0001" for e in un.json()), "refused hand-off is invisible"


def s25(s: Suite):
    """Same supplier SO number shows up on a second job (DROP-0054 / DROP-0006)."""
    s.ok("/sterling/sold", s.sold("DROP-0054"))
    s.ok("/sterling/sold", s.sold("DROP-0006"))
    s.ok("/optimus/order-sent", s.order("DROP-0054"))
    s.ok("/optimus/order-sent", s.order("DROP-0006"))
    s.ok("/optimus/so-back", s.so("DROP-0054", "SO-60054"))
    d = s.refused("/optimus/so-back", s.so("DROP-0006", "SO-60054"))
    expect_issue(d, "already on job DROP-0054")
    d2 = s.refused("/optimus/so-back", s.so("DROP-0006", "so-60054"))
    expect_issue(d2, "already on job DROP-0054")


SCENARIOS = [
    Scenario(1, "DRID60-0135", "Schedule PO 2015126 vs tracker 201526, same $4,005", "Warn as a likely typo, keep the dates", s01),
    Scenario(2, "DROP-0060", "Supplier sent RWB36/RWW3636 for B36/W3636, SO $162.54 short", "Hold the SO, clear it when corrected", s02),
    Scenario(3, "DROP-0055", "SWW3924 out of stock on the SO", "Goes to 1.4 with a warning", s03),
    Scenario(4, "DRHACR-2016", "2 x W3636 on the drawing, not on the order", "Hold the order until it matches the sold quote", s04),
    Scenario(5, "DROPE-3021", "Identical lines to DRSABR-1012's order", "Warn of a possible double order", s05),
    Scenario(6, "DRCOMP-0074", "Lot ID 268340074 in two subdivisions", "Two jobs; feed finds the right one; same-subdivision reuse refused", s06),
    Scenario(7, "CCOL-0582", "PO 8211023_000582 vs 8211023000582; setup email sent twice", "Match the PO, set G/I once", s07),
    Scenario(8, "DROP-0009", "Cancelled Carter PO 750005976", "Refuse it, accept the new PO", s08),
    Scenario(9, "DRID60-0136", "Ashley code CAB OMD60 136, PO off by a digit", "Find the job from the code, hold the PO question", s09),
    Scenario(10, "DRGALA-0210", "RANGE1.30, REF.2D.36, DISHW24 on the quote and order", "Drop from the quote, refuse on the order", s10),
    Scenario(11, "DRPAG-0044", "Install marked complete with a future date", "Refuse; stays 2.0-Ord", s11),
    Scenario(12, "DRGVTH-0012", "Void job still getting schedule rows and a PO", "Ignore the schedule, refuse the PO", s12),
    Scenario(13, "DRHB60-0031", "Installer closing a job that isn't theirs", "403 on theirs-not, 2.1 + 48h walk on their own", s13),
    Scenario(14, "DRHBP3-0014", "Roles reaching apps outside their job", "403 for each, ordering can order", s14),
    Scenario(15, "DRLB50-0062", "Field measure 3 in. short of the layout", "Hold ordering, route to the field contact", s15),
    Scenario(16, "DROP-0016", "Carter PO $0.03 under the SO", "Hold, never bypassed; clears when it matches", s16),
    Scenario(17, "DROP-0017", "Carter PO before the SO", "Hold until the SO is checked", s17),
    Scenario(18, "CCGO-0118", "Island sold with no finish", "Park at 1.1, refuse the order, clear on resend", s18),
    Scenario(19, "DRPAG-0119", "Sterling total not list x 0.217", "Hold the sale", s19),
    Scenario(20, "DRHB60-0020", "Quote resent after the job is ordered", "Refuse; needs a change order", s20),
    Scenario(21, "DRLB50-0021", "Feed moves the office's install date", "Keep the office date, warn", s21),
    Scenario(22, "CCOL-0122", "Install pay blank or $0", "Refuse $0, leave blank for the office", s22),
    Scenario(23, "DRGALA-0023", "Walk before install, then parts, punch, blue tape", "Refuse early walk, then 3.1, 4.0, 4.1", s23),
    Scenario(24, "FERR0001", "Ashley's FERR0001 code instead of a job code", "Refuse, make no job", s24),
    Scenario(25, "DROP-0006", "SO number already on DROP-0054", "Refuse the second SO", s25),
]
