from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access
from app.database import get_db
from app.models import Account, AccountType, Community, Job, JobDocument, JobStatus, PhaseUpdate
from app.phases import PHASE_LABELS

router = APIRouter(tags=["reports"])

ACTIVE = Job.status.notin_((JobStatus.closed, JobStatus.void))


def _d(value) -> float:
    return float(value) if value is not None else 0.0


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


REPORTS = [
    ReportInfo(key="phases", name="Phase Report",
               description="Active houses by builder, community, and lot with current construction phase."),
    ReportInfo(key="open-po", name="Open PO Report",
               description="Every job with an open builder PO, its amount, and totals by builder and community."),
    ReportInfo(key="po-status", name="PO Status Summary",
               description="Count and dollar value of POs grouped by status (open, paid, voided)."),
    ReportInfo(key="revenue-builder", name="Revenue by Builder & Community",
               description="Total PO revenue rolled up by builder, then community."),
    ReportInfo(key="revenue-salesperson", name="Revenue by Salesperson",
               description="PO revenue and job count per salesperson."),
    ReportInfo(key="install-week", name="Install Schedule by Week",
               description="Scheduled installs grouped by install week with PO value."),
    ReportInfo(key="unordered", name="Needs Ordering",
               description="Active jobs with an install date but no cabinet PO yet — the risk list."),
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


