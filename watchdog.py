"""CabinetTron watchdog — keeps the backend running on port 8000.

Polls http://localhost:8000/health every CHECK_SECONDS. If the app is down
(or its process died), starts it with the backend venv's uvicorn. If something
else is already serving /health (e.g. a dev session), the watchdog leaves it
alone and just keeps watching.

Run it:                python watchdog.py          (console window, Ctrl+C to stop)
Run it hidden:         start_watchdog.bat          (uses pythonw, no window)
Stop a hidden one:     create a file named watchdog.stop next to this script
                       (checked every poll), or end the pythonw.exe task.

Log: watchdog.log next to this script. Repeated crash-starts back off
(10s -> 60s -> 5min) so a broken app doesn't spin the CPU.
"""

import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
VENV_PY = BACKEND / ".venv" / "Scripts" / "python.exe"
HEALTH_URL = "http://localhost:8000/health"
CHECK_SECONDS = 30
BOOT_WAIT_SECONDS = 25          # how long the app gets to come up after a start
LOG_FILE = ROOT / "watchdog.log"
STOP_FILE = ROOT / "watchdog.stop"
APP_LOG = ROOT / "app-server.log"  # uvicorn output lands here

# Crash-loop backoff: after each failed start, wait longer before the next try.
BACKOFF_STEPS = [10, 60, 300]

proc: subprocess.Popen | None = None
app_log_handle = None


def log(msg: str) -> None:
    line = f"{datetime.now():%m/%d/%y %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_app() -> None:
    global proc, app_log_handle
    if app_log_handle:
        app_log_handle.close()
    app_log_handle = open(APP_LOG, "a", encoding="utf-8")
    app_log_handle.write(f"\n----- watchdog start {datetime.now():%m/%d/%y %H:%M:%S} -----\n")
    app_log_handle.flush()
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "app.main:app", "--port", "8000"],
        cwd=str(BACKEND),
        stdout=app_log_handle,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    log(f"started app (pid {proc.pid}); waiting for it to come up…")


def main() -> None:
    # Single-instance lock: hold a localhost port for the watchdog's lifetime.
    # A second copy (e.g. logon task while one is already running) exits quietly.
    try:
        lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock.bind(("127.0.0.1", 8790))
        lock.listen(1)
    except OSError:
        log("another watchdog is already running — exiting")
        return

    log(f"watchdog running — checking {HEALTH_URL} every {CHECK_SECONDS}s")
    if not VENV_PY.exists():
        log(f"FATAL: venv python not found at {VENV_PY}")
        sys.exit(1)
    failures = 0

    while True:
        if STOP_FILE.exists():
            STOP_FILE.unlink(missing_ok=True)
            log("watchdog.stop found — shutting down watchdog (app left as-is)")
            return

        if healthy():
            if failures:
                log("app is healthy again")
            failures = 0
            time.sleep(CHECK_SECONDS)
            continue

        # Unhealthy. If we own a process that has exited, note why.
        if proc is not None and proc.poll() is not None:
            log(f"app process exited with code {proc.returncode}")

        log("app is DOWN — restarting")
        start_app()

        # Give it time to boot, checking as we go.
        deadline = time.time() + BOOT_WAIT_SECONDS
        while time.time() < deadline:
            time.sleep(2)
            if healthy():
                break
        if healthy():
            log("app is up")
            failures = 0
        else:
            backoff = BACKOFF_STEPS[min(failures, len(BACKOFF_STEPS) - 1)]
            failures += 1
            log(f"app failed to come up (attempt {failures}) — retrying in {backoff}s; check {APP_LOG.name}")
            time.sleep(backoff)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("watchdog stopped by user (app left running)")
