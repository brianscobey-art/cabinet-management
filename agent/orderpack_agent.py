"""Order Pack agent — the piece that runs on Brian's PC.

The board and the run buttons live in the cloud (cabinettron.com), but only this
machine can see the OneDrive folders, the desktop Outlook, and the logged-in
VendorSuite Chrome session. So the cloud never reaches down here: this agent
reaches UP. It polls for queued runs, does the local work, and reports back.

Two duties:

  1. SCAN — walk "Sold Jobs\\New Orders" and report which job folder sits in
     which stage folder, with a file inventory. A job folder's position in the
     chain IS its status, so this is what makes the board tell the truth.
     Runs on a timer (ORDERPACK_SCAN_MINUTES) and on demand.

  2. RUNS — claim queued commands and execute them. "scan" and "stage4" are
     built; stages 1-3 land in the later phases. Each stage is a module here,
     and the SERVER stamps Optimus off the structured result the module
     returns — the agent never writes a checkbox itself.

Auth is a shared secret in the X-Pack-Key header (same idea as the wallpaper
feed key). No credentials for anything else are stored or requested — in
particular VendorSuite SSO stays manual by design.

Run it:            python agent\\orderpack_agent.py
Run it hidden:     start_orderpack_agent.bat      (pythonw, no console window)
Run one scan:      python agent\\orderpack_agent.py --once
Stop a hidden one: create a file named orderpack_agent.stop next to this script.

Log: agent\\orderpack_agent.log
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AGENT_VERSION = "phaseB-1"

ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "orderpack_agent.log"
STOP_FILE = ROOT / "orderpack_agent.stop"

# ---------------------------------------------------------------------------
# Settings. Env vars win; backend\.env is read as a fallback so the agent and
# the local backend share one place to configure things.
# ---------------------------------------------------------------------------
DEFAULTS = {
    # MUST be the canonical host. cabinettron.com 301-redirects to www, and
    # urllib quietly turns a POST into a GET when it follows a 301 — so a scan
    # posted at the bare domain would report nothing and look like it worked.
    "ORDERPACK_API_BASE": "https://www.cabinettron.com",
    "ORDERPACK_AGENT_KEY": "ckb-pack-9f3a71c4e08b",
    "NEW_ORDERS_DIR": r"C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Shared File"
                      r"\Sold Jobs\New Orders",
    "ORDERPACK_SCAN_MINUTES": "15",
    "ORDERPACK_POLL_SECONDS": "20",
}


def _load_env() -> dict:
    values = dict(DEFAULTS)
    env_file = ROOT.parent / "backend" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip().upper()
            if key in values:
                values[key] = val.strip().strip('"').strip("'")
    for key in values:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


CFG = _load_env()
API_BASE = CFG["ORDERPACK_API_BASE"].rstrip("/") + "/api/ordering-platform/pack"
AGENT_KEY = CFG["ORDERPACK_AGENT_KEY"]
NEW_ORDERS = Path(CFG["NEW_ORDERS_DIR"])
SCAN_MINUTES = int(CFG["ORDERPACK_SCAN_MINUTES"] or 15)
POLL_SECONDS = int(CFG["ORDERPACK_POLL_SECONDS"] or 20)

# The four stage folders, in order, plus Century (a flat folder of job folders).
BUCKETS = [
    ("stage1", "1. POs and Selections"),
    ("stage2", "2. Orders and Layouts"),
    ("stage3", "3. SOs and Order Comparison"),
    ("stage4", "4. POs attached"),
    ("century", "Century Orders"),
]
# Housekeeping folders that are not jobs.
SKIP_DIRS = {"archive", "_to_delete", "_to_delete_duplicate_orders", "forms", "templates"}
LOOSE_EXTS = {".pdf", ".xlsx", ".eml"}   # staged Carter POs, SOs, comparison summaries


def log(msg: str) -> None:
    line = f"{datetime.now():%m/%d/%y %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects.

    urllib's default handler rewrites a redirected POST into a GET. Pointed at
    the wrong host that turns every scan into a silent no-op that still looks
    like a success. A misconfigured ORDERPACK_API_BASE must fail loudly.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError(
            f"server redirected {req.get_method()} {req.full_url} -> {newurl}. "
            f"Set ORDERPACK_API_BASE to the canonical host (https://www.cabinettron.com)."
        )


_OPENER = urllib.request.build_opener(_NoRedirects)


def call(path: str, payload=None, method: str | None = None, timeout: int = 60):
    url = API_BASE + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("X-Pack-Key", AGENT_KEY)
    if data:
        req.add_header("Content-Type", "application/json")
    with _OPENER.open(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


# ---------------------------------------------------------------------------
# Duty 1: scan the folder chain
# ---------------------------------------------------------------------------
def scan_folders() -> dict:
    """Walk the New Orders tree and describe what is physically there."""
    stages: dict[str, list] = {}
    loose: dict[str, list] = {}

    if not NEW_ORDERS.is_dir():
        raise RuntimeError(f"New Orders folder not found: {NEW_ORDERS}")

    for key, folder_name in BUCKETS:
        base = NEW_ORDERS / folder_name
        stages[key] = []
        loose[key] = []
        if not base.is_dir():
            log(f"  ! {folder_name} is missing - skipped")
            continue
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            log(f"  ! can't read {folder_name}: {exc}")
            continue
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name.startswith("~$"):
                continue
            if entry.is_dir():
                if name.lower() in SKIP_DIRS or name.lower().startswith("_to_delete"):
                    continue
                try:
                    files = sorted(f.name for f in entry.iterdir() if f.is_file()
                                   and not f.name.startswith("~$"))
                except OSError as exc:
                    log(f"  ! can't read {name}: {exc}")
                    files = []
                stages[key].append({"folder": name, "files": files})
            elif entry.is_file() and entry.suffix.lower() in LOOSE_EXTS:
                loose[key].append(name)

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "agent_version": AGENT_VERSION,
        "stages": stages,
        "loose_files": loose,
    }


def do_scan(run_id: int | None = None) -> dict:
    payload = scan_folders()
    for key, folder_name in BUCKETS:
        n = len(payload["stages"].get(key, []))
        extra = len(payload["loose_files"].get(key, []))
        line = f"{folder_name}: {n} job folder{'' if n == 1 else 's'}" + \
               (f", {extra} loose file{'' if extra == 1 else 's'}" if extra else "")
        log("  " + line)
        if run_id:
            send_log(run_id, line)
    summary = call("/agent/scan", payload)
    msg = (f"reported {summary.get('matched', 0)} matched, "
           f"{len(summary.get('unmatched') or [])} unmatched, "
           f"{summary.get('left_the_chain', 0)} left the chain")
    log("  " + msg)
    if run_id:
        send_log(run_id, msg)
    return summary


# ---------------------------------------------------------------------------
# Duty 2: execute queued runs
# ---------------------------------------------------------------------------
def send_log(run_id: int, line: str) -> None:
    try:
        call(f"/agent/runs/{run_id}/log", {"line": line})
    except Exception:
        pass  # never let logging kill a run


def finish(run_id: int, status: str, result=None, error: str | None = None) -> None:
    try:
        call(f"/agent/runs/{run_id}/finish",
             {"status": status, "result": result, "error": error})
    except Exception as exc:
        log(f"  ! couldn't report the finish of run {run_id}: {exc}")


def do_stage4(run_id: int) -> dict:
    """Stage 4 — pull the Carter POs, verify the totals, file what passes.

    The results go to the server, which is what stamps Optimus. The agent never
    writes checkboxes itself: one set of records, one place they change.
    """
    if str(ROOT) not in sys.path:      # so the import works whatever the cwd is
        sys.path.insert(0, str(ROOT))
    import stage4_pos

    def emit(line: str) -> None:
        log("  " + line)
        send_log(run_id, line)

    results = stage4_pos.run(NEW_ORDERS, emit)
    if results:
        applied = call("/agent/stage4/apply", {"run_id": run_id, "results": results})
        emit(f"board updated: {applied.get('updated', 0)} job(s), "
             f"{applied.get('flagged', 0)} flagged, "
             f"{applied.get('unmatched', 0)} with no job record")
    # A stage 4 run changes what's on disk, so re-scan before reporting done.
    do_scan(run_id)
    return {"results": results}


def execute(run: dict) -> None:
    run_id, kind = run["id"], run["kind"]
    log(f"run {run_id}: {kind} - starting")
    send_log(run_id, f"agent {AGENT_VERSION} picked this up on {socket.gethostname()}")
    try:
        if kind == "scan":
            summary = do_scan(run_id)
            finish(run_id, "done", result=summary)
            log(f"run {run_id}: done")
        elif kind == "stage4":
            outcome = do_stage4(run_id)
            finish(run_id, "done", result=outcome)
            log(f"run {run_id}: done")
        else:
            # Stage execution arrives in the later phases (stage 4 first).
            # Fail loudly rather than leaving a run stuck in "running".
            msg = f"'{kind}' isn't built into this agent yet (agent {AGENT_VERSION})"
            send_log(run_id, msg)
            finish(run_id, "failed", error=msg)
            log(f"run {run_id}: {msg}")
    except Exception as exc:
        send_log(run_id, f"ERROR: {exc}")
        finish(run_id, "failed", error=str(exc))
        log(f"run {run_id}: FAILED - {exc}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Order Pack on-prem agent")
    parser.add_argument("--once", action="store_true", help="run one scan and exit")
    args = parser.parse_args()

    log(f"Order Pack agent {AGENT_VERSION}")
    log(f"  api    : {API_BASE}")
    log(f"  folders: {NEW_ORDERS}")

    if args.once:
        do_scan()
        return

    # Single-instance lock: a second copy (logon task fired twice) exits quietly.
    try:
        lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock.bind(("127.0.0.1", 8791))
        lock.listen(1)
    except OSError:
        log("another agent is already running - exiting")
        return

    log(f"  polling every {POLL_SECONDS}s, scanning every {SCAN_MINUTES} min")
    next_scan = 0.0
    failures = 0

    while True:
        if STOP_FILE.exists():
            STOP_FILE.unlink(missing_ok=True)
            log("orderpack_agent.stop found - shutting down")
            return
        try:
            run = call("/agent/runs/next")
            if run:
                execute(run)
                failures = 0
                continue  # straight back for the next queued run
            if SCAN_MINUTES > 0 and time.time() >= next_scan:
                log("timed scan")
                do_scan()
                next_scan = time.time() + SCAN_MINUTES * 60
            failures = 0
        except urllib.error.HTTPError as exc:
            failures += 1
            detail = exc.read().decode("utf-8", "ignore")[:200]
            log(f"HTTP {exc.code} from the server: {detail}")
            if exc.code == 403:
                log("  the agent key is wrong - set ORDERPACK_AGENT_KEY to match the server")
        except Exception as exc:
            failures += 1
            log(f"poll failed: {exc}")
        # Back off on a run of failures so a dropped connection doesn't spin.
        time.sleep(POLL_SECONDS * (4 if failures > 5 else 1))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("agent stopped by user")
        sys.exit(0)
