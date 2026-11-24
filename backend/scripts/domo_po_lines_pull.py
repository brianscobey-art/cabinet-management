"""PO Line Items pull through Brian's signed-in Chrome (Brian 11/24/26).

DOMO's PO drill-down card (584540536) can be exported but not put on a
scheduled report, and its export only works from a browser signed in with
Brian's SSO. A scheduled Claude task runs this each morning, after the DOMO
"CabinetTron feed" emails land:

  python scripts/domo_po_lines_pull.py js [--days 60] [--job CODE] [--pos A,B]
      -> JavaScript for a carterlumber.domo.com/page/700127389 tab. It exports
         the drill card for the chosen POs in batches of 200 and downloads one
         CSV, "DOMO PO Lines MMDDYY.csv", to Downloads. Default POs: the
         Purchase Orders feed's last 60 days plus every PO still open.
         --job / --pos pull just those (file name gets the code). Poll
         window.__ctLines until done; it holds the browser's own row count
         and cost totals.
  python scripts/domo_po_lines_pull.py check --rows N --items N --received X [--file F]
      -> re-reads the downloaded file and confirms it matches what the browser
         counted before anything is sent anywhere.
  python scripts/domo_po_lines_pull.py push --env test [--file F]
      -> posts the Purchase Orders feed, the I-Account Detail file and the PO
         lines to the TEST site's ingest endpoint and prints the checks.
         (Live reads the files from R2 through the uploader instead.)
  python scripts/domo_po_lines_pull.py skip --reason "..."
      -> Chrome or the DOMO session wasn't there: log it, no retry.

The drill card's results would only come back from the page ~1 KB at a time,
so the rows travel as a browser download and the counts/totals are compared
instead (step "check").
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.po_lines import parse  # noqa: E402

STATUS = BACKEND.parents[1] / "ai-health" / "domo_po_lines.json"
TOKEN_FILE = BACKEND.parents[1] / "po-lines" / "test_ingest_token.txt"
ENVS = {"test": "https://cabinettron-test-vjcp.onrender.com"}
CARD = 584540536
PAGE = "https://carterlumber.domo.com/page/700127389"
BATCH = 200


def folder() -> Path:
    return Path(get_settings().po_receipt_dir)


def newest(pattern: str) -> Path | None:
    files = sorted(folder().glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0] if files else None


def status(state: str, **extra) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({"state": state, "at": dt.datetime.now().isoformat(timespec="seconds"), **extra},
                                 indent=2, default=str), encoding="utf-8")


def pick_pos(days: int, job: str | None, pos: str | None) -> list[str]:
    if pos:
        return [p.strip() for p in pos.split(",") if p.strip()]
    src = newest("DOMO Job POs*.csv")
    if src is None:
        raise SystemExit("no DOMO Job POs file in Downloads -- the Purchase Orders feed hasn't landed")
    since = dt.date.today() - dt.timedelta(days=days)
    key = "".join(ch for ch in (job or "").upper() if ch.isalnum())
    out = []
    with src.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            po = (r.get("PO #") or "").strip()
            if not po:
                continue
            if key:
                acct = "".join(ch for ch in (r.get("Job Account") or "").upper() if ch.isalnum())
                if key in acct:
                    out.append(po)
                continue
            try:
                when = dt.date.fromisoformat((r.get("Order Date") or "")[:10])
            except ValueError:
                when = None
            if (when and when >= since) or (r.get("Status") or "").strip().lower() == "open":
                out.append(po)
    return sorted(set(out))


def file_name(job: str | None, pos: str | None) -> str:
    tag = f" {job.upper()}" if job else (" selected" if pos else "")
    return f"DOMO PO Lines {dt.date.today():%m%d%y}{tag}.csv"


JS = r"""
window.__ctLines = {done: false, batches: 0, rows: 0, items: 0, received: 0, ordered: 0, errors: []};
(async () => {
  const s = window.__ctLines, batches = __BATCHES__, name = __NAME__;
  // one CSV record -> fields (quotes, commas and doubled quotes inside quotes)
  const split = line => { const out = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) { const c = line[i];
      if (q) { if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
      else if (c === '"') q = true; else if (c === ',') { out.push(cur); cur = ''; } else cur += c; }
    out.push(cur); return out; };
  let header = null; const body = [];
  for (const values of batches) {
    try {
      const req = {queryOverrides: {filters: [{column: 'transaction number', operand: 'IN', values, dataType: 'string'}],
        dataControlContext: {filterGroupIds: []}}, watermark: 'false', mobile: false, showAnnotations: true,
        type: 'file', fileName: 'po_lines.csv', accept: 'text/csv'};
      const fd = new FormData(); fd.append('request', JSON.stringify(req));
      const r = await fetch('/api/content/v1/cards/__CARD__/export?parts=metadata', {method: 'POST', headers: {Accept: 'text/csv'}, body: fd});
      if (r.status !== 200) { s.errors.push(`batch ${s.batches + 1}: DOMO ${r.status}`); s.batches++; continue; }
      const lines = (await r.text()).replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim());
      if (!lines.length) { s.batches++; continue; }
      header = header || lines[0];
      for (const l of lines.slice(1)) {
        const f = split(l); body.push(l); s.rows++;
        const spec = f[6], ordered = Number(f[8]) || 0, recv = Number(f[10]) || 0;
        if (spec === '-' || spec === "'-") s.ordered += ordered; else { s.items++; s.received += recv; }
      }
      s.batches++;
    } catch (e) { s.errors.push(`batch ${s.batches + 1}: ${e.message}`); s.batches++; }
  }
  s.received = Math.round(s.received * 100) / 100; s.ordered = Math.round(s.ordered * 100) / 100;
  if (header && body.length) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([[header, ...body].join('\r\n') + '\r\n'], {type: 'text/csv'}));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  s.done = true;
})();
'started: __N__ PO(s) in __B__ batch(es) -> ' + __NAME__;
"""


def cmd_js(a) -> int:
    pos = pick_pos(a.days, a.job, a.pos)
    if not pos:
        print("NOTHING TO DO: no POs selected")
        return 0
    name = file_name(a.job, a.pos)
    if (folder() / name).exists():
        print(f"NOTHING TO DO: {name} is already in Downloads (Chrome would save a '(1)' copy)")
        return 0
    batches = [pos[i:i + BATCH] for i in range(0, len(pos), BATCH)]
    js = (JS.replace("__BATCHES__", json.dumps(batches)).replace("__NAME__", json.dumps(name))
            .replace("__CARD__", str(CARD)).replace("__N__", str(len(pos))).replace("__B__", str(len(batches))))
    print(f"// open {PAGE} -- {len(pos)} POs, {len(batches)} batch(es), file {name}")
    print(js.strip())
    return 0


def cmd_check(a) -> int:
    f = Path(a.file) if a.file else newest(f"DOMO PO Lines {dt.date.today():%m%d%y}*.csv")
    if f is None or not f.exists():
        status("missing", note="download not in Downloads yet")
        print("MISSING: the download hasn't landed")
        return 1
    rows = parse(f.read_text(encoding="utf-8-sig"))
    items = [r for r in rows if r["line_type"] == "item"]
    got = {"rows": len(rows), "items": len(items),
           "received": round(float(sum((r["received_cost"] or 0) for r in items)), 2)}
    want = {"rows": a.rows, "items": a.items, "received": round(a.received, 2)}
    ok = got == want
    status("ok" if ok else "mismatch", file=f.name, file_counts=got, browser_counts=want,
           pos=len({r["po_number"] for r in rows}))
    print(json.dumps({"ok": ok, "file": f.name, "file_counts": got, "browser_counts": want}, indent=2))
    return 0 if ok else 1


def _post(base: str, feed: str, path: Path, token: str) -> dict:
    req = urllib.request.Request(f"{base}/api/feeds/ingest/{feed}", data=path.read_bytes(), method="POST",
                                 headers={"Content-Type": "text/csv", "X-Ingest-Token": token})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def cmd_push(a) -> int:
    base = ENVS[a.env]
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    out = {}
    for feed, pattern in (("job-pos", "DOMO Job POs*.csv"), ("i-account-detail", "DOMO I-Account Detail*.csv")):
        f = newest(pattern)
        out[feed] = _post(base, feed, f, token) if f else "no file"
        if f:
            out[feed] = {"file": f.name, **{k: v for k, v in out[feed].items() if k != "unmatched_list"}}
    f = Path(a.file) if a.file else newest(f"DOMO PO Lines {dt.date.today():%m%d%y}*.csv")
    if f is None or not f.exists():
        print(json.dumps({**out, "po-lines": "no file"}, indent=2, default=str))
        return 1
    res = _post(base, "po-lines", f, token)
    c = res.pop("checks")
    out["po-lines"] = {"file": f.name, **res, "received_mismatch": len(c["received_mismatch"]),
                       "placeholder_pos": len(c["placeholder_pos"]), "posted_at_cost": len(c["posted_at_cost"])}
    out["checks"] = c
    status("pushed", env=a.env, result={k: v for k, v in out.items() if k != "checks"})
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_skip(a) -> int:
    status("skipped", reason=a.reason)
    print(f"skipped: {a.reason}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("js")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--job")
    p.add_argument("--pos")
    p = sub.add_parser("check")
    p.add_argument("--rows", type=int, required=True)
    p.add_argument("--items", type=int, required=True)
    p.add_argument("--received", type=float, required=True)
    p.add_argument("--file")
    p = sub.add_parser("push")
    p.add_argument("--env", choices=sorted(ENVS), default="test")
    p.add_argument("--file")
    p = sub.add_parser("skip")
    p.add_argument("--reason", required=True)
    a = ap.parse_args()
    return {"js": cmd_js, "check": cmd_check, "push": cmd_push, "skip": cmd_skip}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
