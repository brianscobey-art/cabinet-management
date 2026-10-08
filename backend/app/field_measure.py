"""Field Measures report: which houses need a measure, which layout template
each one prints from, what has already been printed, and the stamped PDF.

Templates live under Sales\\Builders (Brian, 10/8/26): one plan-level layout
PDF per plan + swing, in a "Layouts" folder beside the plan's 2020 design
files. The house's plan abbreviation and swing come from the 3.0 tracker
("House Plan Abbr" + "Swing", e.g. FREE-L). A layout attached to the job
itself (JobDocument doc_type "layout") wins over the plan template.

The cloud app cannot see OneDrive, so the uploader mirrors the template PDFs
to R2 under layout-templates/ and this module reads them from there when the
local folder is absent.
"""
from __future__ import annotations

import io
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import (
    Account, AccountType, FieldMeasure, Job, JobDocument, LayoutPrint, PhaseUpdate,
)
from app.phases import PHASE_HIDDEN_STATUSES, PHASE_LABELS

TEMPLATE_PREFIX = "layout-templates/"
# Houses at these phases are the ones a measurer is about to visit.
MEASURE_PHASES = {"3", "4", "4.1", "4.2"}

_EXCLUDE_DIR = re.compile(r"archive|(^|\s)old(\s|$)|_to_delete|\btops?\b", re.I)
_EXCLUDE_NAME = re.compile(r"\bCAB\b|\bTops?\b|Sales Center", re.I)
_SERIES = re.compile(r"^(DRH|EX|CC)(\d)?$", re.I)  # Horton, Express, Century Complete
_DATE6 = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_DIVISIONS = (
    ("panama", "Panama City"), ("montgomery", "Montgomery"),
    ("pensacola", "Pensacola"), ("tallahassee", "Tallahassee"),
    ("pens", "Pensacola"), ("mont", "Montgomery"), ("tall", "Tallahassee"), ("pc", "Panama City"),
)


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------
@dataclass
class Template:
    rel: str            # path relative to the templates root, forward slashes
    name: str           # file name
    version: str        # MMDDYY from the name, else ISO mtime
    version_date: date | None
    series: str | None  # "DRH1", "EX4", "DRH" ...
    swing: str | None   # "L" / "R" / None (either / not stated)
    plan_tokens: tuple[str, ...]
    division: str | None
    source: str = "local"   # "local" | "r2"
    local_path: Path | None = None
    r2_key: str | None = None


def _is_template(rel_parts: tuple[str, ...], name: str) -> bool:
    if not name.lower().endswith(".pdf"):
        return False
    if any(_EXCLUDE_DIR.search(p) for p in rel_parts[:-1]) or _EXCLUDE_NAME.search(name):
        return False
    parent = rel_parts[-2].lower() if len(rel_parts) >= 2 else ""
    return parent in ("layout", "layouts") or "layout" in name.lower()


def _parse_name(rel: str, name: str, mtime: float | None) -> dict:
    stem = Path(name).stem
    version_date = None
    m = _DATE6.search(stem)
    if m:
        try:
            version_date = datetime.strptime(m.group(1), "%m%d%y").date()
        except ValueError:
            version_date = None
    version = version_date.strftime("%m%d%y") if version_date else (
        datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M") if mtime else "0")
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", _DATE6.sub(" ", stem)) if t]
    series = None
    swing = None
    plan: list[str] = []
    for t in tokens:
        tl = t.lower()
        if series is None and _SERIES.match(t) and not plan:
            series = t.upper()
            continue
        if tl in ("layout", "std"):
            continue
        if tl in ("l", "r", "lh", "rh"):
            swing = tl[0].upper()
            continue
        plan.append(tl)
    division = None
    for frag, label in _DIVISIONS:
        if any(frag in p.lower() for p in Path(rel).parts[:-1]):
            division = label
            break
    return dict(version=version, version_date=version_date, series=series, swing=swing,
                plan_tokens=tuple(plan), division=division)


_TPL_CACHE: dict[str, object] = {"at": 0.0, "items": [], "source": None}


def list_templates(force: bool = False) -> tuple[list[Template], str]:
    """All plan layout templates, from the local Sales folder when it exists,
    otherwise from the R2 mirror. Cached for ten minutes."""
    if not force and time.time() - _TPL_CACHE["at"] < 600 and _TPL_CACHE["items"]:
        return _TPL_CACHE["items"], _TPL_CACHE["source"]  # type: ignore[return-value]
    s = get_settings()
    root = Path(s.layout_templates_dir)
    items: list[Template] = []
    source = "none"
    if root.is_dir():
        source = "local"
        for p in root.rglob("*.pdf"):
            rel_parts = p.relative_to(root).parts
            if not _is_template(rel_parts, p.name):
                continue
            rel = "/".join(rel_parts)
            info = _parse_name(rel, p.name, p.stat().st_mtime)
            items.append(Template(rel=rel, name=p.name, source="local", local_path=p, **info))
    elif s.r2_enabled:
        source = "r2"
        from app.storage import _client, _list

        for key, _size, lm in _list(_client(s), s.r2_bucket, TEMPLATE_PREFIX):
            rel = key[len(TEMPLATE_PREFIX):]
            rel_parts = tuple(rel.split("/"))
            if not _is_template(rel_parts, rel_parts[-1]):
                continue
            info = _parse_name(rel, rel_parts[-1], lm.timestamp())
            items.append(Template(rel=rel, name=rel_parts[-1], source="r2", r2_key=key, **info))
    _TPL_CACHE.update(at=time.time(), items=items, source=source)
    return items, source


def template_bytes(t: Template) -> bytes:
    if t.local_path is not None:
        return t.local_path.read_bytes()
    s = get_settings()
    from app.storage import _client

    return _client(s).get_object(Bucket=s.r2_bucket, Key=t.r2_key)["Body"].read()


def iter_local_templates():
    """(path, rel) for every template PDF on the source PC — what the uploader mirrors."""
    root = Path(get_settings().layout_templates_dir)
    if not root.is_dir():
        return
    for p in root.rglob("*.pdf"):
        rel_parts = p.relative_to(root).parts
        if _is_template(rel_parts, p.name):
            yield p, "/".join(rel_parts)


# --------------------------------------------------------------------------
# Matching a house to a template
# --------------------------------------------------------------------------
@dataclass
class HousePlan:
    abbr: str | None        # tracker House Plan Abbr (ALAB)
    name: str | None        # tracker House Plan (DRH1 Alabaster STD)
    swing: str | None       # L / R / None  (tracker "X" -> None: either)
    series: str | None
    tokens: tuple[str, ...]
    division: str | None

    @property
    def label(self) -> str:
        base = self.abbr or " ".join(t.upper() for t in self.tokens) or "?"
        return f"{base}-{self.swing}" if self.swing else base


def house_plan(tracker_row: dict | None, job: Job) -> HousePlan:
    abbr = name = swing = None
    if tracker_row:
        abbr = (str(tracker_row.get("House Plan Abbr") or "").strip() or None)
        name = (str(tracker_row.get("House Plan") or "").strip() or None)
        sw = str(tracker_row.get("Swing") or "").strip().upper()
        swing = sw if sw in ("L", "R") else None
    if not name and job.plan:
        # VS-created jobs carry "DRH1 Madison STD/B15/L"
        parts = [p for p in re.split(r"[/\s]+", job.plan) if p]
        if parts and parts[-1].upper() in ("L", "R"):
            swing = swing or parts.pop().upper()
        name = " ".join(parts) or None
    tokens: list[str] = []
    series = None
    for t in re.split(r"[^A-Za-z0-9]+", name or ""):
        if not t:
            continue
        if series is None and _SERIES.match(t) and not tokens:
            series = t.upper()
            continue
        if t.lower() in ("std", "l", "r"):
            continue
        tokens.append(t.lower())
    division = None
    acct = (job.account.name if job.account else "").lower()
    for frag, label in _DIVISIONS:
        if frag in acct:
            division = label
            break
    return HousePlan(abbr=abbr, name=name, swing=swing, series=series, tokens=tuple(tokens),
                     division=division)


@dataclass
class Match:
    template: Template | None
    status: str          # ok | swing | missing | no-plan
    note: str = ""


def match_template(plan: HousePlan, templates: list[Template]) -> Match:
    if not plan.tokens and not plan.abbr:
        return Match(None, "no-plan", "no plan on the tracker or the job")
    main = plan.tokens[-1] if plan.tokens else None
    cands = []
    for t in templates:
        if not t.plan_tokens:
            continue
        # Horton and Express are different plan families that reuse names
        # (Madison exists in both), so the series LETTERS must agree when both
        # sides state one.
        if plan.series and t.series and plan.series[:2].upper() != t.series[:2].upper():
            continue
        words = set(t.plan_tokens)
        if main and main in words and all(tok in words for tok in plan.tokens):
            score = 10
        elif plan.abbr and plan.abbr.lower() in words:
            score = 8
        elif main and main in words:
            score = 6
        else:
            continue
        if plan.series and t.series and plan.series.upper() == t.series.upper():
            score += 2
        if plan.division and t.division == plan.division:
            score += 4
        cands.append((score, t))
    if not cands:
        return Match(None, "missing", f"no template for {plan.label}")
    exact = [c for c in cands if plan.swing and c[1].swing == plan.swing]
    either = [c for c in cands if c[1].swing is None]
    pool = exact or (either if plan.swing else cands) or []
    if not pool:
        have = sorted({c[1].swing for c in cands if c[1].swing})
        return Match(None, "swing", f"no {plan.label} template · have {', '.join(f'{plan.abbr or main}-{s}' for s in have)}")
    pool.sort(key=lambda c: (c[0], c[1].version_date or date.min, c[1].version), reverse=True)
    best = pool[0][1]
    note = ""
    if plan.division and best.division and best.division != plan.division:
        # Same plan family, another division's drawing -- usable, but say so.
        note = f"from the {best.division} plan set"
    elif plan.swing and best.swing is None:
        note = "template has no swing"
    return Match(best, "ok", note)


# --------------------------------------------------------------------------
# Report rows
# --------------------------------------------------------------------------
@dataclass
class Row:
    account_name: str
    community_name: str | None
    job_id: int
    job_code: str | None
    lot_number: str | None
    address: str
    plan_label: str
    plan_name: str | None
    phase: str | None
    phase_label: str | None
    measure_date: date | None
    fm_complete_date: date | None
    fm_correct: bool
    fm_incorrect: bool
    source: str | None          # template | job_doc | None
    source_name: str | None
    source_version: str | None
    source_status: str          # ok | swing | missing | no-plan
    source_note: str
    last_printed_at: datetime | None
    last_printed_by: str | None
    last_printed_version: str | None
    print_state: str            # new | revised | printed
    needs_print: bool


def _tracker_by_code() -> dict[str, dict]:
    try:
        from app.smartsheet.api import _tracker_rows

        rows, ok, _ = _tracker_rows()
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for r in rows:
        code = str(r.get("Job Code") or "").strip()
        if code:
            out[code] = r
    return out


def _latest(db: Session, model, job_ids: list[int], order_col=None) -> dict[int, object]:
    if not job_ids:
        return {}
    sub = (
        db.query(model.job_id, func.max(model.id).label("max_id"))
        .filter(model.job_id.in_(job_ids))
        .group_by(model.job_id)
        .subquery()
    )
    return {r.job_id: r for r in db.query(model).join(sub, model.id == sub.c.max_id).all()}


def build_rows(db: Session) -> dict:
    today = date.today()
    jobs = (
        db.query(Job)
        .join(Account, Job.account_id == Account.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .filter(Account.type == AccountType.builder, Job.status.notin_(PHASE_HIDDEN_STATUSES))
        .all()
    )
    ids = [j.id for j in jobs]
    latest_phase = _latest(db, PhaseUpdate, ids)
    last_print = _latest(db, LayoutPrint, ids)
    measures = {fm.job_id: fm for fm in db.query(FieldMeasure).filter(FieldMeasure.job_id.in_(ids)).all()} if ids else {}
    layouts: dict[int, JobDocument] = {}
    if ids:
        for doc in (db.query(JobDocument)
                    .filter(JobDocument.job_id.in_(ids), JobDocument.doc_type == "layout")
                    .order_by(JobDocument.id.desc()).all()):
            layouts.setdefault(doc.job_id, doc)
    templates, tpl_source = list_templates()
    tracker = _tracker_by_code()

    rows: list[Row] = []
    for job in jobs:
        cur = latest_phase.get(job.id)
        phase = cur.phase if cur else None
        fm = measures.get(job.id)
        lp = last_print.get(job.id)
        in_window = bool(job.measure_date and (today - job.measure_date).days <= 14
                         and (job.measure_date - today).days <= 21)
        if not (phase in MEASURE_PHASES or in_window or lp is not None):
            continue
        plan = house_plan(tracker.get(job.job_code or ""), job)
        doc = layouts.get(job.id)
        if doc is not None:
            source, source_name, status, note = "job_doc", doc.filename, "ok", "layout attached to the job"
            mt = Path(doc.file_path)
            version = (datetime.fromtimestamp(mt.stat().st_mtime).strftime("%Y-%m-%dT%H:%M")
                       if mt.is_file() else f"doc{doc.id}")
        else:
            m = match_template(plan, templates)
            source = "template" if m.template else None
            source_name = m.template.rel if m.template else None
            version = m.template.version if m.template else None
            status, note = m.status, m.note
        if lp is None:
            state = "new"
        elif version and lp.source_version != version:
            state = "revised"
        else:
            state = "printed"
        rows.append(Row(
            account_name=job.account.name,
            community_name=job.community.name if job.community else None,
            job_id=job.id, job_code=job.job_code, lot_number=job.lot_number, address=job.address,
            plan_label=plan.label, plan_name=plan.name,
            phase=phase, phase_label=PHASE_LABELS.get(phase) if phase else None,
            measure_date=job.measure_date,
            fm_complete_date=fm.complete_date if fm else None,
            fm_correct=bool(fm and fm.correct), fm_incorrect=bool(fm and fm.incorrect),
            source=source, source_name=source_name, source_version=version,
            source_status=status, source_note=note,
            last_printed_at=lp.printed_at if lp else None,
            last_printed_by=lp.printed_by if lp else None,
            last_printed_version=lp.source_version if lp else None,
            print_state=state,
            needs_print=bool(source) and state in ("new", "revised"),
        ))

    def _lot(r: Row):
        lot = (r.lot_number or "").strip()
        return (0, int(lot)) if lot.isdigit() else (1, lot)

    rows.sort(key=lambda r: (r.account_name.lower(), (r.community_name or "~").lower(), _lot(r)))
    last_run = db.query(LayoutPrint).order_by(LayoutPrint.printed_at.desc()).first()
    run = None
    if last_run:
        n = db.query(func.count(LayoutPrint.id)).filter(LayoutPrint.batch_id == last_run.batch_id).scalar()
        run = {"at": last_run.printed_at, "by": last_run.printed_by, "count": n}
    return {"rows": rows, "templates": len(templates), "templates_source": tpl_source,
            "templates_dir": get_settings().layout_templates_dir, "last_run": run}


# --------------------------------------------------------------------------
# Stamping + print run
# --------------------------------------------------------------------------
STAMP_W, STAMP_H = 276.0, 100.0  # points: ~3.8 x 1.4 in, the empty title-block corner


def _stamp_rect(page):
    """The blank bottom-left corner of the title block. The 'Note: this drawing
    is an artistic interpretation' box is the first drawn rectangle in the
    bottom band; the stamp sits to its left, bottom-aligned with it."""
    import fitz  # PyMuPDF

    H, W = page.rect.height, page.rect.width
    note = None
    for d in page.get_drawings():
        r = d.get("rect")
        if r is None or r.y0 < H * 0.75 or r.width < 150 or r.height < 50:
            continue
        if note is None or r.x0 < note.x0:
            note = r
    if note is not None and note.x0 > 200:
        x1 = note.x0 - 8
        y1 = note.y1 - 2
    else:
        x1, y1 = 16 + STAMP_W, H - 22
    x0 = 16
    w = min(STAMP_W, x1 - x0)
    return fitz.Rect(x0, y1 - STAMP_H, x0 + w, y1)


def _draw_check(page, box, color=(0.07, 0.07, 0.07)):
    """A heavy check mark bigger than its box, with a grey offset copy behind it
    and a thin white highlight on top -- reads as raised ink on paper."""
    import fitz

    x, y = box.x0, box.y0
    pts = [(x - 2, y + 7), (x + 5.5, y + 14.5), (x + 19, y - 4)]
    sh = [(px + 1.6, py + 1.6) for px, py in pts]
    page.draw_polyline(sh, color=(0.6, 0.6, 0.6), width=3.4, lineCap=1, lineJoin=1)
    page.draw_polyline(pts, color=color, width=3.4, lineCap=1, lineJoin=1)
    hl = [(px + 0.3, py - 0.9) for px, py in pts]
    page.draw_polyline(hl, color=(1, 1, 1), width=0.7, lineCap=1, lineJoin=1)


def stamp_page(page, *, community: str, lot: str, job_code: str, plan: str, layout: str,
               printed: date, reprint: bool, measured: date | None, correct: bool) -> None:
    import fitz

    R = _stamp_rect(page)
    page.draw_rect(R, color=(0, 0, 0), width=0.8)
    grey, ink = (0.33, 0.33, 0.33), (0.07, 0.07, 0.07)
    fs = 8.5
    pad = 7
    col2 = R.x0 + R.width * 0.67
    rows = [
        (("Community: ", community), ("Lot: ", lot)),
        (("Job: ", job_code), ("Plan: ", plan)),
        (("Layout: ", layout), (("Reprint: " if reprint else "Printed: "), _fmt_date(printed))),
    ]
    y = R.y0 + pad + fs
    for (l1, v1), (l2, v2) in rows:
        x = R.x0 + pad
        page.insert_text((x, y), l1, fontname="helv", fontsize=fs, color=grey)
        x += fitz.get_text_length(l1, fontname="helv", fontsize=fs)
        maxw = col2 - 6 - x
        v1 = _fit(v1, maxw, fs, "hebo")
        page.insert_text((x, y), v1, fontname="hebo", fontsize=fs, color=ink)
        x = col2
        page.insert_text((x, y), l2, fontname="helv", fontsize=fs, color=grey)
        x += fitz.get_text_length(l2, fontname="helv", fontsize=fs)
        page.insert_text((x, y), _fit(v2, R.x1 - pad - x, fs, "hebo"), fontname="hebo", fontsize=fs, color=ink)
        y += fs + 4.5
    # bottom row: checkbox + label on the left, Measured line on the right
    by = R.y1 - pad - 13
    box = fitz.Rect(R.x0 + pad, by, R.x0 + pad + 13, by + 13)
    page.draw_rect(box, color=ink, width=1.1)
    label_font = "hebo" if correct else "helv"
    page.insert_text((box.x1 + 6, box.y1 - 2.5), "Complete / Correct", fontname=label_font, fontsize=fs, color=ink)
    if correct:
        _draw_check(page, box)
    mx = col2
    page.insert_text((mx, box.y1 - 2.5), "Measured: ", fontname="helv", fontsize=fs, color=grey)
    lx0 = mx + fitz.get_text_length("Measured: ", fontname="helv", fontsize=fs)
    lx1 = R.x1 - pad
    page.draw_line((lx0, box.y1 - 0.5), (lx1, box.y1 - 0.5), color=ink, width=0.8)
    if measured:
        txt = _fmt_date(measured)
        tw = fitz.get_text_length(txt, fontname="hebo", fontsize=fs)
        page.insert_text(((lx0 + lx1 - tw) / 2, box.y1 - 2.5), txt, fontname="hebo", fontsize=fs, color=ink)


def _fit(text: str, maxw: float, fs: float, font: str) -> str:
    import fitz

    text = text or ""
    if fitz.get_text_length(text, fontname=font, fontsize=fs) <= maxw:
        return text
    while text and fitz.get_text_length(text + "…", fontname=font, fontsize=fs) > maxw:
        text = text[:-1]
    return text + "…"


def _lot4(lot: str | None) -> str:
    s = (lot or "").strip()
    m = re.fullmatch(r"(\d{1,4})(?:\.0+)?", s)
    return m.group(1).zfill(4) if m else (s or "—")


def _fmt_date(d) -> str:
    return f"{d.month}/{d.day}/{str(d.year)[2:]}" if d else ""


def print_run(db: Session, job_ids: list[int], printed_by: str | None) -> tuple[bytes, dict]:
    """Stamp each selected house's layout and return one merged PDF, recording
    a LayoutPrint per house. Reprint = that house already has a print record."""
    import fitz

    data = build_rows(db)
    by_id = {r.job_id: r for r in data["rows"]}
    templates, _ = list_templates()
    tpl_by_rel = {t.rel: t for t in templates}
    out = fitz.open()
    batch = uuid.uuid4().hex[:12]
    printed, skipped = [], []
    today = date.today()
    for jid in job_ids:
        r = by_id.get(jid)
        if r is None or not r.source:
            skipped.append({"job_id": jid, "reason": (r.source_note if r else "not on the report")})
            continue
        try:
            if r.source == "job_doc":
                doc = (db.query(JobDocument).filter(JobDocument.job_id == jid, JobDocument.doc_type == "layout")
                       .order_by(JobDocument.id.desc()).first())
                p = Path(doc.file_path)
                if p.is_file():
                    pdf_bytes = p.read_bytes()
                else:
                    from app import storage

                    obj = storage.stream_document(storage.document_key(doc.file_path))
                    if obj is None:
                        raise FileNotFoundError(doc.filename)
                    pdf_bytes = obj["Body"].read()
                layout_label = Path(doc.filename).stem
            else:
                t = tpl_by_rel[r.source_name]
                pdf_bytes = template_bytes(t)
                layout_label = Path(t.name).stem.replace("Layout", "").strip()
        except Exception as exc:  # noqa: BLE001
            skipped.append({"job_id": jid, "reason": f"could not read {r.source_name}: {exc}"})
            continue
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        measured = r.fm_complete_date
        correct = bool(r.fm_correct or r.fm_complete_date)
        reprint = r.last_printed_at is not None
        stamp_page(
            src[0], community=r.community_name or r.account_name, lot=_lot4(r.lot_number),
            job_code=r.job_code or f"#{r.job_id}", plan=r.plan_label, layout=layout_label,
            printed=today, reprint=reprint, measured=measured if correct else None, correct=correct,
        )
        out.insert_pdf(src)
        db.add(LayoutPrint(job_id=jid, batch_id=batch, source=r.source, source_name=r.source_name or "",
                           source_version=r.source_version or "0", reprint=reprint,
                           measured_date=measured if correct else None, printed_by=printed_by))
        printed.append({"job_id": jid, "job_code": r.job_code, "reprint": reprint})
    if printed:
        db.commit()
    pdf = out.tobytes(garbage=3, deflate=True) if len(out) else b""
    return pdf, {"batch": batch, "printed": printed, "skipped": skipped}
