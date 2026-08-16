"""Order Pack — private mode inside Optimus at /ordering-platform/pack.

Brian's DR Horton cabinet ordering runs as four physical OneDrive folders under
"Sold Jobs\\New Orders". A job folder moves down the chain and its position IS
its status. "New Orders Status.xlsx" was supposed to mirror that but corrupts
constantly, so this module owns the state instead and the spreadsheet retires.

Two audiences, two auth schemes:

  * Brian's browser  — normal cms_token login PLUS an owner allowlist
    (ORDERPACK_OWNER_EMAILS). No COAST tile, no nav link, nobody else sees it.
  * The on-prem agent — a shared secret in the X-Pack-Key header
    (ORDERPACK_AGENT_KEY), same approach as WALLPAPER_FEED_KEY. The agent runs
    on Brian's PC because only that machine can see OneDrive, Outlook and the
    logged-in VendorSuite session.

Phase A (this file) is deliberately read-only about Optimus: the folder scan
writes ONLY the Order Pack columns. It never touches `steps`, never calls
_rollup_stages(), and never moves a job's status — so Optimus stays exactly as
correct as it is today while the board starts telling the truth about where
folders physically are. Stage execution (Phase B onward) is what stamps steps,
and it does so through the same server helpers Optimus already uses.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps import NATIONAL_BUILDER_PREFIXES
from app.api.ordering import get_or_create_checklist
from app.auth.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import (
    RUN_KINDS,
    Account,
    AccountType,
    Job,
    JobStatus,
    OrderingChecklist,
    PackRun,
    User,
    get_setting,
    set_setting,
)

router = APIRouter(prefix="/ordering-platform/pack", tags=["order-pack"])

# The four stage folders, in order, plus Century (a flat folder of job folders,
# no stage chain) and the two terminal buckets.
STAGE_FOLDERS = [
    ("stage1", "1. POs and Selections", 1),
    ("stage2", "2. Orders and Layouts", 2),
    ("stage3", "3. SOs and Order Comparison", 3),
    ("stage4", "4. POs attached", 4),
]
FOLDER_LABELS = {
    "stage1": "1. POs & Selections",
    "stage2": "2. Orders & Layouts",
    "stage3": "3. SOs & Comparison",
    "stage4": "4. POs Attached",
    "century": "Century Orders",
    "sold": "Filed to Sold Jobs",
    "missing": "Folder not found",
}
# Buckets a scan can move a job out of. A job that has never been scanned keeps
# a null current_folder and is never demoted to "missing".
PHYSICAL_FOLDERS = {"stage1", "stage2", "stage3", "stage4", "century"}

LAST_SCAN_KEY = "orderpack.last_scan"      # summary JSON (unmatched folders, counts)
AGENT_SEEN_KEY = "orderpack.agent_seen"    # ISO timestamp of the last agent contact

# Standing exclusions — never appear in a cabinet list anywhere in this pipeline.
EXCLUDED_SKUS = ("RANGE1.30", "REF.2D.36", "DISHW24")


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def owner_access(user: User = Depends(get_current_user)) -> User:
    """Order Pack is Brian's private mode: allowlisted logins only."""
    allowed = get_settings().orderpack_owner_list
    if (user.email or "").lower() not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not found")
    return user


def agent_access(x_pack_key: str = Header(default="")) -> None:
    """The on-prem agent's shared secret."""
    if x_pack_key != get_settings().orderpack_agent_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad key")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _job_code_from_folder(name: str) -> str | None:
    """Folder names are "{JobCode} {PlanAbbr} {MMDDYY}" (stage 3 may append
    " REVIEW"; Century plan names carry spaces). The job code is the first
    token and always contains a hyphen — e.g. "DRID60-0115 CREE 081326"."""
    head = (name or "").strip().split()
    if not head:
        return None
    code = head[0].upper()
    return code if "-" in code and len(code) >= 4 else None


def _pick(files: list[str], marker: str) -> str | None:
    """Newest file in the folder whose name carries this marker (" PO ", etc.).
    Names end in MMDDYY so a plain sort by name is not date order — sort by the
    trailing date when it parses, else fall back to name order."""
    hits = [f for f in files if marker.lower() in f.lower()]
    if not hits:
        return None

    def key(fname: str):
        stem = fname.rsplit(".", 1)[0]
        tail = stem.split()[-1] if stem.split() else ""
        if len(tail) == 6 and tail.isdigit():
            return (1, tail[4:6] + tail[0:2] + tail[2:4])  # YYMMDD
        return (0, fname.lower())

    return sorted(hits, key=key)[-1]


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _iso(dt: datetime | date | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _national_jobs_query(db: Session):
    return (
        db.query(Job)
        .join(Account, Job.account_id == Account.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(
            Account.type == AccountType.builder,
            or_(*[Account.name.like(f"{p}%") for p in NATIONAL_BUILDER_PREFIXES]),
            Job.status != JobStatus.void,
        )
    )


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class BoardRow(BaseModel):
    job_id: int
    job_code: str | None
    account_name: str
    community_name: str | None
    lot_number: str | None
    address: str
    plan: str | None
    plan_abbr: str | None
    buid: str | None
    status: JobStatus
    # Physical reality, straight off the agent's last scan.
    current_folder: str | None
    folder_name: str | None
    folder_files: list[str]
    selections_file: str | None
    po_file: str | None
    summary_file: str | None
    review: bool
    # Stage stamps (shared with Optimus — same record, same rollup).
    stage1_date: date | None
    stage2_date: date | None
    stage3_date: date | None
    stage4_date: date | None
    # Reference numbers and money.
    po_number: str | None
    po_date: date | None
    po_total: Decimal | None
    so_number: str | None
    so_total: Decimal | None
    carter_po_number: str | None
    sub_number: str | None
    moved_to_sold_date: date | None
    installer_pay_sheet: bool | None
    install_pay: Decimal | None
    exception: str | None
    notes: str | None
    last_scan_at: datetime | None


class RunOut(BaseModel):
    id: int
    kind: str
    stage: int | None
    job_ids: list[int]
    status: str
    requested_by: str | None
    requested_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    log: str | None
    result: dict | None
    error: str | None


class RunCreate(BaseModel):
    kind: str = "scan"
    job_ids: list[int] = Field(default_factory=list)


class PackUpdate(BaseModel):
    """Manual corrections Brian makes on the board (clearing a flag, typing a
    number the agent couldn't read). Install pay is never invented by code, but
    Brian may of course type what he reads on the sheet himself."""

    exception: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    install_pay: Decimal | None = None
    installer_pay_sheet: bool | None = None
    sub_number: str | None = Field(default=None, max_length=10)


class ScanFolder(BaseModel):
    folder: str
    files: list[str] = Field(default_factory=list)


class ScanPayload(BaseModel):
    """What the agent reports after walking the New Orders tree."""

    scanned_at: datetime | None = None
    agent_version: str | None = None
    # bucket key ("stage1".."stage4", "century") -> folders found there
    stages: dict[str, list[ScanFolder]] = Field(default_factory=dict)
    # loose files sitting at the root of a stage folder (staged Carter POs, SOs)
    loose_files: dict[str, list[str]] = Field(default_factory=dict)


class RunFinish(BaseModel):
    status: str = "done"           # done | failed
    result: dict | None = None
    error: str | None = None
    log: str | None = None


def _row(job: Job, cl: OrderingChecklist) -> BoardRow:
    folder = cl.folder_name or ""
    return BoardRow(
        job_id=job.id,
        job_code=job.job_code,
        account_name=job.account.name if job.account else "",
        community_name=job.community.name if job.community else None,
        lot_number=job.lot_number,
        address=job.address,
        plan=job.plan,
        plan_abbr=cl.plan_abbr,
        buid=cl.buid,
        status=job.status,
        current_folder=cl.current_folder,
        folder_name=cl.folder_name,
        folder_files=list(cl.folder_files or []),
        selections_file=cl.selections_file,
        po_file=cl.po_file,
        summary_file=cl.summary_file,
        # Stage 3 appends " REVIEW" to a folder that failed the comparison —
        # that flag is the whole point of the board, so surface it.
        review=folder.upper().endswith("REVIEW"),
        stage1_date=cl.stage1_date,
        stage2_date=cl.stage2_date,
        stage3_date=cl.stage3_date,
        stage4_date=cl.stage4_date,
        po_number=cl.po_number,
        po_date=cl.po_date,
        po_total=cl.po_total,
        so_number=cl.so_number,
        so_total=cl.so_total,
        carter_po_number=cl.carter_po_number,
        sub_number=cl.sub_number,
        moved_to_sold_date=cl.moved_to_sold_date,
        installer_pay_sheet=cl.installer_pay_sheet,
        install_pay=cl.install_pay,
        exception=cl.exception,
        notes=cl.notes,
        last_scan_at=cl.last_scan_at,
    )


def _run_out(run: PackRun) -> RunOut:
    return RunOut(
        id=run.id,
        kind=run.kind,
        stage=run.stage,
        job_ids=list(run.job_ids or []),
        status=run.status,
        requested_by=run.requested_by,
        requested_at=run.requested_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        log=run.log,
        result=run.result,
        error=run.error,
    )


# --------------------------------------------------------------------------
# Brian's endpoints
# --------------------------------------------------------------------------
@router.get("/meta")
def pack_meta(user: User = Depends(owner_access), db: Session = Depends(get_db)):
    """Folder map, agent health, and what the Run panel is allowed to fire."""
    s = get_settings()
    seen = get_setting(db, AGENT_SEEN_KEY)
    last_scan = get_setting(db, LAST_SCAN_KEY)
    import json

    return {
        "folders": [{"key": k, "label": FOLDER_LABELS[k], "stage": n} for k, _, n in STAGE_FOLDERS],
        "folder_labels": FOLDER_LABELS,
        "excluded_skus": list(EXCLUDED_SKUS),
        "agent_last_seen": seen,
        "scan_minutes": s.orderpack_scan_minutes,
        "auto_stage4": s.orderpack_auto_stage4,
        # Stages the agent can actually execute today. Phase A ships the scan;
        # stage 4 lands in Phase B, then 1, 3, 2.
        "runnable": ["scan"],
        "last_scan": json.loads(last_scan) if last_scan else None,
        "owner": user.email,
    }


@router.get("/board", response_model=list[BoardRow])
def pack_board(
    folder: str | None = None,
    account_id: int | None = None,
    community_id: int | None = None,
    include_done: bool = True,
    exceptions_only: bool = False,
    _: User = Depends(owner_access),
    db: Session = Depends(get_db),
):
    """The live board — one row per job, showing where its folder physically is.

    Completed jobs are never auto-archived (Brian's call 8/16/26); pass
    include_done=false to hide the ones already filed to the sold folder.
    """
    query = (
        _national_jobs_query(db)
        .outerjoin(OrderingChecklist, OrderingChecklist.job_id == Job.id)
        .filter(
            or_(
                OrderingChecklist.current_folder.isnot(None),
                Job.status.in_(
                    (JobStatus.ndord, JobStatus.ordprcss, JobStatus.ordsub, JobStatus.ordpo)
                ),
            )
        )
    )
    if account_id is not None:
        query = query.filter(Job.account_id == account_id)
    if community_id is not None:
        query = query.filter(Job.community_id == community_id)
    if folder:
        query = query.filter(OrderingChecklist.current_folder == folder)
    if exceptions_only:
        query = query.filter(OrderingChecklist.exception.isnot(None))
    if not include_done:
        query = query.filter(
            or_(
                OrderingChecklist.current_folder.is_(None),
                OrderingChecklist.current_folder != "sold",
            )
        )

    jobs = query.order_by(Job.job_code.asc().nulls_last(), Job.id).limit(2000).all()
    rows = [_row(job, get_or_create_checklist(db, job)) for job in jobs]
    db.commit()
    return rows


@router.patch("/jobs/{job_id}", response_model=BoardRow)
def pack_update(
    job_id: int,
    payload: PackUpdate,
    _: User = Depends(owner_access),
    db: Session = Depends(get_db),
):
    """Manual edit from the board — clear an exception, add a note, record a
    pay amount the agent couldn't read off the PDF."""
    job = (
        db.query(Job)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(Job.id == job_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cl = get_or_create_checklist(db, job)
    for field in ("exception", "notes", "install_pay", "installer_pay_sheet", "sub_number"):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            setattr(cl, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(cl)
    return _row(job, cl)


@router.get("/runs", response_model=list[RunOut])
def list_runs(limit: int = 25, _: User = Depends(owner_access), db: Session = Depends(get_db)):
    runs = db.query(PackRun).order_by(PackRun.id.desc()).limit(min(limit, 100)).all()
    return [_run_out(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, _: User = Depends(owner_access), db: Session = Depends(get_db)):
    run = db.get(PackRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_out(run)


@router.post("/runs", response_model=RunOut, status_code=201)
def create_run(
    payload: RunCreate,
    user: User = Depends(owner_access),
    db: Session = Depends(get_db),
):
    """Queue work for the agent. It picks the run up on its next poll."""
    if payload.kind not in RUN_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown run kind '{payload.kind}'")
    if payload.kind != "scan":
        # Phase A ships the scan only. The queue, the claim protocol and the log
        # streaming are all real — Phase B just teaches the agent stage 4.
        raise HTTPException(
            status_code=409,
            detail=f"{payload.kind} isn't built yet — Phase A runs the folder scan only",
        )
    already = (
        db.query(PackRun)
        .filter(PackRun.kind == payload.kind, PackRun.status.in_(("queued", "running")))
        .first()
    )
    if already is not None:
        return _run_out(already)  # don't stack identical work
    stage = int(payload.kind[-1]) if payload.kind.startswith("stage") else None
    run = PackRun(
        kind=payload.kind,
        stage=stage,
        job_ids=payload.job_ids or [],
        status="queued",
        requested_by=user.email,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: int, _: User = Depends(owner_access), db: Session = Depends(get_db)):
    run = db.get(PackRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")
    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _run_out(run)


# --------------------------------------------------------------------------
# Agent endpoints (shared secret, no JWT)
# --------------------------------------------------------------------------
@router.post("/agent/scan", dependencies=[Depends(agent_access)])
def agent_scan(payload: ScanPayload, db: Session = Depends(get_db)):
    """Record what the agent found in the four stage folders.

    This is the whole of Phase A's value: the board stops trusting a checkbox
    and starts reporting where each job folder physically sits. It writes only
    the Order Pack columns — Optimus's steps and statuses are untouched.
    """
    import json

    now = datetime.now(timezone.utc)
    seen_job_ids: set[int] = set()
    unmatched: list[dict] = []
    counts: dict[str, int] = {}

    # Index every national-builder job by code once, rather than a query per folder.
    by_code = {
        (j.job_code or "").upper(): j
        for j in _national_jobs_query(db).filter(Job.job_code.isnot(None)).all()
    }

    for bucket, folders in payload.stages.items():
        if bucket not in PHYSICAL_FOLDERS:
            continue
        counts[bucket] = len(folders)
        for entry in folders:
            code = _job_code_from_folder(entry.folder)
            job = by_code.get(code) if code else None
            if job is None:
                unmatched.append({"folder": entry.folder, "bucket": bucket, "job_code": code})
                continue
            cl = get_or_create_checklist(db, job)
            cl.current_folder = bucket
            cl.folder_name = entry.folder
            cl.folder_files = entry.files
            cl.selections_file = _pick(entry.files, " Selections ")
            cl.po_file = _pick(entry.files, " PO ")
            cl.summary_file = _pick(entry.files, " Summary ")
            if not cl.plan_abbr:
                parts = entry.folder.split()
                if len(parts) >= 2:
                    cl.plan_abbr = parts[1][:20]
            cl.last_scan_at = now
            seen_job_ids.add(job.id)

    # Anything we were physically tracking that is no longer in a stage folder:
    # it either finished (filed to the sold folder) or it went missing, and
    # "missing" is a thing Brian needs to see rather than a thing to hide.
    tracked = (
        db.query(OrderingChecklist)
        .filter(OrderingChecklist.current_folder.in_(tuple(PHYSICAL_FOLDERS)))
        .all()
    )
    vanished = 0
    for cl in tracked:
        if cl.job_id in seen_job_ids:
            continue
        cl.current_folder = "sold" if (cl.moved_to_sold_date or cl.stage4_done) else "missing"
        cl.last_scan_at = now
        vanished += 1

    summary = {
        "scanned_at": _iso(payload.scanned_at or now),
        "agent_version": payload.agent_version,
        "counts": counts,
        "matched": len(seen_job_ids),
        "unmatched": unmatched,
        "left_the_chain": vanished,
        "loose_files": payload.loose_files,
    }
    set_setting(db, LAST_SCAN_KEY, json.dumps(summary))
    set_setting(db, AGENT_SEEN_KEY, now.isoformat())
    db.commit()
    return summary


@router.get("/agent/runs/next", dependencies=[Depends(agent_access)])
def claim_next_run(db: Session = Depends(get_db)):
    """Claim the oldest queued run. Returns null when there's nothing to do."""
    set_setting(db, AGENT_SEEN_KEY, datetime.now(timezone.utc).isoformat())
    run = (
        db.query(PackRun)
        .filter(PackRun.status == "queued")
        .order_by(PackRun.id.asc())
        .with_for_update(skip_locked=True)
        .first()
        if db.bind.dialect.name == "postgresql"
        else db.query(PackRun).filter(PackRun.status == "queued").order_by(PackRun.id.asc()).first()
    )
    if run is None:
        db.commit()
        return None
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _run_out(run)


@router.post("/agent/runs/{run_id}/log", dependencies=[Depends(agent_access)])
def append_log(run_id: int, payload: dict, db: Session = Depends(get_db)):
    """Stream a line (or a block) of agent output onto the run."""
    run = db.get(PackRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    line = str(payload.get("line", "")).rstrip()
    if line:
        run.log = ((run.log or "") + line + "\n")[-100_000:]  # keep the tail, not the world
    db.commit()
    return {"ok": True, "cancelled": run.status == "cancelled"}


@router.post("/agent/runs/{run_id}/finish", dependencies=[Depends(agent_access)])
def finish_run(run_id: int, payload: RunFinish, db: Session = Depends(get_db)):
    run = db.get(PackRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run.status = payload.status if payload.status in ("done", "failed") else "failed"
    run.result = payload.result
    run.error = payload.error
    if payload.log:
        run.log = ((run.log or "") + payload.log)[-100_000:]
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/agent/heartbeat", dependencies=[Depends(agent_access)])
def heartbeat(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    set_setting(db, AGENT_SEEN_KEY, now.isoformat())
    db.commit()
    queued = db.query(func.count(PackRun.id)).filter(PackRun.status == "queued").scalar() or 0
    return {"ok": True, "at": now.isoformat(), "queued_runs": int(queued)}
