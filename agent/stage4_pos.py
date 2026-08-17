"""Stage 4 — POs Attached. Runs on Brian's PC, driven by the Order Pack run queue.

This does NOT reimplement the stage. Two scripts already do this work and have
been doing it for months; they live next to the stage folders in OneDrive:

  Pull_Carter_POs_from_Outlook.py — pulls Carter PO attachments out of the
      Townsend inbox over Outlook COM. Run as its own process (COM wants one)
      and only when Outlook is actually open.
  Process_Carter_POs.py — reads each staged Carter PO, matches it to the job
      folder by SO number, verifies the totals, moves the folder to stage 4,
      files a copy into the community folder, and cleans up staging.

What this module adds is the part the scripts never had: structured results.
The scripts print prose to a log; the board needs numbers per job. So we call
their parsers to gather the facts first, then hand the actual file moves back
to `Process_Carter_POs.process_one()`.

THE DOLLAR GATE. The SO total must equal the Carter PO total exactly, or the
folder does not move. That check is enforced TWICE on purpose — once here, so
the mismatch can be reported with both numbers and the difference, and again
inside `process_one()`, which independently refuses to move a mismatch. A bug
in this file cannot let a mismatch through, because this file is not the thing
holding the gate shut.

Install pay is read off the installer pay sheet, never computed. If the number
can't be read, or lands outside a sane range, it comes back blank with a note.
"""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

# Install pay is a per-job labor amount. Anything outside this window means the
# PDF changed shape and we read the wrong number — report blank, never a guess.
PAY_MIN, PAY_MAX = 50.0, 5000.0

_PAY_RE = re.compile(r"INSTALL\s*PAY(.{0,400}?)\$\s?([\d,]+\.\d\d)", re.DOTALL | re.IGNORECASE)
_ICODE_RE = re.compile(r"(I\d{7}-\d+)")
_PO_NUM_RE = re.compile(r"(750\d{6})")
_JOBCODE_RE = re.compile(r"^([A-Z0-9]{2,7}-\d{3,4})\b")


# Folders that sit alongside the job folders and must never be mistaken for one.
_NOT_A_JOB = ("_to_delete", "archive", "forms", "templates")


def _safe_find_job_folder(so_dir: str, so: str) -> str | None:
    """The job folder in stage 3 whose SO file carries this SO number.

    Replaces the original script's version, which returned the FIRST directory
    containing a matching file — including `_to_delete`, where superseded copies
    of the very same SO live. On 8/17/26 that made SO46088 resolve to
    `_to_delete`; the caller then did `jobcode, abbrev = parts[0], parts[1]` on
    the name "_to_delete" (one token, outside its try block) and the whole batch
    died on an IndexError.

    Three rules: skip housekeeping folders, require a real job-code prefix, and
    refuse to guess when more than one folder matches.
    """
    matches = []
    for name in sorted(os.listdir(so_dir)):
        path = os.path.join(so_dir, name)
        if not os.path.isdir(path):
            continue
        low = name.lower()
        if low.startswith(_NOT_A_JOB):
            continue
        if not _JOBCODE_RE.match(name):
            continue
        try:
            entries = os.listdir(path)
        except OSError:
            continue
        if any(so.lower() in f.lower() and f.lower().endswith(".pdf") for f in entries):
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def _load_processor(new_orders_dir: Path):
    """Import Process_Carter_POs.py from the OneDrive folder it lives in, and
    point its module-level paths at our configured New Orders root."""
    script = new_orders_dir / "Process_Carter_POs.py"
    if not script.exists():
        raise RuntimeError(f"Process_Carter_POs.py not found at {script}")
    spec = importlib.util.spec_from_file_location("process_carter_pos", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # The script hardcodes its own BASE. Keep it consistent with the agent's
    # config so both halves are always looking at the same folders.
    mod.BASE = str(new_orders_dir)
    mod.SO_DIR = str(new_orders_dir / "3. SOs and Order Comparison")
    mod.STG = str(new_orders_dir / "4. POs attached")
    mod.LOG_PATH = str(new_orders_dir / "Process_Carter_POs_log.txt")
    # Patch the module attribute, not just our own calls: process_one() looks
    # this up as a module global, so the fix protects the file moves too.
    mod.find_job_folder = lambda so, _d=mod.SO_DIR: _safe_find_job_folder(_d, so)
    return mod


def _outlook_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return "OUTLOOK.EXE" in (out.stdout or "")
    except Exception:
        return False


def pull_from_outlook(new_orders_dir: Path, emit) -> bool:
    """Run the existing Outlook pull. Returns True if it ran.

    Outlook COM only works against a running, signed-in Outlook. If it isn't
    open we say so and carry on — the playbook's own rule is that whatever is
    already staged in "4. POs attached" still gets processed.
    """
    script = new_orders_dir / "Pull_Carter_POs_from_Outlook.py"
    if not script.exists():
        emit(f"! {script.name} not found — skipping the Outlook pull")
        return False
    if not _outlook_running():
        emit("Outlook isn't running, so there's no mailbox to read. "
             "Processing whatever is already staged.")
        return False

    emit("Pulling Carter POs from Outlook…")
    proc = subprocess.run(
        [sys.executable, "-u", str(script)],
        cwd=str(new_orders_dir), capture_output=True, text=True, timeout=900,
        check=False,   # a non-zero exit is reported, not raised
    )
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line and not line.startswith("="):
            emit("  " + line)
    if proc.returncode != 0:
        emit(f"! the Outlook pull exited {proc.returncode}")
        for line in (proc.stderr or "").splitlines()[-5:]:
            emit("  " + line.strip())
    return proc.returncode == 0


def read_pay_sheet(folder: Path) -> tuple[bool, float | None, str | None, str | None]:
    """(pay sheet present, install pay, i-code, note).

    Install pay is never invented: an unreadable or out-of-range amount comes
    back None with a note explaining what happened.
    """
    sheets = [f for f in os.listdir(folder) if "installer pay sheet" in f.lower()
              and f.lower().endswith(".pdf")]
    if not sheets:
        return False, None, None, "no installer pay sheet in the folder"
    try:
        import pdfplumber
        with pdfplumber.open(folder / sheets[0]) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception as exc:
        return True, None, None, f"pay sheet present but unreadable ({exc})"

    icode_m = _ICODE_RE.search(text)
    icode = icode_m.group(1) if icode_m else None
    m = _PAY_RE.search(text)
    if not m:
        return True, None, icode, "install pay not found on the pay sheet — read it yourself"
    try:
        pay = float(m.group(2).replace(",", ""))
    except ValueError:
        return True, None, icode, "install pay didn't parse as a number"
    if not (PAY_MIN <= pay <= PAY_MAX):
        return True, None, icode, (f"install pay read as ${pay:,.2f}, outside the expected "
                                   f"${PAY_MIN:,.0f}-${PAY_MAX:,.0f} range — left blank on purpose")
    return True, pay, icode, None


def run(new_orders_dir: Path, emit, pull: bool = True) -> list[dict]:
    """Execute stage 4. Returns one structured result per Carter PO handled."""
    proc_mod = _load_processor(new_orders_dir)
    staging = Path(proc_mod.STG)

    if pull:
        pull_from_outlook(new_orders_dir, emit)

    staged = sorted(f for f in os.listdir(staging)
                    if re.match(r"purchase order 750\d{6}\.pdf$", f, re.I))
    if not staged:
        emit("No Carter POs staged in '4. POs attached' — nothing to process.")
        return []

    emit(f"{len(staged)} Carter PO(s) staged: {', '.join(staged)}")
    results: list[dict] = []

    for po_file in staged:
        result = _process_one(proc_mod, staging, po_file, emit)
        results.append(result)

    ok = sum(1 for r in results if r["outcome"] == "ok")
    flagged = [r for r in results if r["outcome"] != "ok"]
    emit(f"Done. {ok} filed, {len(flagged)} needing you.")
    return results


def _process_one(proc_mod, staging: Path, po_file: str, emit) -> dict:
    """Gather the facts, hold the dollar gate, then let the existing script move files."""
    po_num_m = _PO_NUM_RE.search(po_file)
    result = {
        "carter_po_file": po_file,
        "carter_po_number": po_num_m.group(1) if po_num_m else None,
        "job_code": None, "folder": None, "so_number": None,
        "carter_po_total": None, "so_total": None, "sub_number": None,
        "installer_pay_sheet": None, "install_pay": None, "i_code": None,
        "moved_to_sold": False, "outcome": "skip", "exception": None,
    }

    def fail(outcome: str, message: str) -> dict:
        result["outcome"] = outcome
        result["exception"] = message
        emit(f"  {outcome.upper()} {po_file}: {message}")
        return result

    try:
        so, carter_total, _mmddyy = proc_mod.po_info(str(staging / po_file))
    except Exception as exc:
        return fail("error", f"couldn't read the Carter PO ({exc})")
    result["so_number"] = so
    result["carter_po_total"] = carter_total
    if not so or carter_total is None:
        return fail("skip", "couldn't read the SO number or total off the Carter PO")

    folder_path = proc_mod.find_job_folder(so)
    if not folder_path:
        return fail("skip", f"no staged job folder matches {so} — is the SO filed in stage 3?")
    folder = Path(folder_path)
    result["folder"] = folder.name
    code_m = _JOBCODE_RE.match(folder.name)
    result["job_code"] = code_m.group(1) if code_m else None

    so_total = proc_mod.so_total(folder_path, so)
    result["so_total"] = so_total
    if so_total is None:
        return fail("skip", f"couldn't read a total off the SO in {folder.name}")

    # ---- THE GATE. Never bypassed, never auto-resolved. --------------------
    if round(so_total, 2) != round(carter_total, 2):
        diff = abs(carter_total - so_total)
        return fail(
            "mismatch",
            f"Carter PO ${carter_total:,.2f} != SO ${so_total:,.2f} "
            f"(off by ${diff:,.2f}) — folder NOT moved",
        )

    # Read the pay sheet BEFORE the move: afterwards the folder is gone from staging.
    present, pay, icode, note = read_pay_sheet(folder)
    result["installer_pay_sheet"] = present
    result["install_pay"] = pay
    result["i_code"] = icode

    sub = proc_mod.sub_number(folder_path)
    result["sub_number"] = sub
    if not sub:
        return fail("skip", f"couldn't read the Sub # off the DR Horton PO in {folder.name}")

    dest = proc_mod.community_folder(sub)
    if not dest or isinstance(dest, list):
        return fail("flag", f"no single community folder for Sub {sub} — folder NOT moved")

    # Hand the file work to the script that has been doing it all along. It
    # re-runs the same checks; if it disagrees with us, it wins and nothing moves.
    outcome = proc_mod.process_one(po_file)
    result["outcome"] = "ok" if outcome == "ok" else outcome
    result["moved_to_sold"] = outcome == "ok"

    if outcome == "ok":
        detail = f"${carter_total:,.2f} → {Path(dest).name}"
        if pay is not None:
            detail += f", install pay ${pay:,.2f}"
        elif note:
            detail += f", {note}"
        emit(f"  OK   {result['job_code']} {so} {result['carter_po_number']} — {detail}")
        if note:
            result["exception"] = note   # pay sheet issue, but the job itself filed fine
    else:
        result["exception"] = (result["exception"]
                               or f"the processor returned '{outcome}' — see the run log")
        emit(f"  {outcome.upper()} {result['job_code']}: {result['exception']}")

    return result
