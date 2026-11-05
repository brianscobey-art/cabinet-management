"""Every COAST hand-off into CabinetTron, with its double checks.

One function per hand-off. Each one:
1. finds the job (or refuses),
2. runs the double checks and collects findings (ok / warn / hold / reject),
3. changes the job only when nothing rejected it, moving status through ladder.py,
4. writes one JobEvent row (the job timeline), even for a rejection.

A "hold" saves what was sent but stops the job's next step until a clean
hand-off of the same kind clears it (hold_code). A "reject" changes nothing.
The checks come from the problems in Brian's own order history (PO typos, RW vs
SW substitutions, duplicate orders, lot collisions, cancelled Carter POs...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountType,
    Community,
    Job,
    JobEvent,
    JobStatus,
    JobType,
    OrderingChecklist,
    Quote,
    QuoteLineItem,
    QuoteStatus,
    Role,
    RoomSelection,
    User,
    Visit,
)
from app.pricing import DEALER_MULTIPLIER, is_excluded, line_total, money
from app.suite import ladder
from app.suite.schemas import (
    FieldCheckIn,
    InstallIn,
    JobSetupIn,
    OrderSentIn,
    PoBackIn,
    ScheduleIn,
    SoBackIn,
    SoldIn,
)

_LEVEL_RANK = {"ok": 0, "warn": 1, "hold": 2, "reject": 3}

# Open holds that must stop Carter's PO (money committed), not just the order.
PO_BLOCKERS = {"measure_discrepancy", "builder_po_cancelled", "quote_changed_after_order",
               "so_total_mismatch", "sku_substitution", "so_extra_sku", "so_missing_sku"}

JOB_CODE_RE = re.compile(r"^[A-Z0-9]{2,8}-\d{3,4}$")

# Carter POs cancelled in the history; a PO-back carrying one is refused.
CANCELLED_CARTER_POS = {"750005976", "750005977"}

# Ashley's job-setup codes -> CabinetTron job-code prefixes (from the setup emails).
ASHLEY_PREFIX = {
    "LE50": "DRLB50",
    "HB60": "DRHB60",
    "OP70": "DROP",
    "CL": "CCOL",
    "GOC": "CCGO",
    "PG": "DRPAG",
    "IND60": "DRID60",
    "OMD60": "DRID60",
    "GL": "DRGALA",
    "GVTH": "DRGVTH",
    "HBPH3": "DRHBP3",
}

# Suppliers sometimes ship a "RW" (ready-to-wrap) SKU in place of the plain one
# (RWB36 for B36, RWW3636 for W3636) -- the DROP-0060 short SO.
SUBSTITUTION_PREFIXES = ("RW", "SW")


# --------------------------------------------------------------------------- helpers


@dataclass
class Result:
    findings: list[tuple[str, str, str]] = field(default_factory=list)  # (level, code, text)

    def add(self, level: str, code: str, text: str) -> None:
        self.findings.append((level, code, text))

    @property
    def level(self) -> str:
        return max((f[0] for f in self.findings), key=_LEVEL_RANK.get, default="ok")

    @property
    def issues(self) -> list[str]:
        return [f[2] for f in self.findings]

    @property
    def hold_code(self) -> str | None:
        holds = [f[1] for f in self.findings if f[0] == "hold"]
        return holds[0] if holds else None

    @property
    def rejected(self) -> bool:
        return self.level == "reject"


def norm_po(value: str | None) -> str:
    """'8211023_000582' == '8211023000582'; '201526 ON' == '201526'."""
    if not value:
        return ""
    s = re.sub(r"[^A-Z0-9]", "", value.upper())
    if s.endswith("ON") and s[:-2].isdigit():
        s = s[:-2]
    return s


def norm_code(value: str | None) -> str:
    return (value or "").strip().upper()


def norm_so(value: str | None) -> str:
    """'so-60054' == 'SO-60054' == 'SO 60054'."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def norm_sku(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").upper())


def _cents(value) -> Decimal | None:
    return None if value is None else money(value)


def _today() -> date:
    return datetime.now(UTC).date()


def job_by_code(db: Session, code: str | None) -> Job | None:
    code = norm_code(code)
    if not code:
        return None
    return db.query(Job).filter(Job.job_code == code).first()


def open_holds(db: Session, job: Job) -> list[JobEvent]:
    return (
        db.query(JobEvent)
        .filter(JobEvent.job_id == job.id, JobEvent.level == "hold", JobEvent.resolved_at.is_(None))
        .order_by(JobEvent.id)
        .all()
    )


def _resolve(db: Session, job: Job, codes: set[str], event: JobEvent) -> list[str]:
    cleared = []
    for h in open_holds(db, job):
        if h.hold_code in codes:
            h.resolved_at = datetime.now(UTC)
            h.resolved_by_event = event.id
            cleared.append(h.hold_code)
    return cleared


def _checklist(db: Session, job: Job) -> OrderingChecklist:
    cl = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
    if cl is None:
        cl = OrderingChecklist(job_id=job.id, steps={})
        db.add(cl)
        db.flush()
    return cl


def _move(r: Result, job: Job, target: JobStatus) -> tuple[str, str] | None:
    """Move status through the ladder; a refusal becomes a reject finding."""
    try:
        if ladder.check_move(job.status, target):
            before = job.status.value
            job.status = target
            return before, target.value
    except ladder.LadderError as exc:
        r.add("reject", "ladder", str(exc))
    return None


def _save(
    db: Session,
    *,
    source: str,
    kind: str,
    r: Result,
    job: Job | None,
    job_code: str | None,
    actor: User | str | None,
    payload: dict | None = None,
    moved: tuple[str, str] | None = None,
    note: str | None = None,
) -> JobEvent:
    ev = JobEvent(
        job_id=job.id if job is not None and job.id is not None else None,
        job_code=norm_code(job_code) or (job.job_code if job is not None else None),
        source=source,
        kind=kind,
        level=r.level,
        issues=r.issues or None,
        hold_code=r.hold_code,
        status_from=moved[0] if moved else None,
        status_to=moved[1] if moved else None,
        payload=payload,
        note=note,
        actor=actor if isinstance(actor, str) else (actor.email if actor else None),
    )
    db.add(ev)
    db.flush()
    return ev


def _answer(r: Result, ev: JobEvent, job: Job | None, extra: dict | None = None) -> dict:
    out = {
        "level": r.level,
        "event_id": ev.id,
        "job_code": ev.job_code,
        "status": job.status.value if job is not None and job.id is not None else None,
        "issues": r.issues,
        "hold_code": r.hold_code,
    }
    if extra:
        out.update(extra)
    return out


def _finish(db: Session, r: Result, ev: JobEvent, job: Job | None, extra: dict | None = None) -> dict:
    """Commit, or for a rejection throw away every change but keep a timeline row saying why."""
    if r.rejected:
        keep = {c: getattr(ev, c) for c in ("job_code", "source", "kind", "level", "issues", "hold_code",
                                             "payload", "note", "actor")}
        job_id = job.id if job is not None else None
        db.rollback()
        if job_id is not None and db.get(Job, job_id) is None:
            job_id = None
        row = JobEvent(job_id=job_id, **keep)
        db.add(row)
        db.commit()
        raise HTTPException(status_code=422, detail=_answer(r, row, None))
    db.commit()
    return _answer(r, ev, job, extra)


def _payload(model) -> dict:
    return model.model_dump(mode="json")


def _order_lines(ev: JobEvent | None) -> dict[str, int]:
    if ev is None or not ev.payload:
        return {}
    out: dict[str, int] = {}
    for ln in ev.payload.get("lines", []):
        out[norm_sku(ln["sku"])] = out.get(norm_sku(ln["sku"]), 0) + int(ln.get("qty", 1))
    return out


def _last_event(db: Session, job: Job, kind: str, *, clean_only: bool = False) -> JobEvent | None:
    q = db.query(JobEvent).filter(JobEvent.job_id == job.id, JobEvent.kind == kind)
    if clean_only:
        q = q.filter(JobEvent.level.in_(("ok", "warn")))
    else:
        q = q.filter(JobEvent.level != "reject")
    return q.order_by(JobEvent.id.desc()).first()


# --------------------------------------------------------------------------- Sterling


def _sold_lines(lines) -> dict[str, tuple[int, Decimal]]:
    out: dict[str, tuple[int, Decimal]] = {}
    for ln in lines:
        q, p = out.get(norm_sku(ln.sku), (0, Decimal(0)))
        out[norm_sku(ln.sku)] = (q + ln.qty, money(ln.list_price))
    return out


def _quote_lines(db: Session, job: Job) -> dict[str, tuple[int, Decimal]]:
    q = db.query(Quote).filter(Quote.job_id == job.id, Quote.status == QuoteStatus.accepted).first()
    return _sold_lines(q.lines) if q is not None else {}


def _apply_parked(db: Session, job: Job, ev: JobEvent) -> list[str]:
    """Feed rows that came in before the sale (no job yet) land on the new job now."""
    landed = []
    parked = (
        db.query(JobEvent)
        .filter(JobEvent.job_id.is_(None), JobEvent.source == "feed", JobEvent.level != "reject",
                JobEvent.kind.in_(("schedule", "job_setup")))
        .order_by(JobEvent.id)
        .all()
    )
    comm = job.community.name if job.community is not None else None
    for p in parked:
        d = p.payload or {}
        po_hit = bool(d.get("builder_po")) and bool(job.builder_po) and norm_po(d["builder_po"]) == norm_po(job.builder_po)
        lot_hit = bool(comm) and d.get("community") == comm and d.get("lot_number") == job.lot_number
        if not (po_hit or lot_hit or norm_code(d.get("job_code")) == job.job_code):
            continue
        if p.kind == "schedule":
            if d.get("measure_date") and not job.measure_date:
                job.measure_date = date.fromisoformat(d["measure_date"])
            if d.get("install_date") and not job.install_date:
                job.install_date = date.fromisoformat(d["install_date"])
        else:
            job.g_code = job.g_code or d.get("g_code")
            job.i_code = job.i_code or d.get("i_code")
        p.job_id = job.id
        p.resolved_at = datetime.now(UTC)
        p.resolved_by_event = ev.id
        landed.append(f"{p.kind} #{p.id}")
    return landed


def sterling_sold(db: Session, data: SoldIn, actor: User | None) -> dict:
    r = Result()
    code = norm_code(data.job_code)
    payload = _payload(data)

    if not JOB_CODE_RE.match(code):
        r.add("reject", "bad_job_code", f"Job code {data.job_code!r} is not in the PREFIX-0000 format")
        ev = _save(db, source="sterling", kind="sold", r=r, job=None, job_code=code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)

    try:
        acct_type = AccountType(data.account_type)
        job_type = JobType(data.job_type)
    except ValueError as exc:
        r.add("reject", "bad_type", str(exc))
        ev = _save(db, source="sterling", kind="sold", r=r, job=None, job_code=code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)

    lot = (data.lot_number or "").strip() or None
    if acct_type is AccountType.builder and not (data.community and lot):
        r.add("reject", "no_lot", "A builder job needs its subdivision and lot number")

    # Lines: drop excluded appliance placeholders, refuse nonsense.
    kept = []
    for ln in data.lines:
        if is_excluded(ln.sku):
            r.add("warn", "excluded_sku", f"Dropped {ln.sku.strip().upper()}: appliance placeholder, never ordered")
            continue
        if ln.qty <= 0:
            r.add("reject", "bad_qty", f"{ln.sku} has quantity {ln.qty}")
        if ln.list_price < 0:
            r.add("reject", "bad_price", f"{ln.sku} has a negative price")
        elif ln.list_price == 0:
            r.add("warn", "zero_price", f"{ln.sku} is priced at $0.00; check it is a no-charge item")
        kept.append(ln)
    if not kept:
        r.add("reject", "no_lines", "The sold quote has no cabinet lines")

    figured = sum((line_total(ln.list_price, ln.qty) for ln in kept if ln.qty > 0), Decimal(0))
    if data.quote_total is not None and kept and money(data.quote_total) != money(figured):
        r.add(
            "hold",
            "quote_total_mismatch",
            f"Sterling says ${money(data.quote_total):,} but the lines figure to ${money(figured):,} at {DEALER_MULTIPLIER}",
        )

    # Selections: every room needs a door style and a finish before it can be ordered.
    if not data.rooms:
        r.add("hold", "selections_incomplete", "No room selections came with the sale")
    for rm in data.rooms:
        missing = [n for n, v in (("door style", rm.door_style), ("finish", rm.finish)) if not (v or "").strip()]
        if missing:
            r.add("hold", "selections_incomplete", f"{rm.room} is missing {' and '.join(missing)}")

    addr = (data.address or "").strip()
    if not addr or addr.upper() in {"TBD", "N/A", "NA"}:
        r.add("warn", "no_address", "No street address yet; Autobot can't route this house until it has one")
    if not data.field_contact_name.strip():
        r.add("warn", "no_field_contact", "No field contact; measure problems will have nobody to go to")

    job = job_by_code(db, code)
    account = db.query(Account).filter(Account.name == data.account_name.strip()).first()
    community = None
    if account is not None and data.community:
        community = (
            db.query(Community)
            .filter(Community.account_id == account.id, Community.name == data.community.strip())
            .first()
        )

    # Lot collision: same subdivision + lot already belongs to another job code.
    if community is not None and lot:
        other = (
            db.query(Job)
            .filter(Job.community_id == community.id, Job.lot_number == lot, Job.job_code != code)
            .first()
        )
        if other is not None:
            r.add("reject", "lot_collision", f"{data.community} lot {lot} is already job {other.job_code}")

    if job is not None:
        same_place = (job.lot_number or None) == lot and (
            community is None or job.community_id == community.id
        )
        if acct_type is AccountType.builder and not same_place:
            r.add("reject", "code_reused", f"{code} already exists for a different lot ({job.lot_number})")
        if job.status is JobStatus.void:
            r.add("reject", "void", f"{code} is 8.0-Void; the office has to reopen it")
        elif ladder.at_least(job.status, JobStatus.ord):
            r.add("reject", "already_ordered", f"{code} is already {job.status.value}; changes need a change order in Optimus")
        elif ladder.at_least(job.status, JobStatus.ordprcss) and _quote_lines(db, job) != _sold_lines(kept):
            r.add("hold", "quote_changed_after_order",
                  f"{code} changed after the order went to the supplier ({job.status.value}); Optimus has to send a change order")
        else:
            r.add("warn", "resent", f"{code} was already sold; updated it with this version of the quote")

    if r.rejected:
        ev = _save(db, source="sterling", kind="sold", r=r, job=job, job_code=code, actor=actor, payload=payload)
        return _finish(db, r, ev, job)

    if account is None:
        account = Account(name=data.account_name.strip(), type=acct_type)
        db.add(account)
        db.flush()
    if data.community and community is None:
        community = Community(account_id=account.id, name=data.community.strip())
        db.add(community)
        db.flush()

    created = job is None
    if created:
        job = Job(
            job_code=code,
            account_id=account.id,
            job_type=job_type,
            status=JobStatus.track,
            address=addr or "TBD",
            sales_contact_name=data.sales_contact_name or "",
            field_contact_name=data.field_contact_name or "",
        )
        db.add(job)
    job.community_id = community.id if community else None
    job.lot_number = lot
    job.address = addr or job.address or "TBD"
    job.plan = data.plan or job.plan
    job.sales_contact_name = data.sales_contact_name or job.sales_contact_name
    job.field_contact_name = data.field_contact_name or job.field_contact_name
    job.field_contact_phone = data.field_contact_phone or job.field_contact_phone
    job.builder_po = data.builder_po or job.builder_po
    if data.po_amount is not None:
        job.po_amount = money(data.po_amount)
    job.sale_date = data.sold_date or job.sale_date or _today()
    db.flush()

    # One accepted quote = the sold version. Older accepted ones go back to draft.
    for q in db.query(Quote).filter(Quote.job_id == job.id, Quote.status == QuoteStatus.accepted):
        q.status = QuoteStatus.draft
    quote = Quote(job_id=job.id, name="Sold (Sterling)", status=QuoteStatus.accepted, multiplier=DEALER_MULTIPLIER)
    quote.lines = [
        QuoteLineItem(room=ln.room, qty=ln.qty, sku=norm_sku(ln.sku), list_price=money(ln.list_price)) for ln in kept
    ]
    db.add(quote)
    job.room_selections = [
        RoomSelection(
            room=rm.room, zone=rm.zone, cabinet_brand=rm.cabinet_brand, series=rm.series,
            door_style=rm.door_style, finish=rm.finish,
        )
        for rm in data.rooms
    ]

    # Sold with complete selections = ready to order (1.2). A selections hold parks it at 1.1.
    target = JobStatus.preord if r.hold_code == "selections_incomplete" else JobStatus.ndord
    moved = None
    if ladder.rank(job.status) < ladder.rank(target):
        moved = _move(r, job, target)
    ev = _save(db, source="sterling", kind="sold", r=r, job=job, job_code=code, actor=actor, payload=payload, moved=moved)
    if r.level in ("ok", "warn"):
        _resolve(db, job, {"selections_incomplete", "quote_total_mismatch"}, ev)
    landed = _apply_parked(db, job, ev)
    if landed:
        ev.note = "Applied feed rows that came before the sale: " + ", ".join(landed)
    return _finish(db, r, ev, job, {"created": created, "dealer_total": str(money(figured))})


# --------------------------------------------------------------------------- Optimus


def _ordering_gate(db: Session, r: Result, job: Job) -> None:
    for h in open_holds(db, job):
        if h.hold_code in {"measure_discrepancy", "selections_incomplete", "quote_total_mismatch", "po_mismatch",
                           "gi_conflict", "builder_po_cancelled"}:
            r.add("reject", "on_hold", f"Held by {h.source} ({h.hold_code}): {'; '.join(h.issues or [])}")


def optimus_order_sent(db: Session, data: OrderSentIn, actor: User | None) -> dict:
    r = Result()
    job = job_by_code(db, data.job_code)
    payload = _payload(data)
    if job is None:
        r.add("reject", "no_job", f"No job {norm_code(data.job_code)} in CabinetTron; Sterling has to sell it first")
        ev = _save(db, source="optimus", kind="order_sent", r=r, job=None, job_code=data.job_code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)

    if not ladder.is_between(job.status, JobStatus.ndord, JobStatus.ordprcss):
        r.add("reject", "wrong_stage", f"{job.job_code} is {job.status.value}; orders go out from 1.2-NdOrd")
    _ordering_gate(db, r, job)

    lines = []
    for ln in data.lines:
        if is_excluded(ln.sku):
            r.add("reject", "excluded_sku", f"{ln.sku.strip().upper()} is an appliance placeholder and can't be ordered")
        elif ln.qty <= 0:
            r.add("reject", "bad_qty", f"{ln.sku} has quantity {ln.qty}")
        else:
            lines.append(ln)
    if not lines:
        r.add("reject", "no_lines", "The order has no lines")
    summed = money(sum((money(ln.price) * ln.qty for ln in lines), Decimal(0)))
    if lines and summed != money(data.order_total):
        r.add("hold", "order_total_mismatch", f"Order lines add to ${summed:,} but the order total says ${money(data.order_total):,}")

    if data.po_number and job.builder_po and norm_po(data.po_number) != norm_po(job.builder_po):
        r.add("reject", "po_mismatch", f"Order is against PO {data.po_number} but the job's builder PO is {job.builder_po}")

    # Sold quote vs order: a cabinet on the drawing that isn't ordered (DRHACR-2016's 2x W3636).
    quote = db.query(Quote).filter(Quote.job_id == job.id, Quote.status == QuoteStatus.accepted).first()
    ordered: dict[str, int] = {}
    for ln in lines:
        ordered[norm_sku(ln.sku)] = ordered.get(norm_sku(ln.sku), 0) + ln.qty
    if quote is not None:
        sold: dict[str, int] = {}
        for ql in quote.lines:
            sold[norm_sku(ql.sku)] = sold.get(norm_sku(ql.sku), 0) + ql.qty
        for sku, qty in sold.items():
            if ordered.get(sku, 0) < qty:
                r.add("hold", "order_vs_quote", f"Sold {qty} x {sku} but ordered {ordered.get(sku, 0)}")
        for sku, qty in ordered.items():
            if sku not in sold:
                r.add("warn", "not_on_quote", f"{qty} x {sku} is on the order but not on the sold quote")

    # Duplicate order: identical lines sent for another job in the last 14 days.
    since = datetime.now(UTC) - timedelta(days=14)
    recent = (
        db.query(JobEvent)
        .filter(JobEvent.kind == "order_sent", JobEvent.level != "reject", JobEvent.job_id != job.id,
                JobEvent.created_at >= since)
        .all()
    )
    for other in recent:
        if ordered and _order_lines(other) == ordered:
            r.add("warn", "duplicate_order", f"Identical lines to the order for {other.job_code}; make sure this isn't a double order")
            break

    moved = None
    if not r.rejected and r.level != "hold":
        moved = _move(r, job, JobStatus.ordprcss)
    ev = _save(db, source="optimus", kind="order_sent", r=r, job=job, job_code=job.job_code, actor=actor,
               payload=payload, moved=moved)
    if not r.rejected:
        cl = _checklist(db, job)
        cl.vendor = data.vendor or cl.vendor
        cl.po_number = data.po_number or cl.po_number
        if r.level in ("ok", "warn"):
            _resolve(db, job, {"order_total_mismatch", "order_vs_quote", "quote_changed_after_order"}, ev)
    return _finish(db, r, ev, job)


def optimus_so_back(db: Session, data: SoBackIn, actor: User | None) -> dict:
    r = Result()
    job = job_by_code(db, data.job_code)
    payload = _payload(data)
    if job is None:
        r.add("reject", "no_job", f"No job {norm_code(data.job_code)} in CabinetTron")
        ev = _save(db, source="optimus", kind="so_back", r=r, job=None, job_code=data.job_code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)
    if not ladder.is_between(job.status, JobStatus.ordprcss, JobStatus.ordpo):
        r.add("reject", "wrong_stage", f"{job.job_code} is {job.status.value}; an SO only comes back after the order is sent")

    so_no = norm_so(data.so_number)
    dup = next(
        (c for c in db.query(OrderingChecklist).filter(OrderingChecklist.so_number.isnot(None),
                                                       OrderingChecklist.job_id != job.id)
         if norm_so(c.so_number) == so_no),
        None,
    )
    if dup is not None:
        r.add("reject", "duplicate_so", f"SO {data.so_number} is already on job {dup.job.job_code}")

    sent = _last_event(db, job, "order_sent", clean_only=True)
    if sent is None and not r.rejected:
        r.add("reject", "no_order", "No clean order on file for this job; send the order through Optimus first")
    else:
        order_total = money(Decimal(str(sent.payload["order_total"]))) if sent else None
        # Compare the cabinet subtotal: the grand total also carries $10/box build charge and freight.
        if order_total is not None and money(data.so_subtotal) != order_total:
            diff = money(data.so_subtotal) - order_total
            r.add("hold", "so_total_mismatch",
                  f"SO subtotal ${money(data.so_subtotal):,} vs order ${order_total:,} (off by ${diff:,})")
        ordered = _order_lines(sent)
        got: dict[str, int] = {}
        for ln in data.lines:
            got[norm_sku(ln.sku)] = got.get(norm_sku(ln.sku), 0) + ln.qty
        for sku, qty in got.items():
            if sku in ordered:
                continue
            base = next((sku[len(p):] for p in SUBSTITUTION_PREFIXES if sku.startswith(p) and sku[len(p):] in ordered), None)
            if base:
                r.add("hold", "sku_substitution", f"Supplier sent {sku} in place of {base}; confirm or have it corrected")
            elif data.lines:
                r.add("hold", "so_extra_sku", f"{qty} x {sku} is on the SO but wasn't ordered")
        for sku, qty in ordered.items():
            if data.lines and got.get(sku, 0) < qty and not any(s == p + sku for s in got for p in SUBSTITUTION_PREFIXES):
                r.add("hold", "so_missing_sku", f"Ordered {qty} x {sku}, SO has {got.get(sku, 0)}")
    for sku in data.out_of_stock:
        r.add("warn", "out_of_stock", f"{norm_sku(sku)} is out of stock; delivery date may slip")

    moved = None
    if not r.rejected and r.level != "hold":
        moved = _move(r, job, JobStatus.ordsub)
    ev = _save(db, source="optimus", kind="so_back", r=r, job=job, job_code=job.job_code, actor=actor, payload=payload, moved=moved)
    if not r.rejected:
        cl = _checklist(db, job)
        cl.so_number = so_no
        cl.so_amount = _cents(data.so_total) if data.so_total is not None else cl.so_amount
        if r.level in ("ok", "warn"):
            cl.so_total = money(data.so_total if data.so_total is not None else data.so_subtotal)
            _resolve(db, job, {"so_total_mismatch", "sku_substitution", "so_extra_sku", "so_missing_sku"}, ev)
    return _finish(db, r, ev, job)


def optimus_po_back(db: Session, data: PoBackIn, actor: User | None) -> dict:
    r = Result()
    job = job_by_code(db, data.job_code)
    payload = _payload(data)
    po = norm_po(data.carter_po_number)
    if po in CANCELLED_CARTER_POS:
        r.add("reject", "cancelled_po", f"Carter PO {data.carter_po_number} was cancelled; cut a new one")
    if job is None:
        r.add("reject", "no_job", f"No job {norm_code(data.job_code)} in CabinetTron")
        ev = _save(db, source="optimus", kind="po_back", r=r, job=None, job_code=data.job_code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)
    if job.status is JobStatus.void:
        r.add("reject", "void", f"{job.job_code} is 8.0-Void; never order or bill a void job")
    if data.carter_po_date > _today():
        r.add("reject", "future_date", f"Carter PO date {data.carter_po_date} is in the future")
    dup = (
        db.query(OrderingChecklist)
        .filter(OrderingChecklist.carter_po_number == po, OrderingChecklist.job_id != job.id)
        .first()
    )
    if dup is not None:
        r.add("reject", "duplicate_po", f"Carter PO {data.carter_po_number} is already on job {dup.job.job_code}")

    cl = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
    so_last = _last_event(db, job, "so_back")
    so_clean = so_last is not None and so_last.level in ("ok", "warn")
    for h in open_holds(db, job):
        if h.hold_code in PO_BLOCKERS:
            r.add("hold", h.hold_code, f"Open {h.source} hold, Carter PO waits: {'; '.join(h.issues or [])}")
    if cl is None or not cl.so_number or so_last is None:
        r.add("hold", "po_before_so", "Carter PO came in before a clean SO; match it once the SO is checked")
    elif not so_clean:
        r.add("hold", "po_on_held_so", "The latest SO from the supplier is on hold; the Carter PO waits for a clean one")
    else:
        if norm_so(data.so_number) != norm_so(cl.so_number):
            r.add("hold", "po_so_number", f"PO says SO {data.so_number}, the job has SO {cl.so_number}")
        # The SO total and the Carter PO total must match to the cent. Never bypassed.
        if cl.so_total is not None and money(data.carter_po_total) != money(cl.so_total):
            r.add("hold", "po_total_mismatch",
                  f"Carter PO ${money(data.carter_po_total):,} vs SO ${money(cl.so_total):,}; must match to the cent")

    moved = None
    if not r.rejected and r.level != "hold":
        moved = _move(r, job, JobStatus.ord)
    ev = _save(db, source="optimus", kind="po_back", r=r, job=job, job_code=job.job_code, actor=actor, payload=payload, moved=moved)
    if not r.rejected and r.level in ("ok", "warn"):
        # The Carter PO total stays on the timeline row: checklist.po_total is the
        # builder's PO total and must not be overwritten.
        cl.carter_po_number = po
        cl.carter_po_date = data.carter_po_date
        job.cabinet_po = po
        _resolve(db, job, {"po_before_so", "po_so_number", "po_total_mismatch"}, ev)
    return _finish(db, r, ev, job)


# --------------------------------------------------------------------------- feeds


def _job_from_feed(db: Session, job_code: str | None, builder_po: str | None, community: str | None,
                   lot: str | None) -> Job | None:
    job = job_by_code(db, job_code)
    if job is not None:
        return job
    if builder_po:
        want = norm_po(builder_po)
        hits = [j for j in db.query(Job).filter(Job.builder_po.isnot(None)).all() if norm_po(j.builder_po) == want]
        if len(hits) == 1:
            return hits[0]
    if community and lot:
        return (
            db.query(Job).join(Community, Job.community_id == Community.id)
            .filter(Community.name == community.strip(), Job.lot_number == lot.strip())
            .first()
        )
    return None


def feed_schedule(db: Session, data: ScheduleIn, actor: User | None) -> dict:
    r = Result()
    payload = _payload(data)
    job = _job_from_feed(db, data.job_code, data.builder_po, data.community, data.lot_number)
    if job is None:
        r.add("warn", "no_job", "Schedule row for a lot with no job yet; kept on the timeline until Sterling sells it")
        ev = _save(db, source="feed", kind="schedule", r=r, job=None, job_code=data.job_code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)
    if job.status is JobStatus.void:
        r.add("warn", "void", f"{job.job_code} is 8.0-Void; schedule ignored")
        ev = _save(db, source="feed", kind="schedule", r=r, job=job, job_code=job.job_code, actor=actor, payload=payload)
        return _finish(db, r, ev, job)

    if data.po_cancelled:
        r.add("hold", "builder_po_cancelled", f"Builder cancelled PO {data.builder_po or job.builder_po}; stop ordering")
    if data.builder_po and job.builder_po and norm_po(data.builder_po) != norm_po(job.builder_po):
        same_money = data.po_amount is not None and job.po_amount is not None and money(data.po_amount) == money(job.po_amount)
        if same_money:
            r.add("warn", "po_typo", f"Schedule PO {data.builder_po} vs job PO {job.builder_po}, same ${money(job.po_amount):,}; likely a typo")
        else:
            r.add("hold", "po_mismatch", f"Schedule PO {data.builder_po} doesn't match job PO {job.builder_po}")
    if data.measure_date and data.install_date and data.install_date < data.measure_date:
        r.add("reject", "bad_dates", f"Install {data.install_date} is before measure {data.measure_date}")

    if not r.rejected:
        if data.measure_date:
            job.measure_date = data.measure_date
        if data.install_date:
            # The office's install date wins; the feed never overwrites it.
            if job.install_date and job.install_date != data.install_date:
                r.add("warn", "install_conflict",
                      f"Feed says install {data.install_date}, office has {job.install_date}; kept the office date")
            elif not job.install_date:
                job.install_date = data.install_date
    ev = _save(db, source="feed", kind="schedule", r=r, job=job, job_code=job.job_code, actor=actor, payload=payload)
    if r.level in ("ok", "warn"):
        _resolve(db, job, {"po_mismatch"}, ev)
    return _finish(db, r, ev, job)


def ashley_to_code(ashley: str | None) -> str | None:
    """'CAB OMD60 135' -> 'DRID60-0135'."""
    if not ashley:
        return None
    m = re.match(r"^(?:CAB\s+)?([A-Z]+\s?\d*)\s+(\d{1,4})$", ashley.strip().upper())
    if not m:
        return None
    key = m.group(1).replace(" ", "")
    prefix = ASHLEY_PREFIX.get(key)
    return f"{prefix}-{int(m.group(2)):04d}" if prefix else None


def feed_job_setup(db: Session, data: JobSetupIn, actor: User | None) -> dict:
    r = Result()
    payload = _payload(data)
    seen = (
        db.query(JobEvent)
        .filter(JobEvent.kind == "job_setup", JobEvent.level != "reject")
        .all()
    )
    if any((e.payload or {}).get("request_number") == data.request_number for e in seen):
        r.add("warn", "repeat_request", f"Setup request #{data.request_number} was already handled; nothing changed")
        ev = _save(db, source="feed", kind="job_setup", r=r, job=None, job_code=None, actor=actor, payload=payload)
        return _finish(db, r, ev, None)

    want = norm_po(data.builder_po)
    hits = [j for j in db.query(Job).filter(Job.builder_po.isnot(None)).all() if norm_po(j.builder_po) == want]
    if len(hits) > 1 and data.lot_number:
        hits = [j for j in hits if j.lot_number == data.lot_number.strip()] or hits
    if len(hits) > 1 and data.po_amount is not None:
        hits = [j for j in hits if j.po_amount is not None and money(j.po_amount) == money(data.po_amount)] or hits
    job = hits[0] if len(hits) == 1 else None
    if job is None:
        derived = ashley_to_code(data.ashley_code)
        job = job_by_code(db, derived)
        if job is not None:
            same_money = data.po_amount is not None and job.po_amount is not None and money(data.po_amount) == money(job.po_amount)
            if job.builder_po and norm_po(job.builder_po) != want:
                level = "hold"
                text = (f"Setup email PO {data.builder_po} vs CabinetTron PO {job.builder_po} for {job.job_code}"
                        + (f" (same ${money(job.po_amount):,}, likely a typo on one side)" if same_money else ""))
                r.add(level, "po_mismatch", text)
    if job is None:
        r.add("warn", "no_job", f"No job yet for PO {data.builder_po}; kept until Sterling sells it")
        ev = _save(db, source="feed", kind="job_setup", r=r, job=None, job_code=None, actor=actor, payload=payload)
        return _finish(db, r, ev, None)

    for attr, val in (("g_code", data.g_code), ("i_code", data.i_code)):
        if not val:
            continue
        have = getattr(job, attr)
        if have and have != val.strip():
            r.add("hold", "gi_conflict", f"{attr[0].upper()} code {val} differs from {have} already on {job.job_code}")
        elif r.hold_code != "po_mismatch":
            setattr(job, attr, val.strip())
    ev = _save(db, source="feed", kind="job_setup", r=r, job=job, job_code=job.job_code, actor=actor, payload=payload)
    return _finish(db, r, ev, job)


# --------------------------------------------------------------------------- Autobot


def autobot_field_check(db: Session, data: FieldCheckIn, actor: User | None) -> dict:
    r = Result()
    payload = _payload(data)
    job = job_by_code(db, data.job_code)
    if job is None:
        r.add("reject", "no_job", f"No job {norm_code(data.job_code)} in CabinetTron")
        ev = _save(db, source="autobot", kind=data.visit_type, r=r, job=None, job_code=data.job_code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)
    if data.visit_type not in ("field_measure", "post_walk", "punch_out", "blue_tape"):
        r.add("reject", "bad_visit", f"{data.visit_type} isn't a field check")
    if data.done_on > _today():
        r.add("reject", "future_date", f"Visit date {data.done_on} is in the future")
    if job.status is JobStatus.void:
        r.add("reject", "void", f"{job.job_code} is 8.0-Void")

    target = None
    clears: set[str] = set()
    if data.visit_type == "field_measure":
        if not data.passed or data.discrepancies:
            who = job.field_contact_name or ""
            route = f"send to {who}" if who.strip() else "no field contact on the job, so the office has to chase it"
            r.add("hold", "measure_discrepancy",
                  f"Field measure doesn't match the drawing: {'; '.join(data.discrepancies) or 'see notes'} ({route}); ordering is held")
            if not who.strip():
                r.add("warn", "no_field_contact", "No field contact on the job")
        else:
            clears = {"measure_discrepancy"}
            if data.done_on:
                job.measure_date = job.measure_date or data.done_on
    elif data.visit_type == "post_walk":
        if not ladder.at_least(job.status, JobStatus.inst):
            r.add("reject", "not_installed", f"{job.job_code} is {job.status.value}; a post-install walk needs the install done")
        elif data.parts_needed:
            r.add("hold", "parts_needed", f"Parts needed: {', '.join(data.parts_needed)}")
            target = JobStatus.parts
        elif data.passed:
            target, clears = JobStatus.punch, {"parts_needed", "walk_failed"}
        else:
            r.add("hold", "walk_failed", data.notes or "Post-install walk found problems")
            target = JobStatus.ndqw
    else:  # punch_out / blue_tape
        if not ladder.at_least(job.status, JobStatus.ndqw):
            r.add("reject", "not_installed", f"{job.job_code} is {job.status.value}; punch comes after the install walk")
        elif data.passed:
            target = JobStatus.blue if data.visit_type == "punch_out" else JobStatus.epo
            clears = {"punch_open"}
        else:
            r.add("hold", "punch_open", data.notes or f"{data.visit_type.replace('_', ' ')} items still open")
            target = JobStatus.punch

    moved = None
    if target is not None and not r.rejected and ladder.rank(target) > ladder.rank(job.status):
        moved = _move(r, job, target)
    ev = _save(db, source="autobot", kind=data.visit_type, r=r, job=job, job_code=job.job_code, actor=actor,
               payload=payload, moved=moved)
    if clears and not r.rejected:
        _resolve(db, job, clears, ev)
    return _finish(db, r, ev, job)


# --------------------------------------------------------------------------- Tailgate


def _owns(user: User | None, job: Job) -> bool:
    if user is None or not job.installer:
        return False
    who = job.installer.strip().lower()
    return who in {(user.full_name or "").strip().lower(), (user.email or "").strip().lower()}


def tailgate_install(db: Session, data: InstallIn, actor: User | None) -> dict:
    r = Result()
    payload = _payload(data)
    job = job_by_code(db, data.job_code)
    if job is None:
        r.add("reject", "no_job", f"No job {norm_code(data.job_code)} in CabinetTron")
        ev = _save(db, source="tailgate", kind="install", r=r, job=None, job_code=data.job_code, actor=actor, payload=payload)
        return _finish(db, r, ev, None)
    if actor is not None and actor.role is Role.installer and not _owns(actor, job):
        raise HTTPException(status_code=403, detail=f"{job.job_code} isn't assigned to you")
    if not ladder.at_least(job.status, JobStatus.ord):
        r.add("reject", "not_ordered", f"{job.job_code} is {job.status.value}; cabinets aren't ordered yet")
    if data.installed_on > _today():
        r.add("reject", "future_date", f"Install date {data.installed_on} is in the future; a scheduled install isn't an installed one")
    if data.install_pay is not None and data.install_pay <= 0:
        r.add("reject", "bad_pay", f"Install pay ${data.install_pay} isn't a real amount")
    if not data.complete and not (data.notes or "").strip():
        r.add("reject", "no_notes", "An incomplete install needs a note saying what's left")
    if data.complete and data.photos <= 0:
        r.add("warn", "no_photos", "No install photos; the post-install walk will have nothing to compare to")

    cl = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
    if data.complete and not r.rejected:
        if data.install_pay is None and (cl is None or cl.install_pay is None):
            r.add("warn", "no_install_pay", "Install pay is blank; left blank for the office (never guessed)")

    moved = None
    if data.complete and not r.rejected:
        moved = _move(r, job, JobStatus.inst)
    if not data.complete and not r.rejected:
        r.add("hold", "install_incomplete", data.notes.strip())
    ev = _save(db, source="tailgate", kind="install", r=r, job=job, job_code=job.job_code, actor=actor, payload=payload, moved=moved)
    if not r.rejected and data.complete:
        job.install_date = data.installed_on
        job.warranty_start_date = job.warranty_start_date or data.installed_on
        if data.install_pay is not None:
            _checklist(db, job).install_pay = money(data.install_pay)
        _resolve(db, job, {"install_incomplete"}, ev)
        # The post-install walk is on a hard 48 hour clock from completion. One per job.
        has_walk = db.query(Visit).filter(Visit.job_id == job.id, Visit.visit_type == "post_walk",
                                          Visit.status != "canceled").first()
        if has_walk is None:
            db.add(Visit(
                visit_type="post_walk", job_id=job.id, community_id=job.community_id,
                open_date=data.installed_on, close_date=data.installed_on + timedelta(days=2),
                status="pending", priority=5, created_by="tailgate",
            ))
    return _finish(db, r, ev, job)


def unmatched(db: Session, days: int = 30) -> list[dict]:
    """Hand-offs that never reached a job: refused codes, feed rows waiting on a sale."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        db.query(JobEvent)
        .filter(JobEvent.job_id.is_(None), JobEvent.resolved_at.is_(None), JobEvent.created_at >= since)
        .order_by(JobEvent.id.desc())
        .all()
    )
    return [_row(e) for e in rows]


def _row(e: JobEvent) -> dict:
    return {
        "id": e.id, "at": e.created_at.isoformat() if e.created_at else None, "job_code": e.job_code,
        "source": e.source, "kind": e.kind, "level": e.level, "issues": e.issues or [], "hold_code": e.hold_code,
        "status_from": e.status_from, "status_to": e.status_to, "actor": e.actor, "resolved": e.resolved_at is not None,
    }


def timeline(db: Session, job: Job) -> list[dict]:
    rows = db.query(JobEvent).filter(JobEvent.job_id == job.id).order_by(JobEvent.id).all()
    return [_row(e) for e in rows]


# --------------------------------------------------------------------------- in-app callers
# The Optimus board, the Order Pack agent and the builder feeds run inside
# CabinetTron, so they call these directly instead of the HTTP hand-offs. Same
# ladder, same holds, same timeline; they commit with their own transaction.

ORDERING_GATE = {"measure_discrepancy", "selections_incomplete", "quote_total_mismatch", "po_mismatch",
                 "gi_conflict", "builder_po_cancelled"}
OPTIMUS_WINDOW = (JobStatus.ndord, JobStatus.ordprcss, JobStatus.ordsub, JobStatus.ordpo, JobStatus.ord)


def optimus_move(db: Session, job: Job, target: JobStatus, actor: str = "Optimus") -> bool:
    """A ticked or unticked Optimus step wants the job at `target`.

    Forward moves wait while a hold is open (ordering holds from 1.3 on, money
    holds from 1.5 on). Moving back inside the Optimus window is allowed, because
    unticking a step there is the office correcting itself, and it is logged.
    Returns True when the status changed.
    """
    if job.status == target or job.status not in OPTIMUS_WINDOW or target not in OPTIMUS_WINDOW:
        return False
    r = Result()
    back = ladder.rank(target) < ladder.rank(job.status)
    if not back:
        blockers = set()
        if ladder.rank(target) >= ladder.rank(JobStatus.ordprcss):
            blockers |= ORDERING_GATE
        if ladder.rank(target) >= ladder.rank(JobStatus.ordpo):
            blockers |= PO_BLOCKERS
        for h in open_holds(db, job):
            if h.hold_code in blockers:
                r.add("hold", h.hold_code, f"Optimus step waits on an open {h.source} hold: {'; '.join(h.issues or [])}")
        if r.level == "hold":
            # Not a new hold of its own: record it, but the original hold is what clears it.
            _save(db, source="optimus", kind="step_blocked", r=Result([("warn", "step_blocked", t) for _, _, t in r.findings]),
                       job=job, job_code=job.job_code, actor=actor, payload={"wanted": target.value})
            return False
    before = job.status.value
    try:
        ladder.check_move(job.status, target, reopen=back)
    except ladder.LadderError as exc:
        _save(db, source="optimus", kind="step_blocked", r=Result([("warn", "ladder", str(exc))]), job=job,
              job_code=job.job_code, actor=actor, payload={"wanted": target.value})
        return False
    job.status = target
    if back:
        r.add("warn", "moved_back", f"Step unticked in Optimus: {before} back to {target.value}")
    _save(db, source="optimus", kind="step", r=r, job=job, job_code=job.job_code, actor=actor,
          moved=(before, target.value), payload={"wanted": target.value})
    return True


def carter_po_gate(db: Session, job: Job, po_number: str | None, po_total, so_total) -> list[str]:
    """The Order Pack agent's stage 4 result, checked the same way as a PO-back."""
    problems = []
    po = norm_po(po_number)
    if job.status is JobStatus.void:
        problems.append(f"{job.job_code} is 8.0-Void; never order or bill a void job")
    if not po:
        problems.append("No Carter PO number in the stage 4 result")
    elif po in CANCELLED_CARTER_POS:
        problems.append(f"Carter PO {po_number} was cancelled; cut a new one")
    else:
        dup = (
            db.query(OrderingChecklist)
            .filter(OrderingChecklist.carter_po_number.isnot(None), OrderingChecklist.job_id != job.id)
            .all()
        )
        other = next((c for c in dup if norm_po(c.carter_po_number) == po), None)
        if other is not None:
            problems.append(f"Carter PO {po_number} is already on job {other.job.job_code}")
    if po_total is None or so_total is None:
        problems.append("Stage 4 result is missing the SO total or the Carter PO total, so they can't be matched")
    elif money(po_total) != money(so_total):
        problems.append(f"Carter PO ${money(po_total):,} vs SO ${money(so_total):,}; must match to the cent")
    for h in open_holds(db, job):
        if h.hold_code in PO_BLOCKERS:
            problems.append(f"Open {h.source} hold: {'; '.join(h.issues or [])}")
    return problems


def log_agent(db: Session, job: Job, kind: str, problems: list[str], payload: dict | None = None,
              moved: tuple[str, str] | None = None) -> JobEvent:
    r = Result([("hold", "agent_" + kind, p) for p in problems])
    ev = _save(db, source="optimus", kind=kind, r=r, job=job, job_code=job.job_code, actor="Order Pack agent",
               payload=payload, moved=moved)
    if not problems:
        _resolve(db, job, {"agent_" + kind}, ev)
    return ev


def feed_po_open(db: Session, job: Job, source_label: str) -> bool:
    """The builder's PO is open: the job is sold and ready to order (1.2-NdOrd).

    Only Optimus moves it further. The feeds used to jump it to 2.0-Ord, which
    skipped every ordering check.
    """
    if job.status not in (JobStatus.track, JobStatus.preord):
        return False
    before = job.status.value
    job.status = JobStatus.ndord
    _save(db, source="feed", kind="builder_po_open", r=Result(), job=job, job_code=job.job_code, actor=source_label,
          moved=(before, job.status.value), payload={"builder_po": job.builder_po})
    return True


def feed_po_changed(db: Session, job: Job, new_po: str | None, new_amount, source_label: str) -> None:
    """The builder feed carries a different PO than the job has. Same rule as the
    schedule hand-off: same dollars = likely typo (warn), else a hold."""
    if not new_po or not job.builder_po or norm_po(new_po) == norm_po(job.builder_po):
        return
    same_money = new_amount is not None and job.po_amount is not None and money(new_amount) == money(job.po_amount)
    r = Result()
    if same_money:
        r.add("warn", "po_typo", f"Feed PO {new_po} vs job PO {job.builder_po}, same ${money(job.po_amount):,}; likely a typo")
    else:
        r.add("warn", "po_changed", f"Builder PO changed from {job.builder_po} to {new_po}; check ordering used the right one")
    _save(db, source="feed", kind="po_changed", r=r, job=job, job_code=job.job_code, actor=source_label,
          payload={"old": job.builder_po, "new": new_po})
