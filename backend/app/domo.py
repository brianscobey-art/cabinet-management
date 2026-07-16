"""Server-side Domo pull for the Job Cost P&L (needs a Domo access token).

A Domo access token (Admin > Authentication > Access tokens, tied to a user's
PDP scope) lets the server call the same private instance APIs the browser
used — so the report's Update button can pull live with no browser session.

Set DOMO_ACCESS_TOKEN in backend/.env. Without it, refresh falls back to the
latest KB Job Costs*.json export file.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.jobcosts import import_rows
from app.models import Job

K_AND_B_LABOR_CODE = "C9009"


def token_configured() -> bool:
    return bool(get_settings().domo_access_token.strip())


def _domo_sql(sql: str) -> list[list]:
    s = get_settings()
    url = f"https://{s.domo_instance}/api/query/v1/execute/{s.domo_dataset_id}"
    req = urllib.request.Request(
        url,
        data=json.dumps({"sql": sql}).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-DOMO-Developer-Token": s.domo_access_token.strip(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data.get("rows", [])


def _prefix(job_field) -> str:
    return str(job_field).split(":")[0].strip()


def _is_labor(sku: str) -> bool:
    return sku.upper().startswith("C90")  # installed-sales labor family (C90xx)


def combine_domo_rows(db: Session, all_rows: list) -> list[dict]:
    """Turn raw Domo [job, sku, sales, cost] rows into per-house cost dicts.

    A house's dollars live on its I-code while active and are rebilled to its
    G-code once complete, so BOTH codes are combined per house. Within each code,
    product is the non-C90xx SKUs and labor is the C90xx SKUs (C9009 = K&B install
    labor; other C90xx net folds in / washes out downstream).
    """
    # code prefix -> {"prod": {sales, cost}, "labor": {sku: {sales, cost}}}
    by_code: dict[str, dict] = {}
    for r in all_rows:
        code = _prefix(r[0])
        sku = _prefix(r[1])
        sales, cost = r[2] or 0, r[3] or 0
        slot = by_code.setdefault(code, {"prod": {"sales": 0.0, "cost": 0.0}, "labor": {}})
        if _is_labor(sku):
            s = slot["labor"].setdefault(sku.upper(), {"sales": 0.0, "cost": 0.0})
            s["sales"] += sales
            s["cost"] += cost
        else:
            slot["prod"]["sales"] += sales
            slot["prod"]["cost"] += cost

    rows = []
    for job in db.query(Job).filter((Job.g_code.isnot(None)) | (Job.i_code.isnot(None))).all():
        prod = {"sales": 0.0, "cost": 0.0}
        labor: dict[str, dict] = {}
        seen = False
        for code in (job.g_code, job.i_code):  # combine active (I) + rebilled/complete (G)
            b = by_code.get(code) if code else None
            if not b:
                continue
            seen = True
            prod["sales"] += b["prod"]["sales"]
            prod["cost"] += b["prod"]["cost"]
            for sku, v in b["labor"].items():
                s = labor.setdefault(sku, {"sales": 0.0, "cost": 0.0})
                s["sales"] += v["sales"]
                s["cost"] += v["cost"]
        if not seen:
            continue
        c9009 = labor.get(K_AND_B_LABOR_CODE, {"sales": 0, "cost": 0})
        others = {
            sku: round(v["sales"] - v["cost"], 2)
            for sku, v in labor.items()
            if sku != K_AND_B_LABOR_CODE
        }
        rows.append({
            "job_code": job.job_code,
            "g_code": job.g_code,
            "i_code": job.i_code,
            "revenue": round(prod["sales"], 2),
            "product_cost": round(prod["cost"], 2),
            "labor_revenue": round(c9009["sales"], 2),
            "labor_cost": round(c9009["cost"], 2),
            "labor_codes": others,
        })
    return rows


def pull_and_import(db: Session) -> dict:
    """Live-pull Domo actuals (needs a token) and import as job costs."""
    if not token_configured():
        return {"error": "no DOMO_ACCESS_TOKEN configured"}
    try:
        # Installed-sales job codes are whole-house (all trades), so restrict product to
        # the Kitchen and Bath category; labor is the C90xx SKUs (C9009 = K&B install).
        all_rows = _domo_sql(
            "SELECT SUBSTRING_INDEX(`job`,':',1) AS job, `sku` AS sku, "
            "SUM(`sales`) AS sales, SUM(`cost`) AS cost FROM table "
            "WHERE (`job` LIKE 'G%' OR `job` LIKE 'I%') "
            "AND (`product category` = 'Kitchen and Bath' OR `sku` LIKE 'C90%') "
            "GROUP BY SUBSTRING_INDEX(`job`,':',1), `sku`"
        )
    except urllib.error.HTTPError as e:
        return {"error": f"Domo returned {e.code} — token invalid or expired?"}
    except urllib.error.URLError as e:
        return {"error": f"could not reach Domo: {e.reason}"}
    rows = combine_domo_rows(db, all_rows)
    return {"source": "Domo live pull", **import_rows(db, rows, source="Domo live pull")}


def latest_raw_export(directory: Path) -> Path | None:
    files = [f for f in directory.glob("KB Domo Raw*.json") if not f.name.startswith("~")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def import_raw_file(db: Session) -> dict:
    """Import the newest raw Domo dump (KB Domo Raw*.json: job/sku/sales/cost rows),
    combining each house's G-code and I-code."""
    directory = Path(get_settings().domo_export_dir)
    f = latest_raw_export(directory)
    if f is None:
        return {"error": "no 'KB Domo Raw*.json' export found — run the Domo cost pull first"}
    data = json.loads(f.read_text(encoding="utf-8"))
    raw = data.get("rows", data) if isinstance(data, dict) else data
    all_rows = [
        (r["job"], r["sku"], r.get("sales"), r.get("cost")) if isinstance(r, dict) else r
        for r in raw
    ]
    rows = combine_domo_rows(db, all_rows)
    return {"file": f.name, **import_rows(db, rows, source=f.name)}
