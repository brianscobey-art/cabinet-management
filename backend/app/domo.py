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


def pull_and_import(db: Session) -> dict:
    """Live-pull product + labor actuals from Domo and import as job costs."""
    if not token_configured():
        return {"error": "no DOMO_ACCESS_TOKEN configured"}
    try:
        prod_rows = _domo_sql(
            "SELECT `job`, SUM(`sales`) AS sales, SUM(`cost`) AS cost "
            "FROM table WHERE `job` LIKE 'G%' GROUP BY `job`"
        )
        labor_rows = _domo_sql(
            "SELECT `job`, `sku`, SUM(`sales`) AS sales, SUM(`cost`) AS cost "
            "FROM table WHERE `job` LIKE 'I%' AND `sku` LIKE 'C90%' GROUP BY `job`, `sku`"
        )
    except urllib.error.HTTPError as e:
        return {"error": f"Domo returned {e.code} — token invalid or expired?"}
    except urllib.error.URLError as e:
        return {"error": f"could not reach Domo: {e.reason}"}

    prod: dict[str, dict] = {}
    for r in prod_rows:
        c = _prefix(r[0])
        p = prod.setdefault(c, {"sales": 0.0, "cost": 0.0})
        p["sales"] += r[1] or 0
        p["cost"] += r[2] or 0

    labor: dict[str, dict] = {}
    for r in labor_rows:
        c = _prefix(r[0])
        sku = _prefix(r[1])
        L = labor.setdefault(c, {})
        s = L.setdefault(sku, {"sales": 0.0, "cost": 0.0})
        s["sales"] += r[2] or 0
        s["cost"] += r[3] or 0

    rows = []
    for job in db.query(Job).filter((Job.g_code.isnot(None)) | (Job.i_code.isnot(None))).all():
        p = prod.get(job.g_code) if job.g_code else None
        L = labor.get(job.i_code, {}) if job.i_code else {}
        if not p and not L:
            continue
        c9009 = L.get(K_AND_B_LABOR_CODE, {"sales": 0, "cost": 0})
        # net P&L (billed − cost) per non-C9009 code, so it can be folded into margin
        others = {
            sku: round(v["sales"] - v["cost"], 2)
            for sku, v in L.items()
            if sku != K_AND_B_LABOR_CODE
        }
        rows.append({
            "job_code": job.job_code,
            "g_code": job.g_code,
            "i_code": job.i_code,
            "revenue": round(p["sales"], 2) if p else 0,
            "product_cost": round(p["cost"], 2) if p else 0,
            "labor_revenue": round(c9009["sales"], 2),
            "labor_cost": round(c9009["cost"], 2),
            "labor_codes": others,
        })
    result = import_rows(db, rows, source="Domo live pull")
    return {"source": "Domo live pull", **result}
