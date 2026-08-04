from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access, write_access
from app.database import get_db
from app.jobcosts import MARGIN_EXCLUDED_LABOR_CODES, pl_components, refresh_from_file
from app.domo_txn import SNAPSHOT_SOURCE, half_range, quarter_range, refresh_domo_txns, ytd_range
from app.models import (
    Account, AccountType, Community, DomoTxn, Job, JobCost, JobDocument, JobStatus, PhaseUpdate,
    ServiceLine, ServiceRequest,
)
from app.phases import PHASE_LABELS

router = APIRouter(tags=["reports"])

ACTIVE = Job.status.notin_((JobStatus.closed, JobStatus.void))


def _d(value) -> float:
    return float(value) if value is not None else 0.0


def _parse_signed_money(s: str) -> float:
    """'-$1,234.56' -> -1234.56 (parses the fixed format the app writes)."""
    s = s.strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


class PhaseReportRow(BaseModel):
    account_name: str
    community_name: str | None
    job_id: int
    job_code: str | None
    lot_number: str | None
    address: str
    plan: str | None
    phase: str | None
    phase_label: str | None
    phase_date: datetime | None
    measure_date: date | None
    layout_doc_id: int | None


@router.get("/reports/phases", response_model=list[PhaseReportRow], dependencies=[Depends(read_access)])
def phase_report(db: Session = Depends(get_db)):
    """All active builder houses with current phase — sorted builder, community, lot."""
    jobs = (
        db.query(Job)
        .join(Account, Job.account_id == Account.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(Account.type == AccountType.builder, Job.status.notin_((JobStatus.closed, JobStatus.void)))
        .all()
    )

    latest: dict[int, PhaseUpdate] = {}
    if jobs:
        sub = (
            db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("max_id"))
            .filter(PhaseUpdate.job_id.in_([j.id for j in jobs]))
            .group_by(PhaseUpdate.job_id)
            .subquery()
        )
        for row in db.query(PhaseUpdate).join(sub, PhaseUpdate.id == sub.c.max_id).all():
            latest[row.job_id] = row

    layouts: dict[int, int] = {}
    if jobs:
        for doc in (
            db.query(JobDocument)
            .filter(JobDocument.job_id.in_([j.id for j in jobs]), JobDocument.doc_type == "layout")
            .order_by(JobDocument.id.desc())
            .all()
        ):
            layouts[doc.job_id] = doc.id

    def sort_key(job: Job):
        lot = (job.lot_number or "").strip()
        return (
            job.account.name.lower(),
            (job.community.name.lower() if job.community else "~"),  # no-community groups last
            (0, int(lot)) if lot.isdigit() else (1, lot),
        )

    rows = []
    for job in sorted(jobs, key=sort_key):
        current = latest.get(job.id)
        rows.append(
            PhaseReportRow(
                account_name=job.account.name,
                community_name=job.community.name if job.community else None,
                job_id=job.id,
                job_code=job.job_code,
                lot_number=job.lot_number,
                address=job.address,
                plan=job.plan,
                phase=current.phase if current else None,
                phase_label=PHASE_LABELS.get(current.phase) if current else None,
                phase_date=current.noted_at if current else None,
                measure_date=job.measure_date,
                layout_doc_id=layouts.get(job.id),
            )
        )
    return rows


# --------------------------------------------------------------------------
# Reports catalog — what the frontend dropdown offers
# --------------------------------------------------------------------------

class ReportInfo(BaseModel):
    key: str
    name: str
    description: str
    category: str


# Category display order on the Reports tab
REPORT_CATEGORIES = ["Accounting", "Operations", "Sales"]

REPORTS = [
    ReportInfo(key="job-pl", name="Job Cost P&L (Domo)", category="Accounting",
               description="Per-house all-in P&L from Domo actual costs by G/I code — product, C9009 install labor, and the net of every other labor code folded into margin. Click Update to re-pull."),
    ReportInfo(key="domo-pl", name="Domo P&L by Period", category="Accounting",
               description="Department P&L straight from Domo transactions, run by builder, single job, date window, quarter, half-year, YTD, or year-over-year. Click Update to re-pull transactions."),
    ReportInfo(key="other-labor", name="Labor on Non-C9009 Codes", category="Accounting",
               description="Every house carrying install labor billed to a code other than C9009, with the net dollar drag (or gain) on its margin — worst first."),
    ReportInfo(key="po-status", name="PO Status Summary", category="Accounting",
               description="Count and dollar value of POs grouped by status (open, paid, voided)."),
    ReportInfo(key="phases", name="Phase Report", category="Operations",
               description="Active houses by builder, community, and lot with current construction phase."),
    ReportInfo(key="install-week", name="Install Schedule by Week", category="Operations",
               description="Scheduled installs grouped by install week with PO value."),
    ReportInfo(key="unordered", name="Needs Ordering", category="Operations",
               description="Active jobs with an install date but no cabinet PO yet — the risk list."),
    ReportInfo(key="open-service", name="Open Service Requests", category="Operations",
               description="Every service request with work still open — job, date created, material status, and scheduled completion date."),
    ReportInfo(key="revenue-builder", name="Revenue by Builder & Community", category="Sales",
               description="Total PO revenue rolled up by builder, then community."),
    ReportInfo(key="revenue-salesperson", name="Revenue by Salesperson", category="Sales",
               description="PO revenue and job count per salesperson."),
    ReportInfo(key="open-po", name="Open PO Report", category="Sales",
               description="Every job with an open builder PO, its amount, and totals by builder and community."),
]


@router.get("/reports", response_model=list[ReportInfo], dependencies=[Depends(read_access)])
def list_reports():
    return REPORTS


# --- Open PO report -------------------------------------------------------

class OpenPORow(BaseModel):
    job_id: int
    job_code: str | None
    account_name: str
    community_name: str | None
    lot_number: str | None
    address: str
    builder_po: str | None
    po_amount: float
    po_status: str | None


class OpenPOReport(BaseModel):
    rows: list[OpenPORow]
    total_amount: float
    count: int


@router.get("/reports/open-po", response_model=OpenPOReport, dependencies=[Depends(read_access)])
def open_po_report(db: Session = Depends(get_db)):
    jobs = (
        db.query(Job)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(ACTIVE, Job.po_status.ilike("open"))
        .all()
    )
    jobs.sort(key=lambda j: (j.account.name.lower(), (j.community.name.lower() if j.community else "~"),
                             _lotkey(j.lot_number)))
    rows = [
        OpenPORow(
            job_id=j.id, job_code=j.job_code, account_name=j.account.name,
            community_name=j.community.name if j.community else None,
            lot_number=j.lot_number, address=j.address, builder_po=j.builder_po,
            po_amount=_d(j.po_amount), po_status=j.po_status,
        )
        for j in jobs
    ]
    return OpenPOReport(rows=rows, total_amount=round(sum(r.po_amount for r in rows), 2), count=len(rows))


# --- PO status summary ----------------------------------------------------

class StatusSummaryRow(BaseModel):
    po_status: str
    count: int
    total_amount: float


@router.get("/reports/po-status", response_model=list[StatusSummaryRow], dependencies=[Depends(read_access)])
def po_status_summary(db: Session = Depends(get_db)):
    rows = (
        db.query(Job.po_status, func.count(Job.id), func.sum(Job.po_amount))
        .filter(Job.po_status.isnot(None))
        .group_by(Job.po_status)
        .order_by(func.sum(Job.po_amount).desc())
        .all()
    )
    return [StatusSummaryRow(po_status=s or "—", count=c, total_amount=_d(amt)) for s, c, amt in rows]


# --- Revenue by builder & community --------------------------------------

class RevenueGroup(BaseModel):
    label: str
    sublabel: str | None
    count: int
    total_amount: float


@router.get("/reports/revenue-builder", response_model=list[RevenueGroup], dependencies=[Depends(read_access)])
def revenue_by_builder(db: Session = Depends(get_db)):
    rows = (
        db.query(Account.name, Community.name, func.count(Job.id), func.sum(Job.po_amount))
        .join(Job, Job.account_id == Account.id)
        .outerjoin(Community, Job.community_id == Community.id)
        .filter(Job.po_amount.isnot(None))
        .group_by(Account.name, Community.name)
        .order_by(Account.name, func.sum(Job.po_amount).desc())
        .all()
    )
    return [
        RevenueGroup(label=acct, sublabel=comm, count=c, total_amount=_d(amt))
        for acct, comm, c, amt in rows
    ]


@router.get("/reports/revenue-salesperson", response_model=list[RevenueGroup], dependencies=[Depends(read_access)])
def revenue_by_salesperson(db: Session = Depends(get_db)):
    rows = (
        db.query(Job.salesperson, func.count(Job.id), func.sum(Job.po_amount))
        .filter(Job.po_amount.isnot(None))
        .group_by(Job.salesperson)
        .order_by(func.sum(Job.po_amount).desc())
        .all()
    )
    return [
        RevenueGroup(label=name or "Unassigned", sublabel=None, count=c, total_amount=_d(amt))
        for name, c, amt in rows
    ]


# --- Install schedule by week --------------------------------------------

class InstallWeekRow(BaseModel):
    week_start: date
    count: int
    total_amount: float


@router.get("/reports/install-week", response_model=list[InstallWeekRow], dependencies=[Depends(read_access)])
def install_by_week(db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(ACTIVE, Job.install_date.isnot(None)).all()
    buckets: dict[date, list[Job]] = {}
    for j in jobs:
        monday = j.install_date - timedelta(days=j.install_date.weekday())
        buckets.setdefault(monday, []).append(j)
    return [
        InstallWeekRow(week_start=wk, count=len(js),
                       total_amount=round(sum(_d(j.po_amount) for j in js), 2))
        for wk, js in sorted(buckets.items())
    ]


# --- Needs ordering -------------------------------------------------------

class NeedsOrderRow(BaseModel):
    job_id: int
    job_code: str | None
    account_name: str
    community_name: str | None
    lot_number: str | None
    address: str
    install_date: date
    status: JobStatus


@router.get("/reports/unordered", response_model=list[NeedsOrderRow], dependencies=[Depends(read_access)])
def needs_ordering(db: Session = Depends(get_db)):
    jobs = (
        db.query(Job)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(ACTIVE, Job.install_date.isnot(None), Job.cabinet_po.is_(None))
        .order_by(Job.install_date)
        .all()
    )
    return [
        NeedsOrderRow(
            job_id=j.id, job_code=j.job_code, account_name=j.account.name,
            community_name=j.community.name if j.community else None,
            lot_number=j.lot_number, address=j.address,
            install_date=j.install_date, status=j.status,
        )
        for j in jobs
    ]


def _lotkey(lot):
    s = (lot or "").strip()
    return (0, int(s)) if s.isdigit() else (1, s)


# --- Open Service Requests ------------------------------------------------

class OpenServiceRow(BaseModel):
    sr_id: int
    job_id: int
    job_code: str | None
    account_name: str
    community_name: str | None
    lot_number: str | None
    address: str
    title: str | None
    status: str
    material_status: str | None
    created_at: datetime
    scheduled_date: date | None
    open_lines: int
    total_lines: int


@router.get("/reports/open-service", response_model=list[OpenServiceRow], dependencies=[Depends(read_access)])
def open_service_requests(db: Session = Depends(get_db)):
    """Every service request with work still open (some/all lines not done),
    with job info, date created, material status, and scheduled completion date."""
    reqs = (
        db.query(ServiceRequest)
        .options(
            joinedload(ServiceRequest.job).joinedload(Job.account),
            joinedload(ServiceRequest.job).joinedload(Job.community),
            joinedload(ServiceRequest.lines),
        )
        .all()
    )
    rows = []
    for sr in reqs:
        total = len(sr.lines)
        done = sum(1 for ln in sr.lines if ln.done)
        if total > 0 and done == total:
            continue  # fully completed — not open
        job = sr.job
        rows.append(OpenServiceRow(
            sr_id=sr.id, job_id=sr.job_id, job_code=job.job_code,
            account_name=job.account.name if job.account else "—",
            community_name=job.community.name if job.community else None,
            lot_number=job.lot_number, address=job.address,
            title=sr.title, status=sr.status, material_status=sr.material_status,
            created_at=sr.created_at, scheduled_date=sr.scheduled_date,
            open_lines=total - done, total_lines=total,
        ))
    rows.sort(key=lambda r: (r.scheduled_date or date.max, r.created_at))
    return rows




# --- Job Cost P&L (Domo actuals) -----------------------------------------


class JobPLRow(BaseModel):
    job_id: int
    job_code: str | None
    account_name: str
    community_name: str | None
    lot_number: str | None
    g_code: str | None
    i_code: str | None
    revenue: float
    revenue_source: str
    builder_po: str | None
    po_check_number: str | None
    po_paid_date: date | None
    product_cost: float
    labor_revenue: float
    labor_cost: float
    other_labor_net: float
    wash_labor_net: float
    margin: float
    margin_pct: float | None
    other_labor_codes: str | None
    wash_labor_codes: str | None


class JobPLReport(BaseModel):
    rows: list[JobPLRow]
    total_revenue: float
    total_cost: float
    total_other_labor_net: float
    total_wash_labor_net: float
    total_margin: float
    margin_pct: float | None
    count: int
    with_other_labor: int
    drh_po_count: int
    updated_at: datetime | None


def _pl_row(job: Job, cost: JobCost) -> JobPLRow:
    rev, cst, other_net, margin, source = pl_components(job, cost)
    return JobPLRow(
        job_id=job.id, job_code=job.job_code, account_name=job.account.name,
        community_name=job.community.name if job.community else None,
        lot_number=job.lot_number, g_code=job.g_code, i_code=job.i_code,
        revenue=round(rev, 2), revenue_source=source,
        builder_po=job.builder_po if source == "DRH PO" else None,
        po_check_number=job.po_check_number if source == "DRH PO" else None,
        po_paid_date=job.po_paid_date if source == "DRH PO" else None,
        product_cost=_d(cost.product_cost),
        labor_revenue=_d(cost.labor_revenue), labor_cost=_d(cost.labor_cost),
        other_labor_net=round(other_net, 2), wash_labor_net=round(_d(cost.wash_labor_net), 2),
        margin=round(margin, 2), margin_pct=round(margin / rev * 100, 1) if rev else None,
        other_labor_codes=cost.other_labor_codes, wash_labor_codes=cost.wash_labor_codes,
    )


@router.get("/reports/job-pl", response_model=JobPLReport, dependencies=[Depends(read_access)])
def job_pl_report(db: Session = Depends(get_db)):
    q = (
        db.query(Job, JobCost)
        .join(JobCost, JobCost.job_id == Job.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .all()
    )
    rows: list[JobPLRow] = []
    latest: datetime | None = None
    for job, cost in q:
        rows.append(_pl_row(job, cost))
        if cost.updated_at and (latest is None or cost.updated_at > latest):
            latest = cost.updated_at
    rows.sort(key=lambda r: (r.account_name.lower(), (r.community_name or "~").lower(), _lotkey(r.lot_number)))
    total_rev = round(sum(r.revenue for r in rows), 2)
    total_margin = round(sum(r.margin for r in rows), 2)
    return JobPLReport(
        rows=rows,
        total_revenue=total_rev,
        total_cost=round(sum(r.product_cost + r.labor_cost for r in rows), 2),
        total_other_labor_net=round(sum(r.other_labor_net for r in rows), 2),
        total_wash_labor_net=round(sum(r.wash_labor_net for r in rows), 2),
        total_margin=total_margin,
        margin_pct=round(total_margin / total_rev * 100, 1) if total_rev else None,
        count=len(rows),
        with_other_labor=sum(1 for r in rows if r.other_labor_codes),
        drh_po_count=sum(1 for r in rows if r.revenue_source == "DRH PO"),
        updated_at=latest,
    )


# --- Labor on non-C9009 codes --------------------------------------------

class OtherLaborRow(BaseModel):
    job_id: int
    job_code: str | None
    account_name: str
    community_name: str | None
    lot_number: str | None
    i_code: str | None
    c9009_margin: float       # product + C9009 labor only
    other_labor_net: float    # net drag/gain of the real non-C9009 codes (in margin)
    all_in_margin: float      # c9009_margin + other_labor_net
    wash_labor_net: float     # C9091/C9002 overhead & rebill parked here (excluded)
    other_labor_codes: str | None
    wash_labor_codes: str | None


class WashCodeTotal(BaseModel):
    code: str
    total: float
    houses: int


class OtherLaborReport(BaseModel):
    rows: list[OtherLaborRow]
    count: int
    total_other_labor_net: float
    total_c9009_margin: float
    total_all_in_margin: float
    total_wash_labor_net: float
    excluded_codes: list[str]
    wash_by_code: list[WashCodeTotal]
    updated_at: datetime | None


@router.get("/reports/other-labor", response_model=OtherLaborReport, dependencies=[Depends(read_access)])
def other_labor_report(db: Session = Depends(get_db)):
    """Every job carrying real (non-wash) labor billed to codes other than C9009, worst drag first."""
    q = (
        db.query(Job, JobCost)
        .join(JobCost, JobCost.job_id == Job.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(JobCost.other_labor_codes.isnot(None))
        .all()
    )
    rows: list[OtherLaborRow] = []
    latest: datetime | None = None
    for job, cost in q:
        _, _, other_net, all_in, _ = pl_components(job, cost)  # DRH-PO override applied
        rows.append(OtherLaborRow(
            job_id=job.id, job_code=job.job_code, account_name=job.account.name,
            community_name=job.community.name if job.community else None,
            lot_number=job.lot_number, i_code=job.i_code,
            c9009_margin=round(all_in - other_net, 2),
            other_labor_net=round(other_net, 2),
            all_in_margin=round(all_in, 2),
            wash_labor_net=round(_d(cost.wash_labor_net), 2),
            other_labor_codes=cost.other_labor_codes,
            wash_labor_codes=cost.wash_labor_codes,
        ))
        if cost.updated_at and (latest is None or cost.updated_at > latest):
            latest = cost.updated_at
    rows.sort(key=lambda r: r.other_labor_net)  # most negative (biggest drag) first

    # per-code totals of the excluded overhead across every house (not just the rows above)
    by_code: dict[str, list] = {}
    for (wc,) in db.query(JobCost.wash_labor_codes).filter(JobCost.wash_labor_codes.isnot(None)).all():
        for part in wc.split("; "):
            code, _, amt = part.partition(": ")
            slot = by_code.setdefault(code, [0.0, 0])
            slot[0] += _parse_signed_money(amt)
            slot[1] += 1
    wash_by_code = [
        WashCodeTotal(code=c, total=round(v[0], 2), houses=v[1])
        for c, v in sorted(by_code.items(), key=lambda kv: kv[1][0])  # biggest drag first
    ]

    return OtherLaborReport(
        rows=rows,
        count=len(rows),
        total_other_labor_net=round(sum(r.other_labor_net for r in rows), 2),
        total_c9009_margin=round(sum(r.c9009_margin for r in rows), 2),
        total_all_in_margin=round(sum(r.all_in_margin for r in rows), 2),
        total_wash_labor_net=round(sum(r.wash_labor_net for r in rows), 2),
        excluded_codes=sorted(MARGIN_EXCLUDED_LABOR_CODES),
        wash_by_code=wash_by_code,
        updated_at=latest,
    )


@router.post("/reports/job-pl/refresh", dependencies=[Depends(write_access)])
def job_pl_refresh(db: Session = Depends(get_db)):
    """The report's Update button. Preference order:
    1. live token pull, 2. newest raw Domo dump (KB Domo Raw*.json — G+I combined),
    3. legacy pre-combined KB Job Costs*.json. Options 1–2 combine each house's
    active (I-code) and rebilled/complete (G-code) dollars; option 3 is whatever
    the old export already contained."""
    from app.config import get_settings
    from app.domo import import_raw_file, latest_raw_export, pull_and_import, token_configured

    if token_configured():
        result = pull_and_import(db)
        if "error" not in result:
            return result
        # token misconfigured/expired — fall back so the button still works
        if latest_raw_export(Path(get_settings().domo_export_dir)):
            return {**import_raw_file(db), "domo_error": result["error"]}
        return {**refresh_from_file(db), "domo_error": result["error"]}
    if latest_raw_export(Path(get_settings().domo_export_dir)):
        return import_raw_file(db)
    return refresh_from_file(db)


# --- Domo P&L by period (builder / job / window / quarter / half / YTD / YoY) ---


class DomoCell(BaseModel):
    revenue: float
    cost: float
    product_margin: float
    c9009_margin: float
    other_labor_net: float
    wash_labor_net: float
    margin: float
    margin_pct: float | None
    jobs: int


class DomoPeriod(BaseModel):
    key: str
    label: str
    start: date
    end: date


class DomoPLRow(BaseModel):
    label: str
    sublabel: str | None
    cells: list[DomoCell]


class DomoPLReport(BaseModel):
    mode: str
    builder: str | None
    job: str | None
    note: str | None
    source: str | None
    no_data: bool
    periods: list[DomoPeriod]
    totals: list[DomoCell]
    rows: list[DomoPLRow]
    updated_at: datetime | None


def _aggregate(txns: list[DomoTxn]) -> DomoCell:
    ps = pc = cs = cc = os_ = oc = ws = wc = 0.0
    jobs: set = set()
    for t in txns:
        sales, cost = _d(t.sales), _d(t.cost)
        jobs.add(t.job_id or t.code_prefix)
        if t.code_type == "G":
            ps += sales
            pc += cost
        elif t.code_type == "I":
            sku = (t.sku or "").upper()
            if sku == "C9009":
                cs += sales
                cc += cost
            elif sku in MARGIN_EXCLUDED_LABOR_CODES:  # overhead/rebill wash — excluded from margin
                ws += sales
                wc += cost
            else:
                os_ += sales
                oc += cost
    # revenue/cost/margin exclude the wash codes (kept separately for transparency)
    revenue = ps + cs + os_
    cost_total = pc + cc + oc
    margin = revenue - cost_total
    return DomoCell(
        revenue=round(revenue, 2), cost=round(cost_total, 2),
        product_margin=round(ps - pc, 2), c9009_margin=round(cs - cc, 2),
        other_labor_net=round(os_ - oc, 2), wash_labor_net=round(ws - wc, 2),
        margin=round(margin, 2),
        margin_pct=round(margin / revenue * 100, 1) if revenue else None,
        jobs=len(jobs),
    )


def _mdy(d: date) -> str:
    return f"{d.month}/{d.day}/{d.strftime('%y')}"


def _periods(mode, year, quarter, half, start, end, today) -> list[DomoPeriod]:
    if mode == "quarter":
        s, e = quarter_range(year, quarter)
        return [DomoPeriod(key="p", label=f"Q{quarter} {year}", start=s, end=e)]
    if mode == "half":
        s, e = half_range(year, half)
        return [DomoPeriod(key="p", label=f"H{half} {year}", start=s, end=e)]
    if mode == "ytd":
        s, e = ytd_range(year, today)
        return [DomoPeriod(key="p", label=f"YTD {year} (through {_mdy(e)})", start=s, end=e)]
    if mode == "yoy":
        s1, e1 = ytd_range(year, today)
        s0, e0 = ytd_range(year - 1, today)
        return [
            DomoPeriod(key="cur", label=f"YTD {year}", start=s1, end=e1),
            DomoPeriod(key="prior", label=f"YTD {year - 1}", start=s0, end=e0),
        ]
    # window (default)
    s = start or date(today.year, 1, 1)
    e = end or today
    return [DomoPeriod(key="p", label=f"{_mdy(s)} – {_mdy(e)}", start=s, end=e)]


@router.get("/reports/domo-pl", response_model=DomoPLReport, dependencies=[Depends(read_access)])
def domo_pl_report(
    db: Session = Depends(get_db),
    mode: str = Query("window"),
    builder: str | None = None,
    job: str | None = None,
    year: int | None = None,
    quarter: int = 1,
    half: int = 1,
    start: date | None = None,
    end: date | None = None,
):
    """Department P&L from Domo transactions, sliced by the chosen period and scope."""
    today = date.today()
    year = year or today.year
    periods = _periods(mode, year, quarter, half, start, end, today)

    updated_at = db.query(func.max(DomoTxn.imported_at)).scalar()
    total_txns = db.query(func.count(DomoTxn.id)).scalar() or 0
    sources = [s[0] for s in db.query(DomoTxn.source_file).distinct().all() if s[0]]
    source = sources[0] if len(sources) == 1 else (sources[0] if sources else None)
    if total_txns == 0:
        return DomoPLReport(mode=mode, builder=builder, job=job, no_data=True, source=None,
                            note="No period data yet — click “Calculate from last Domo pull” to "
                                 "build it from the most recent Domo cost pull.",
                            periods=periods, totals=[], rows=[], updated_at=updated_at)

    # scope filter applied to every period query
    def scoped(q):
        if job:
            q = q.filter((DomoTxn.job_code == job.strip()) | (DomoTxn.code_prefix == job.strip()))
        elif builder:
            q = q.filter(DomoTxn.account_name == builder)
        return q

    # grouping: single job -> that job; a builder -> its jobs; else -> builders
    if job:
        def key_of(t):
            return (t.job_code or t.code_prefix or "—", t.account_name)
    elif builder:
        def key_of(t):
            return (t.job_code or t.code_prefix or "—", t.community_name)
    else:
        def key_of(t):
            return (t.account_name or "Unassigned / no job match", None)

    # collect rows aligned across periods
    row_keys: list[tuple] = []
    row_cells: dict[tuple, list[DomoCell | None]] = {}
    totals: list[DomoCell] = []

    for pi, p in enumerate(periods):
        txns = scoped(
            db.query(DomoTxn).filter(DomoTxn.txn_date >= p.start, DomoTxn.txn_date <= p.end)
        ).all()
        totals.append(_aggregate(txns))
        grouped: dict[tuple, list[DomoTxn]] = {}
        for t in txns:
            grouped.setdefault(key_of(t), []).append(t)
        for k, ts in grouped.items():
            if k not in row_cells:
                row_keys.append(k)
                row_cells[k] = [None] * len(periods)
            row_cells[k][pi] = _aggregate(ts)

    empty = DomoCell(revenue=0, cost=0, product_margin=0, c9009_margin=0,
                     other_labor_net=0, wash_labor_net=0, margin=0, margin_pct=None, jobs=0)
    # sort rows by first-period margin ascending (worst first) so drags surface
    row_keys.sort(key=lambda k: (row_cells[k][0].margin if row_cells[k][0] else 0))
    rows = [
        DomoPLRow(label=k[0], sublabel=k[1], cells=[c or empty for c in row_cells[k]])
        for k in row_keys
    ]
    note = None
    if source == SNAPSHOT_SOURCE:
        note = ("Calculated from the last Domo cost pull — each house's actual P&L is dated to its "
                "install date. Houses without a date are not shown in a period.")
    return DomoPLReport(
        mode=mode, builder=builder, job=job, no_data=False, note=note, source=source,
        periods=periods, totals=totals, rows=rows, updated_at=updated_at,
    )


@router.get("/reports/domo-pl/builders", response_model=list[str], dependencies=[Depends(read_access)])
def domo_pl_builders(db: Session = Depends(get_db)):
    rows = (
        db.query(DomoTxn.account_name)
        .filter(DomoTxn.account_name.isnot(None))
        .distinct()
        .order_by(DomoTxn.account_name)
        .all()
    )
    return [r[0] for r in rows]


@router.post("/reports/domo-pl/refresh", dependencies=[Depends(write_access)])
def domo_pl_refresh(db: Session = Depends(get_db)):
    """The report's button: use a dated transaction export if present, else calculate
    period data from the last Domo cost pull (each house dated by its install date)."""
    return refresh_domo_txns(db)
