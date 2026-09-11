"""Pull DOMO's "PO Receipt List" through Brian's signed-in browser profile.

WHY THIS EXISTS. Carter will not issue Brian a DOMO developer token, so the
server-side pull in app.po_receipts can never run. DOMO's query API does accept
an ordinary logged-in session, which is how scripts/domo_receipt_pull.js works
-- but that needs Brian at DevTools clicking a button. This does the same call
from a Chromium profile that stays signed in, so Task Scheduler can run it at
02:30 with nobody at the keyboard.

    --login   opens a visible browser on carterlumber.domo.com and waits for
              Brian to sign in (SSO / MFA are HIS to complete -- this script
              never types a credential). Run once; the profile keeps the session.
    (no flag) headless: run the query, write the CSV, exit.

The CSV lands in settings.po_receipt_folder (Downloads) under the exact name
and 7 columns po_receipts expects. From there nothing else is new: the
"CarterKB R2 Upload" task ships it every 5 minutes and cabinettron.com's
5-minute poll imports it, so the PO tracker's "Received?" moves on its own.

A status file beside the AI Health Check records every run. "signed-out" is
the state to watch for: SSO sessions expire, and when they do the pull cannot
help -- Brian has to run --login again.

Exit codes: 0 pulled, 2 not signed in, 1 anything else.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.po_receipts import COLS, _RECEIPT_SQL  # noqa: E402  (one SQL, one column list)

DOMO = "https://carterlumber.domo.com"
# Durable, outside the repo and outside Downloads (which gets swept).
PROFILE = BACKEND.parents[1] / "domo-profile"
STATUS = BACKEND.parents[1] / "ai-health" / "domo_receipts.json"
LOGIN_WAIT_S = 600

# Drawn onto whatever page the login window is showing, and re-drawn after
# every SSO redirect. The first hand-off failed because Brian signed in to his
# everyday Chrome instead: this window is a separate profile, plain Chromium,
# and nothing on screen said so.
_BANNER_JS = """
(() => {
  document.getElementById('__ckb_banner')?.remove();
  const d = document.createElement('div');
  d.id = '__ckb_banner';
  d.textContent = 'SIGN IN TO DOMO IN THIS WINDOW - CabinetTron receipt pull. '
                + 'It closes by itself once the session works.';
  d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;'
    + 'background:#125952;color:#fff;font:bold 18px/1.4 sans-serif;'
    + 'padding:14px 20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.4)';
  document.body?.appendChild(d);
})();
"""


def write_status(state: str, **extra) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "at": dt.datetime.now().isoformat(timespec="seconds"), **extra}
    STATUS.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def query(context, dataset_id: str):
    """The same SQL po_receipts uses, through the profile's cookies.
    Returns (rows, http_status)."""
    r = context.request.post(
        f"{DOMO}/api/query/v1/execute/{dataset_id}",
        data=json.dumps({"sql": _RECEIPT_SQL}),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=120_000,
    )
    if r.status != 200:
        return None, r.status
    return r.json().get("rows", []), 200


def save_csv(rows, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    name = f"PO Receipt List {dt.date.today():%m%d%y}.csv"
    out = folder / name
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        w.writerows(rows)
    return out


def max_receipt_date(rows) -> str | None:
    i = COLS.index("Receipt Date")
    dates = [str(r[i])[:10] for r in rows if r[i]]
    return max(dates) if dates else None


def run(login: bool, headed: bool, wait_s: int = LOGIN_WAIT_S) -> int:
    from playwright.sync_api import sync_playwright

    s = get_settings()
    ds = s.po_receipt_dataset_id.strip()
    folder = Path(s.po_receipt_folder)
    PROFILE.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), headless=not (login or headed),
            viewport={"width": 1280, "height": 900},
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(DOMO, wait_until="domcontentloaded", timeout=60_000)

            if login:
                print("Sign in to DOMO in the browser window (SSO/MFA are yours to do).")
                print(f"Waiting up to {wait_s // 60} minutes for the session...")
                deadline = time.time() + wait_s
                while time.time() < deadline:
                    # The banner races SSO redirects: evaluate() on a page that
                    # is mid-navigation throws "execution context destroyed",
                    # and that happened at the exact moment the sign-in landed.
                    # A missing banner for one 5-second tick is nothing; a
                    # crashed login window is the whole hand-off lost.
                    for pg in ctx.pages:
                        try:
                            pg.evaluate(_BANNER_JS)
                        except Exception:  # noqa: BLE001
                            pass
                    try:
                        rows, status = query(ctx, ds)
                    except Exception as exc:  # noqa: BLE001
                        # The window was closed before the session verified.
                        # Not an error in the code -- an abandoned sign-in.
                        if "closed" in str(exc).lower():
                            print("Window closed before sign-in completed.")
                            write_status("signed-out", note="login window closed")
                            return 2
                        raise
                    if status == 200:
                        print(f"Signed in. Query works: {len(rows)} receipts. Profile saved.")
                        write_status("ok", rows=len(rows), note="login verified")
                        return 0
                    time.sleep(5)
                print("Timed out waiting for sign-in.")
                write_status("signed-out", note="login timed out")
                return 2

            rows, status = query(ctx, ds)
            if status != 200:
                print(f"DOMO returned {status}: not signed in. Run with --login.")
                write_status("signed-out", http=status)
                return 2
            out = save_csv(rows, folder)
            as_of = max_receipt_date(rows)
            print(f"{len(rows)} receipts -> {out.name}  (latest receipt {as_of})")
            write_status("ok", rows=len(rows), max_receipt_date=as_of, file=str(out))
            return 0
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001 — already gone
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--login", action="store_true", help="open a window and wait for Brian to sign in")
    ap.add_argument("--headed", action="store_true", help="run the pull with a visible window")
    ap.add_argument("--wait", type=int, default=LOGIN_WAIT_S // 60,
                    help="minutes to wait for sign-in with --login (default 10)")
    a = ap.parse_args()
    try:
        sys.exit(run(a.login, a.headed, a.wait * 60))
    except Exception as exc:  # noqa: BLE001 — the status file is how failures get seen
        write_status("error", error=f"{type(exc).__name__}: {exc}"[:300])
        print(f"error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
