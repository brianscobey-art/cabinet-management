"""Field reports from Smartsheet into CabinetTron (Brian 10/30/26). READ ONLY:
nothing here writes to Smartsheet.

"Install Reports" -- the installer's sign-off, still in use. Each new report:
  * shows on the job page (complete?, trade stopping?, what's needed, shoe
    sticks, damage / parts)
  * complete -> phase 12 - Cabinets Installed, unless the house is already
    at 12 or later
  * complete -> the 48-hour post-walk clock starts from the installer's date
    instead of the scheduled install date
  * not complete, or damage / parts -> Parts on the house's punch-board ticket,
    in the installer's words; trade-blocking when they said trade stopping
Clock and parts only fire for reports from the last POST_WALK_LOOKBACK days, so
the first load of the backlog doesn't flood the punch board with parts that
were dealt with weeks ago. Each report acts once (acted_at).

"TBS Quality Control v2" -- the old post-walk form (4/13-9/29/26). Loaded as
history: each becomes a done post_walk visit on its house, unless the house
already has a post-walk record.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import InstallReport, Job, PhaseUpdate, QcReport, ServicePart, ServiceRequest, Visit, set_setting
from app.phases import FINISHED_PHASES

logger = logging.getLogger("uvicorn.error")

REPORT_KEY = "field_reports_report"
SOURCE = "Install report"


# ------------------------------------------------------------- reading ----
def fetch_rows(token: str, sheet_id: int) -> list[tuple[int, dict]]:
    """[(row id, {column title: value})] for one sheet."""
    from app.smartsheet.job_tracker import _client

    with _client(token) as c:
        r = c.get(f"/sheets/{sheet_id}")
        r.raise_for_status()
        sheet = r.json()
    titles = {col["id"]: col["title"] for col in sheet.get("columns", [])}
    out = []
    for row in sheet.get("rows", []):
        cells = {titles.get(cell["columnId"]): cell.get("value") for cell in row.get("cells", [])
                 if cell.get("value") not in (None, "")}
        if cells:
            out.append((row["id"], cells))
    return out


def _text(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _yes(v) -> bool | None:
    s = (_text(v) or "").lower()
    if s in ("yes", "y", "true"):
        return True
    if s in ("no", "n", "false"):
        return False
    return None


def _date(v) -> date | None:
    s = _text(v)
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _when(v) -> datetime | None:
    s = _text(v)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _jobs_by_code(db: Session) -> dict[str, Job]:
    return {j.job_code.strip().upper(): j for j in db.query(Job).filter(Job.job_code.isnot(None)).all()}


# ----------------------------------------------------- install reports ----
def _parts_ticket(db: Session, job: Job) -> ServiceRequest:
    """The house's one 'Parts' ticket -- same rule as Autobot's walks."""
    sr = (db.query(ServiceRequest).filter(ServiceRequest.job_id == job.id, ServiceRequest.title == "Parts")
          .order_by(ServiceRequest.id.desc()).first())
    if sr is None:
        sr = ServiceRequest(job_id=job.id, title="Parts", status="Parts", created_by=SOURCE)
        db.add(sr)
        db.flush()
    return sr


def _act(db: Session, rep: InstallReport, job: Job, today: date) -> list[str]:
    from app.autobot import POST_WALK_DAYS, POST_WALK_LOOKBACK

    done = []
    anchor = rep.install_date or (rep.submitted_at.date() if rep.submitted_at else None)
    recent = bool(anchor and anchor >= today - timedelta(days=POST_WALK_LOOKBACK))

    if rep.complete:
        latest = (db.query(PhaseUpdate).filter(PhaseUpdate.job_id == job.id)
                  .order_by(PhaseUpdate.id.desc()).first())
        if latest is None or latest.phase not in FINISHED_PHASES:
            db.add(PhaseUpdate(job_id=job.id, phase="12", source="install_rpt",
                               noted_by=(rep.installer or SOURCE)[:255]))
            done.append("phase 12")
        if job.install_date is None and anchor:
            job.install_date = anchor
            done.append("install date")
        if recent:
            walks = db.query(Visit).filter(Visit.job_id == job.id, Visit.visit_type == "post_walk").all()
            if not any(v.status == "done" for v in walks):
                close = max(anchor + timedelta(days=POST_WALK_DAYS), today)
                pending = sorted((v for v in walks if v.status == "pending"), key=lambda v: v.id)
                note = f"48h clock from the installer's report ({anchor.month}/{anchor.day})"
                if pending:
                    pending[-1].open_date, pending[-1].close_date = anchor, close
                    pending[-1].notes = pending[-1].notes or note
                    done.append("post-walk clock moved")
                else:
                    db.add(Visit(visit_type="post_walk", job_id=job.id, open_date=anchor, close_date=close,
                                 notes=note, created_by=SOURCE))
                    done.append("post walk created")

    if recent and (rep.complete is False or rep.damage_parts):
        items = [("missing", rep.needed_to_finish), ("damaged", rep.damage_detail)]
        items = [(why, t) for why, t in items if t] or [("other", "See the installer's report")]
        sr = _parts_ticket(db, job)
        stamp = f"Installer report {anchor.month}/{anchor.day}" if anchor else "Installer report"
        for why, text in items:
            db.add(ServicePart(service_request_id=sr.id, part=text[:200], reason=why, found_on="install",
                               trade_blocking=bool(rep.trade_stopping),
                               notes=f"{stamp} - {rep.installer or ''}".strip(" -")[:300]))
        done.append(f"{len(items)} part(s)")
    return done


def sync_install_reports(db: Session, rows: list[tuple[int, dict]], today: date | None = None) -> dict:
    today = today or date.today()
    jobs = _jobs_by_code(db)
    existing = {r.row_id: r for r in db.query(InstallReport).all()}
    new = acted = unmatched = 0
    for row_id, c in rows:
        code = (_text(c.get("Job Code")) or "").upper()
        rep = existing.get(row_id)
        if rep is None:
            rep = InstallReport(row_id=row_id)
            db.add(rep)
            new += 1
        job = jobs.get(code)
        rep.job_code, rep.job_id = code or None, job.id if job else None
        rep.install_date = _date(c.get("Install Date"))
        rep.installer = (_text(c.get("Installer")) or "")[:120] or None
        rep.complete = _yes(c.get("Job Complete?"))
        rep.trade_stopping = _yes(c.get("Trade Stopping?"))
        rep.needed_to_finish = _text(c.get("What Is Needed to Finish?"))
        rep.shoe_sticks = _num(c.get("Sticks of Shoe on Site"))
        rep.damage_parts = _yes(c.get("Damage or Parts Needed?"))
        rep.damage_detail = _text(c.get("Damage / Parts Detail"))
        rep.submitted_at = _when(c.get("Submitted"))
        if job is None:
            unmatched += 1
            continue
        if rep.acted_at is None:
            db.flush()
            rep.actions = ", ".join(_act(db, rep, job, today))[:300] or "none"
            rep.acted_at = datetime.now(timezone.utc)
            acted += 1
    return {"rows": len(rows), "new": new, "acted": acted, "unmatched": unmatched}


# ------------------------------------------------------------ QC v2 -------
QC_SKIP = {"PWID", "Created By", "Created", "Job Code", "Contact List", "Attachment Prompt"}


def _qc_result(c: dict) -> tuple[str, str]:
    """ok / issues, and a one-paragraph summary for the visit's result notes."""
    flags = []
    if _yes(c.get("Are the critical Dimensions good?")) is False:
        flags.append(f"dimensions off: {_text(c.get('What measurement(s) were incorrect?')) or '?'}")
    if _yes(c.get("Are there IGB Items?")):
        flags.append(f"IGB: {_text(c.get('What is needed to make the job complete?')) or 'yes'}")
    if _yes(c.get("Are there Parts Needed?")):
        flags.append(f"parts needed: {_text(c.get('What parts are needed to finish the job')) or 'yes'}")
    if _yes(c.get("Are there service issues to address?")):
        what = _text(c.get("What's the damage?")) or _text(c.get("Replacement")) or "yes"
        flags.append(f"service ({_text(c.get('Repair or Replace')) or 'repair'}): {what}")
    if _yes(c.get("Are there Parts Left on the Site?")):
        flags.append(f"parts left on site: {_text(c.get('What Parts are being left onsite?')) or 'yes'}")
    pulls = [_text(c.get("Island Pull - Fridge Side")), _text(c.get("Island Pull - Opposite Fridge"))]
    if any(p and p.upper() != "NA" for p in pulls):
        flags.append(f"island pulls {pulls[0] or '-'} / {pulls[1] or '-'}")
    result = "issues" if any(not f.startswith("island") for f in flags) else "ok"
    return result, ("QC v2 post walk. " + "; ".join(flags)) if flags else "QC v2 post walk: no issues."


def sync_qc_reports(db: Session, rows: list[tuple[int, dict]]) -> dict:
    jobs = _jobs_by_code(db)
    existing = {r.row_id: r for r in db.query(QcReport).all()}
    walked = {jid for (jid,) in db.query(Visit.job_id).filter(Visit.visit_type == "post_walk").distinct()}
    new = visits = unmatched = 0
    for row_id, c in rows:
        code = (_text(c.get("Job Code")) or "").upper()
        rep = existing.get(row_id)
        if rep is None:
            rep = QcReport(row_id=row_id)
            db.add(rep)
            new += 1
        job = jobs.get(code)
        rep.job_code, rep.job_id = code or None, job.id if job else None
        rep.pwid = (_text(c.get("PWID")) or "").removesuffix(".0") or None
        rep.walked_at = _when(c.get("Created"))
        rep.walked_by = _text(c.get("Created By"))
        rep.result, rep.summary = _qc_result(c)
        rep.answers = json.dumps({k: v for k, v in c.items() if k not in QC_SKIP}, default=str)
        if job is None:
            unmatched += 1
            continue
        if rep.visit_id is None and job.id not in walked:
            day = rep.walked_at.date() if rep.walked_at else (_date(c.get("Install Date")) or date.today())
            v = Visit(visit_type="post_walk", job_id=job.id, status="done", open_date=day, close_date=day,
                      result=rep.result, result_notes=rep.summary, completed_at=rep.walked_at,
                      completed_by=(rep.walked_by or "QC v2")[:255], created_by="QC v2 import")
            db.add(v)
            db.flush()
            rep.visit_id = v.id
            walked.add(job.id)
            visits += 1
    return {"rows": len(rows), "new": new, "post_walks_added": visits, "unmatched": unmatched}


# ------------------------------------------------------------- runner -----
def run(db: Session) -> dict:
    s = get_settings()
    if not s.smartsheet_api_token:
        return {"error": "no Smartsheet token"}
    out = {"at": datetime.now().isoformat(timespec="seconds")}
    for key, sheet_id, sync in (
        ("install_reports", s.smartsheet_install_reports_sheet_id, sync_install_reports),
        ("qc_reports", s.smartsheet_qc_sheet_id, sync_qc_reports),
    ):
        if not sheet_id:
            continue
        try:
            out[key] = sync(db, fetch_rows(s.smartsheet_api_token, sheet_id))
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- one sheet failing must not stop the other
            db.rollback()
            out[key] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            logger.warning("field reports %s failed: %s", key, exc)
    set_setting(db, REPORT_KEY, json.dumps(out, default=str))
    db.commit()
    return out


def job_reports(db: Session, job_id: int) -> dict:
    """The job page's Install & post-walk reports card."""
    installs = (db.query(InstallReport).filter(InstallReport.job_id == job_id)
                .order_by(func.coalesce(InstallReport.submitted_at, InstallReport.acted_at).desc()).all())
    qcs = db.query(QcReport).filter(QcReport.job_id == job_id).order_by(QcReport.walked_at.desc()).all()
    return {
        "install_reports": [{
            "install_date": r.install_date, "installer": r.installer, "complete": r.complete,
            "trade_stopping": r.trade_stopping, "needed_to_finish": r.needed_to_finish,
            "shoe_sticks": r.shoe_sticks, "damage_parts": r.damage_parts, "damage_detail": r.damage_detail,
            "submitted_at": r.submitted_at, "actions": r.actions,
        } for r in installs],
        "qc_reports": [{
            "pwid": r.pwid, "walked_at": r.walked_at, "walked_by": r.walked_by, "result": r.result,
            "summary": r.summary, "answers": json.loads(r.answers or "{}"),
        } for r in qcs],
    }
