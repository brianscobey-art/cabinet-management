"""DOMO feeds through Brian's own signed-in Chrome (Brian 11/3/26: "do the DOMO
Chrome pull every morning"). The Playwright pull (pull_domo_receipts.py) keeps
losing its DOMO session; Brian's everyday Chrome stays signed in. A scheduled
Claude task drives it every morning:

    python scripts/domo_chrome_pull.py js      -> JavaScript to run in a
        carterlumber.domo.com tab (Claude-in-Chrome javascript_tool). It runs
        the same four queries the nightly pull does and downloads each result
        to Downloads under the name the uploader / cloud importers expect.
        Feeds already written today are left out (Chrome would save a "(1)" copy).
        The work runs in the background; poll window.__ctPull until done.
    python scripts/domo_chrome_pull.py check   -> which of today's files are in
        Downloads; writes ai-health/domo_chrome_pull.json. Exit 0 = all four.

The SQL, columns and dataset ids are imported from the app, so this never
drifts from what the nightly pull and the importers use.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.domo_pos import COLS as PO_COLS, PO_SQL  # noqa: E402
from app.final_bill import BILLING_SQL, COLS as BILL_COLS  # noqa: E402
from app.job_accounts import ACCOUNTS_SQL, COLS as ACCT_COLS  # noqa: E402
from app.po_receipts import COLS as RECEIPT_COLS, _RECEIPT_SQL  # noqa: E402

STATUS = BACKEND.parents[1] / "ai-health" / "domo_chrome_pull.json"


def feeds(day: dt.date) -> list[tuple[str, str, str, list[str]]]:
    s = get_settings()
    stamp = f"{day:%m%d%y}"
    return [
        (f"PO Receipt List {stamp}.csv", s.po_receipt_dataset_id.strip(), _RECEIPT_SQL, RECEIPT_COLS),
        (f"DOMO CAB Accounts {stamp}.csv", s.domo_accounts_dataset_id.strip(), ACCOUNTS_SQL, ACCT_COLS),
        (f"DOMO Job POs {stamp}.csv", s.domo_po_dataset_id.strip(), PO_SQL, PO_COLS),
        (f"DOMO Job Billing {stamp}.csv", s.domo_dataset_id.strip(), BILLING_SQL, BILL_COLS),
    ]


def folder() -> Path:
    return Path(get_settings().po_receipt_folder)


JS = r"""
window.__ctPull = {done: false, results: []};
(async () => {
  const feeds = __FEEDS__;
  const cell = v => { if (v === null || v === undefined) return ''; const s = String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const csv = (cols, rows) => [cols, ...rows].map(r => r.map(cell).join(',')).join('\r\n') + '\r\n';
  for (const [name, ds, sql, cols] of feeds) {
    try {
      const r = await fetch(`/api/query/v1/execute/${ds}`, {method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, body: JSON.stringify({sql})});
      if (r.status !== 200) { window.__ctPull.results.push(`${name}: DOMO ${r.status} - skipped`); continue; }
      const rows = (await r.json()).rows || [];
      if (!rows.length) { window.__ctPull.results.push(`${name}: 0 rows - skipped`); continue; }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([csv(cols, rows)], {type: 'text/csv'}));
      a.download = name; document.body.appendChild(a); a.click(); a.remove();
      window.__ctPull.results.push(`${name}: ${rows.length} rows`);
      await new Promise(res => setTimeout(res, 1500));
    } catch (e) { window.__ctPull.results.push(`${name}: error ${e.message}`); }
  }
  window.__ctPull.done = true;
})();
'started: ' + __COUNT__ + ' feed(s)';
"""


def build_js(day: dt.date) -> str | None:
    todo = [[n, ds, sql, cols] for n, ds, sql, cols in feeds(day) if not (folder() / n).exists()]
    if not todo:
        return None
    return JS.replace("__FEEDS__", json.dumps(todo)).replace("__COUNT__", str(len(todo))).strip()


def check(day: dt.date) -> int:
    out = {"at": dt.datetime.now().isoformat(timespec="seconds"), "files": {}}
    ok = True
    for name, *_ in feeds(day):
        f = folder() / name
        if f.exists():
            with f.open(encoding="utf-8-sig") as fh:
                rows = sum(1 for _ in fh) - 1
            out["files"][name] = f"{rows} rows"
        else:
            out["files"][name] = "missing"
            ok = False
    out["state"] = "ok" if ok else "incomplete"
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if ok else 1


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    today = dt.date.today()
    if cmd == "js":
        js = build_js(today)
        print(js if js else "NOTHING TO DO: all four of today's DOMO files are already in Downloads")
    elif cmd == "check":
        sys.exit(check(today))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
