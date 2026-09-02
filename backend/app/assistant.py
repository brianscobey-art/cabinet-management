"""The in-app assistant — Claude with read-only tools over CabinetTron's data.

READ-ONLY BY DESIGN (Brian, 9/1/26). Every tool below runs a bounded,
purpose-built query. There is deliberately no "run this SQL" tool: it would be
the most capable option and the least safe one — a misread question could dump
the whole database into a chat panel, and nothing about the request would look
wrong. Adding a tool here is the only way to widen what the assistant can see.

Answers stream, so long ones appear as they are written rather than after a
twenty-second pause.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from app.config import get_settings

logger = logging.getLogger("uvicorn.error")

MODEL = "claude-opus-5"
MAX_TOKENS = 8000
MAX_TURNS = 8          # tool round-trips before we stop; a runaway loop costs real money
ROW_CAP = 200          # never hand back more rows than a person would read


SYSTEM = """You are the assistant inside CabinetTron, the kitchen-and-bath \
operations suite for Carter Lumber's Dothan division (formerly Townsend \
Building Supply — the Townsend name was retired 8/7/26; never use it).

You help Brian Scobey, the K&B manager, and his team: answering questions about \
jobs, looking up criteria, and pulling together the numbers behind a report.

The suite:
- CabinetTron — jobs, phases, documents, ordering pipeline, reports
- Sterling — cabinet pricing: SKU catalog by price group, plan pricing, countertops
- Optimus — the 4-stage ordering pipeline; Order Pack is its private bulk mode
- Autobot — service-tech routing

How to work:
- Use the tools. Never answer a factual question about jobs, pricing or margin \
from memory or inference — look it up. If the tools cannot reach something, say \
so plainly rather than estimating.
- Be direct and brief. Lead with the answer, then the supporting numbers.
- Money to the dollar unless cents matter. Dates as m/d/yy.
- When you show more than a couple of rows, use a markdown table.
- If a question is ambiguous in a way that changes the answer, ask instead of \
guessing.
- You are read-only. If asked to change something, say what you would change \
and where to do it, but be clear you cannot make the edit yourself.
"""


# --------------------------------------------------------------------------
# Tools — each one bounded, each one read-only
# --------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_jobs",
        "description": (
            "Find jobs by any mix of job code, address, community, builder, plan "
            "or status. Returns the matching jobs with their current phase, "
            "install date and status. Use this first for anything job-related."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Free text — job code, street, community, plan."},
                "status": {"type": "string",
                           "description": "Exact status such as 2.0-Ord or 4.0-Punch."},
                "limit": {"type": "integer", "description": f"Max rows, default 25, cap {ROW_CAP}."},
            },
        },
    },
    {
        "name": "job_detail",
        "description": (
            "Everything about one job: address, plan, status, phase history, "
            "install and measure dates, ordering checklist (PO/SO numbers, stage "
            "dates, folder), and the documents attached to it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"job_code": {"type": "string"}},
            "required": ["job_code"],
        },
    },
    {
        "name": "plan_pricing",
        "description": (
            "Sterling's pricing for a house plan: list price, cabinet cost, "
            "freight, labour, COGS, margin and calculated sale price. Omit "
            "'plan' to list every priced plan for a division."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "e.g. 'DRH1 Madison STD'"},
                "division": {"type": "string", "description": "e.g. 'DRH PC'"},
            },
        },
    },
    {
        "name": "sku_lookup",
        "description": (
            "A cabinet SKU's prices across all five price groups, plus its "
            "install group, door and drawer counts. Accepts a partial SKU."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    },
    {
        "name": "run_report",
        "description": (
            "Run one of Sterling's saved reports and get its rows back. "
            "Keys: 'plan-margin' (priced plans vs what DR Horton actually paid), "
            "'reprice-check' (POs written at a superseded price), "
            "'reprice-proposal' (what the levelling changes). Slow — a few "
            "seconds — so only run one when the question needs it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "phase_report",
        "description": (
            "Active houses with their current construction phase, field measure "
            "state and install date, grouped by builder and community. Use for "
            "'what is happening on site' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "builder": {"type": "string"},
                "community": {"type": "string"},
            },
        },
    },
]


def _cap(n: Any, default: int = 25) -> int:
    try:
        return max(1, min(int(n), ROW_CAP))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
def _search_jobs(args: dict) -> Any:
    from sqlalchemy import or_

    from app.database import SessionLocal
    from app.models import Job, OrderingChecklist, PhaseUpdate

    q = (args.get("query") or "").strip()
    limit = _cap(args.get("limit"))
    with SessionLocal() as db:
        query = db.query(Job)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Job.job_code.ilike(like), Job.address.ilike(like),
                                     Job.plan.ilike(like)))
        if args.get("status"):
            query = query.filter(Job.status == args["status"])
        jobs = query.limit(limit).all()
        if not jobs:
            return {"rows": [], "note": "No jobs matched."}

        ids = [j.id for j in jobs]
        phases: dict[int, PhaseUpdate] = {}
        for pu in (db.query(PhaseUpdate).filter(PhaseUpdate.job_id.in_(ids))
                   .order_by(PhaseUpdate.id).all()):
            phases[pu.job_id] = pu          # last write wins == newest
        cls = {c.job_id: c for c in
               db.query(OrderingChecklist).filter(OrderingChecklist.job_id.in_(ids)).all()}
        rows = []
        for j in jobs:
            c = cls.get(j.id)
            rows.append({
                "job_code": j.job_code, "address": j.address, "plan": j.plan,
                "community": j.community.name if j.community else None,
                "builder": j.account.name if j.account else None,
                "status": j.status.value if j.status else None,
                "phase": phases[j.id].phase if j.id in phases else None,
                "measure_date": str(j.measure_date) if j.measure_date else None,
                "install_date": str(j.install_date) if j.install_date else None,
                "builder_po": j.builder_po,
                "so_number": c.so_number if c else None,
            })
        return {"rows": rows, "count": len(rows)}


def _job_detail(args: dict) -> Any:
    from app.database import SessionLocal
    from app.models import Job, JobDocument, OrderingChecklist, PhaseUpdate

    code = (args.get("job_code") or "").strip()
    with SessionLocal() as db:
        job = db.query(Job).filter(Job.job_code.ilike(code)).first()
        if job is None:
            return {"error": f"No job with code {code!r}."}
        c = db.query(OrderingChecklist).filter(OrderingChecklist.job_id == job.id).first()
        phases = (db.query(PhaseUpdate).filter(PhaseUpdate.job_id == job.id)
                  .order_by(PhaseUpdate.id.desc()).limit(10).all())
        docs = db.query(JobDocument).filter(JobDocument.job_id == job.id).all()
        return {
            "job_code": job.job_code, "address": job.address, "plan": job.plan,
            "lot": job.lot_number,
            "community": job.community.name if job.community else None,
            "builder": job.account.name if job.account else None,
            "status": job.status.value if job.status else None,
            "measure_date": str(job.measure_date) if job.measure_date else None,
            "install_date": str(job.install_date) if job.install_date else None,
            "superintendent": job.field_contact_name,
            "builder_po": job.builder_po,
            "po_amount": float(job.po_amount) if job.po_amount else None,
            "phase_history": [
                {"phase": p.phase, "at": str(p.noted_at)[:10], "by": p.noted_by}
                for p in phases
            ],
            "ordering": None if c is None else {
                "stage1": str(c.stage1_date) if c.stage1_date else None,
                "stage2": str(c.stage2_date) if c.stage2_date else None,
                "stage3": str(c.stage3_date) if c.stage3_date else None,
                "stage4": str(c.stage4_date) if c.stage4_date else None,
                "so_number": c.so_number, "carter_po": c.carter_po_number,
                "folder": c.current_folder, "folder_name": c.folder_name,
                "install_pay": float(c.install_pay) if c.install_pay else None,
            },
            "documents": [{"id": d.id, "type": d.doc_type, "name": d.filename} for d in docs],
        }


def _plan_pricing(args: dict) -> Any:
    from app.sterling_app.compute import national_pricing_rows
    from app.sterling_app.database import SessionLocal

    plan = (args.get("plan") or "").strip().lower()
    division = (args.get("division") or "").strip().lower()
    with SessionLocal() as db:
        rows = national_pricing_rows(db, None, None)
    out = []
    for r in rows:
        if plan and plan not in str(r["plan"]).lower():
            continue
        if division and division not in str(r["division"]).lower():
            continue
        out.append({k: (float(v) if hasattr(v, "quantize") else v)
                    for k, v in r.items()})
    if not out:
        return {"rows": [], "note": "No priced plan matched."}
    return {"rows": out[:ROW_CAP], "count": len(out)}


def _sku_lookup(args: dict) -> Any:
    from app.sterling_app.database import SessionLocal
    from app.sterling_app.models import CatalogItem

    sku = (args.get("sku") or "").strip()
    with SessionLocal() as db:
        items = db.query(CatalogItem).filter(CatalogItem.sku.ilike(f"%{sku}%")).limit(40).all()
        if not items:
            return {"rows": [], "note": f"No SKU matching {sku!r}."}
        f = lambda v: float(v) if v is not None else None
        return {"rows": [{
            "sku": i.sku, "description": i.description, "vendor": i.vendor,
            "list_price": f(i.list_price),
            "g1": f(i.price_g1), "g2": f(i.price_g2), "g3": f(i.price_g3),
            "g4": f(i.price_g4), "g5": f(i.price_g5),
            "install_group": i.install_group, "doors": i.doors, "drawers": i.drawers,
        } for i in items]}


def _run_report(args: dict) -> Any:
    from app.sterling_app import reports
    from app.sterling_app.database import SessionLocal

    key = (args.get("key") or "").strip()
    with SessionLocal() as db:
        try:
            data = reports.run(key, db)
        except KeyError:
            return {"error": f"No report {key!r}. Available: "
                             f"{[r['key'] for r in reports.catalog()]}"}
        except ValueError as exc:
            return {"error": str(exc)}
    return {
        "title": data["report"]["title"],
        "meta": {k: v for k, v in data["meta"].items() if k != "headline"},
        "headline": data["meta"].get("headline"),
        "groups": data.get("groups"),
        "rows": data["rows"][:ROW_CAP],
        "row_count": len(data["rows"]),
    }


def _phase_report(args: dict) -> Any:
    from app.api.reports import phase_report as build
    from app.database import SessionLocal

    builder = (args.get("builder") or "").strip().lower()
    community = (args.get("community") or "").strip().lower()
    with SessionLocal() as db:
        rows = build(db=db)
    out = []
    for r in rows:
        d = r.model_dump() if hasattr(r, "model_dump") else dict(r)
        if builder and builder not in str(d.get("account_name", "")).lower():
            continue
        if community and community not in str(d.get("community_name") or "").lower():
            continue
        out.append({k: (str(v) if hasattr(v, "isoformat") else v) for k, v in d.items()})
    return {"rows": out[:ROW_CAP], "count": len(out)}


HANDLERS = {
    "search_jobs": _search_jobs,
    "job_detail": _job_detail,
    "plan_pricing": _plan_pricing,
    "sku_lookup": _sku_lookup,
    "run_report": _run_report,
    "phase_report": _phase_report,
}


def _client():
    import anthropic

    key = get_settings().anthropic_api_key
    if not key:
        raise RuntimeError(
            "The assistant needs an Anthropic API key. Set ANTHROPIC_API_KEY in "
            "backend/.env locally and in Render's environment for the live site."
        )
    return anthropic.Anthropic(api_key=key)


def stream_reply(history: list[dict], page: str | None = None) -> Iterator[dict]:
    """Yield {type, ...} events: text deltas, tool notices, usage, errors.

    The caller turns these into server-sent events. Tool calls loop here rather
    than in the browser so the data never leaves the server unnecessarily.
    """
    import anthropic

    try:
        client = _client()
    except RuntimeError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    system = SYSTEM
    if page:
        system += f"\n\nThe user is currently on: {page}. Prefer it for context."

    messages = [m for m in history if m.get("role") in ("user", "assistant")]
    total_in = total_out = 0

    for turn in range(MAX_TURNS):
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                tools=TOOLS,
                thinking={"type": "adaptive"},
                messages=messages,
            ) as stream:
                for event in stream:
                    if (event.type == "content_block_delta"
                            and event.delta.type == "text_delta"):
                        yield {"type": "text", "text": event.delta.text}
                reply = stream.get_final_message()
        except anthropic.RateLimitError:
            yield {"type": "error", "message": "Rate limited by the API — try again shortly."}
            return
        except anthropic.APIStatusError as exc:
            logger.warning("assistant API error %s: %s", exc.status_code, exc)
            yield {"type": "error", "message": f"API error {exc.status_code}."}
            return
        except anthropic.APIConnectionError:
            yield {"type": "error", "message": "Could not reach the API."}
            return

        total_in += reply.usage.input_tokens
        total_out += reply.usage.output_tokens

        if reply.stop_reason != "tool_use":
            yield {"type": "usage", "input": total_in, "output": total_out,
                   "cost": round(total_in / 1e6 * 5 + total_out / 1e6 * 25, 4)}
            yield {"type": "done"}
            return

        messages.append({"role": "assistant", "content": reply.content})
        results = []
        for block in reply.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool", "name": block.name}
            handler = HANDLERS.get(block.name)
            try:
                out = handler(block.input) if handler else {"error": "unknown tool"}
            except Exception as exc:  # noqa: BLE001 — a tool fault must not kill the chat
                logger.exception("assistant tool %s failed", block.name)
                out = {"error": f"{type(exc).__name__}: {exc}"}
            results.append({
                "type": "tool_result", "tool_use_id": block.id,
                "content": json.dumps(out, default=str)[:120_000],
            })
        # All results go back in ONE user message — splitting them teaches the
        # model to stop calling tools in parallel.
        messages.append({"role": "user", "content": results})

    yield {"type": "error",
           "message": f"Stopped after {MAX_TURNS} tool rounds without settling on an answer."}
