"""Load a day's data into the TEST site and run the Account Code check (11/24/26).

  python scripts/code_check_push.py --jobs JOBS.csv --accounts ACCOUNTS.csv --setups SETUPS.csv [--out OUT.json]

JOBS.csv: Job Code, Builder, KSR, I-Code, G-Code, Ashley's Code (a tracker
snapshot -- the test site has no copy of live's jobs). ACCOUNTS.csv: the
Job Account feed ("DOMO CAB Accounts" / "Job Account" column). SETUPS.csv:
"Job Setup Requests MMDDYY.csv". Test site only: the jobs-snapshot feed is
refused by the live site.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TOKEN_FILE = BACKEND.parents[1] / "po-lines" / "test_ingest_token.txt"
BASE = "https://cabinettron-test-vjcp.onrender.com"


def post(path: str, body: bytes | None, token: str) -> dict:
    req = urllib.request.Request(f"{BASE}/api{path}", data=body or b"", method="POST",
                                 headers={"Content-Type": "text/csv", "X-Ingest-Token": token})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--accounts", required=True)
    ap.add_argument("--setups", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    out = {"jobs-snapshot": post("/feeds/ingest/jobs-snapshot", Path(a.jobs).read_bytes(), token),
           "job-accounts": post("/feeds/ingest/job-accounts", Path(a.accounts).read_bytes(), token),
           "setup-requests": post("/feeds/ingest/setup-requests", Path(a.setups).read_bytes(), token)}
    res = post("/feeds/code-check/run", None, token)
    out["summary"] = res["summary"]
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
