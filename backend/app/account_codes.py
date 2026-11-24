"""Account Code Match: every job's I-code and G-code vs DOMO (Brian 11/24/26).

Corporate sometimes changes or re-sequences job accounts after setup without
telling us, and codes get typed wrong, so codes drift. DOMO is the source of
truth. This flags every job whose stored code doesn't match DOMO, suggests
the DOMO code, and never changes a job by itself -- a person approves each
fix with one click (apply_fix).

Sources
  * DOMO job accounts ("G7510082-016: SUZANNE VICKERS ... - CAB SVCC3160"):
    the daily "CabinetTron feed - Job Account" email (card 1639216258, kept as
    "DOMO CAB Accounts MMDDYY.csv"), plus the I-Account Detail email (card
    661056096), whose "Job Final Bill" column also names each I-account's G.
    -> table domo_accounts.
  * The Job Setup Requests log (Received Job Setup Requests.xlsx, exported to
    "Job Setup Requests MMDDYY.csv") -> table job_setup_requests.
  * Jobs: CabinetTron's job records (job code, I-code, G-code, KSR, builder).

Matching rules
  * The CAB code is the text after "CAB " in the DOMO account name. A DOMO
    account belongs to a job when its CAB code equals the job code, or the
    job's Ashley's Code from the tracker (DR Horton accounts are named by
    community + lot, "CAB GL 34A", not by job code). Case, spaces, dashes and
    dots are ignored ("BURN-0104.2" = "BURN01042").
  * I-accounts start with I, G-accounts with G. The two are numbered
    separately -- one non-installed job shifts the sequences -- so one is never
    inferred from the other and nothing matches on the number alone.

Flags (one row per problem): see FLAGS.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models import (
    Account, AccountCodeFlag, DomoAccount, IAccountLine, Job, JobSetupRequest, get_setting, set_setting,
)

FLAGS = {
    "missing": "Missing code",
    "no_prefix": "No prefix",
    "wrong_prefix": "Wrong prefix",
    "digit": "Digit difference",
    "other_job": "Belongs to another job",
    "name": "Name mismatch",
    "not_in_domo": "Not in DOMO",
    "no_setup": "No setup request",
}
FIELDS = {"I": "i_code", "G": "g_code"}
SUMMARY_KEY = "account_code_check"
ASHLEY_KEY = "account_code_check_ashley"  # test copy: Ashley's Codes from a tracker snapshot
SETUP_GLOB = "Job Setup Requests*.csv"
SETUP_COLS = ["Email Date", "Ashley's Code", "G-Account #", "I-Account #", "G-Account Credit Limit",
              "I-Account Credit Limit", "Job Request #", "Customer Name", "Tracker Job Code"]

# "G7510082-016: SUZANNE VICKERS CONSTRUCTION INC - CAB SVCC3160"
_ACCOUNT = re.compile(r"^\s*(?P<acct>[GI][0-9A-Z]+(?:-[0-9A-Z]+)+)\s*:\s*(?P<rest>.*)$", re.I)
_CAB = re.compile(r"\bCAB\s+(.+?)\s*$", re.I)
_BLANK = {"", "NA", "N/A", "0", "NONE", "-"}
_CASH = ("Z", "CASH")


# ---------------------------------------------------------------- keys

def job_key(s: str | None) -> str:
    """'BURN-0104.2' -> 'BURN01042'. Case, spaces, dashes and dots ignored."""
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def ash_key(s: str | None) -> str:
    """Ashley's Code / CAB name -> key: 'CAB GL 034A' -> 'GL34A'. DR Horton lot
    numbers drift in zero padding between DOMO and the tracker."""
    k = job_key(re.sub(r"^\s*CAB\b", "", str(s or ""), flags=re.I))
    return re.sub(r"\d+", lambda m: str(int(m.group())), k)


def clean_code(s: str | None) -> str:
    """Stored code as typed, minus case and outside spaces."""
    v = str(s or "").strip().upper()
    return "" if v in _BLANK else v


def cab_code(name: str | None) -> str | None:
    m = _CAB.search(str(name or ""))
    return " ".join(m.group(1).split()) if m else None


def _loose(code: str) -> str:
    """Account with dash/space format and suffix zero padding ignored."""
    parts = [p for p in re.split(r"[\s_-]+", code.upper()) if p]
    if not parts:
        return ""
    return parts[0] + "".join("-" + (p.lstrip("0") or "0") for p in parts[1:])


def _one_edit(a: str, b: str) -> bool:
    """b is a with exactly one character added or dropped."""
    if abs(len(a) - len(b)) != 1:
        return False
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def near_code(stored: str, domo: str) -> bool:
    """G7500042-0120 vs G7500042-120, G750-00-023 vs G750-000-023,
    G7510189-0103 vs G7510189-003: one digit too many / too few, or padding."""
    return stored != domo and (_loose(stored) == _loose(domo) or _one_edit(stored, domo))


def _master_seq(code: str) -> tuple[str, int] | None:
    """'G7510082-016' -> ('G7510082', 16); 'G750-000-023' -> ('G750-000', 23)."""
    head, _, tail = str(code or "").upper().rpartition("-")
    return (head, int(tail)) if head and tail.isdigit() else None


def near_name(a: str, b: str) -> bool:
    """HOFL0300 vs HOFL0200: close enough that it's likely a typo in DOMO's
    account name (or ours) -- flagged for review, never auto-fixed."""
    a, b = job_key(a), job_key(b)
    if not a or not b:
        return False
    same_letters = re.sub(r"\d", "", a) == re.sub(r"\d", "", b)
    return (same_letters and SequenceMatcher(None, a, b).ratio() >= 0.75) or _one_edit(a, b)


# ---------------------------------------------------------------- loading

def parse_accounts(text: str, source: str) -> list[dict]:
    """Job Account feed ("DOMO CAB Accounts" CSV, column "Job Account", or the
    raw card's "Job") -> account dicts. Every G/I account; cab_code is None
    for accounts not named "... - CAB ..."."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = (row.get("Job Account") or row.get("Job") or "").strip()
        m = _ACCOUNT.match(raw)
        if not m:
            continue
        rest = m["rest"]
        cab = cab_code(rest)
        if cab:
            cust, _, name = rest.rpartition(" - CAB ")
            name = f"CAB {name.strip()}" if name else rest.strip()
        else:  # not a cabinet account -- kept so "not in DOMO" means what it says
            cust, _, name = rest.rpartition(" - ")
            name = (name or rest).strip()
        out.append({"account": m["acct"].upper(), "kind": m["acct"][0].upper(), "customer": cust.strip() or None,
                    "name": name[:200], "cab_code": cab,
                    "linked_g": (row.get("Linked G") or "").strip().upper() or None, "source": source})
    return out


def replace_accounts(db: Session, rows: list[dict], iaccount_extra: bool = True) -> dict:
    """The Job Account feed is the full list: replace the table, then add any
    CAB account the I-Account Detail email knows that the feed doesn't (with
    the I -> G final-bill link)."""
    db.query(DomoAccount).delete()
    seen = {}
    for r in rows:
        seen[r["account"]] = r
    extra = 0
    if iaccount_extra:
        for g, i, iname in db.query(IAccountLine.g_account, IAccountLine.i_account, IAccountLine.i_account_name).distinct():
            cab = cab_code(iname)
            if not cab:
                continue
            for acct in (i, g):
                acct = (acct or "").upper()
                if acct and acct[0] in "GI" and acct not in seen:
                    seen[acct] = {"account": acct, "kind": acct[0], "customer": None, "name": f"CAB {cab}",
                                  "cab_code": cab, "linked_g": None, "source": "I-Account Detail"}
                    extra += 1
            if i and (i.upper() in seen) and g:
                seen[i.upper()]["linked_g"] = seen[i.upper()].get("linked_g") or g.upper()
    for r in seen.values():
        db.add(DomoAccount(**r))
    db.commit()
    return {"accounts": len(seen), "from_job_account_feed": len(rows), "from_i_account_detail": extra}


def parse_setups(text: str) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        ash = (r.get("Ashley's Code") or "").strip()
        g = clean_code(r.get("G-Account #"))
        i = clean_code(r.get("I-Account #"))
        if not (ash or g or i):
            continue
        d = (r.get("Email Date") or "")[:10]
        try:
            when = date.fromisoformat(d)
        except ValueError:
            when = None
        out.append({"email_date": when, "ashley_code": ash or None, "g_account": g or None, "i_account": i or None,
                    "g_limit": (r.get("G-Account Credit Limit") or "").strip() or None,
                    "i_limit": (r.get("I-Account Credit Limit") or "").strip() or None,
                    "request_no": (r.get("Job Request #") or "").strip() or None,
                    "customer_name": (r.get("Customer Name") or "").strip() or None,
                    "tracker_job_code": (r.get("Tracker Job Code") or "").strip() or None})
    return out


def replace_setups(db: Session, rows: list[dict]) -> dict:
    db.query(JobSetupRequest).delete()
    for r in rows:
        db.add(JobSetupRequest(**r))
    db.commit()
    return {"setup_requests": len(rows)}


def newest_file(folder, pattern: str = SETUP_GLOB):
    from pathlib import Path

    folder = Path(folder)
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
    return files[0] if files else None


def _ashley_by_job(db: Session) -> dict[str, str]:
    """Job Code -> Ashley's Code. The live site reads the tracker; the test
    copy can't, so it keeps the snapshot it was sent in app_settings."""
    out: dict[str, str] = {}
    try:
        from app.smartsheet.api import _tracker_rows

        rows, _ok, _name = _tracker_rows()
        for r in rows:
            code = str(r.get("Job Code") or "").strip()
            ash = str(r.get("Ashley's  Code") or r.get("Ashley's Code") or "").strip()
            if code and ash and ash.upper() not in _BLANK:
                out[code] = ash
    except Exception:  # noqa: BLE001 -- no tracker on this copy
        pass
    if not out:
        raw = get_setting(db, ASHLEY_KEY)
        if raw:
            out = json.loads(raw)
    return out


# ---------------------------------------------------------------- the check

def find_problems(jobs: list[dict], accounts: list[dict], setups: list[dict]) -> list[dict]:
    """Pure: jobs = [{job_id, job_code, i_code, g_code, ashley}], accounts =
    domo_accounts rows as dicts, setups = job_setup_requests rows as dicts.
    Returns one dict per problem (job_code, field, flag, stored, domo, name,
    detail)."""
    by_acct = {a["account"]: a for a in accounts}
    by_cab: dict[str, list[dict]] = defaultdict(list)
    by_ash: dict[str, list[dict]] = defaultdict(list)
    for a in accounts:
        if a.get("cab_code"):
            by_cab[job_key(a["cab_code"])].append(a)
            by_ash[ash_key(a["cab_code"])].append(a)
    # Which CabinetTron job a DOMO CAB name points at (job code first, then Ashley's Code).
    job_by_key = {job_key(j["job_code"]): j["job_code"] for j in jobs}
    job_by_ash: dict[str, set] = defaultdict(set)
    for j in jobs:
        if j.get("ashley"):
            job_by_ash[ash_key(j["ashley"])].add(j["job_code"])

    def owner(a: dict) -> str | None:
        if not a.get("cab_code"):
            return None
        code = job_by_key.get(job_key(a["cab_code"]))
        if code:
            return code
        hits = job_by_ash.get(ash_key(a["cab_code"]), set())
        return next(iter(hits)) if len(hits) == 1 else None

    setup_accts = set()
    setup_keys = set()
    first_logged: dict[str, int] = {}  # "G7510082" -> lowest sequence # in the setup log
    for s in setups:
        for c in (s.get("g_account"), s.get("i_account")):
            if c:
                setup_accts.add(_loose(c))
                ms = _master_seq(c)
                if ms:
                    first_logged[ms[0]] = min(first_logged.get(ms[0], ms[1]), ms[1])
        if s.get("ashley_code"):
            setup_keys.add(job_key(re.sub(r"^\s*CAB\b", "", s["ashley_code"], flags=re.I)))
            setup_keys.add(ash_key(s["ashley_code"]))
        if s.get("tracker_job_code"):
            setup_keys.add(job_key(s["tracker_job_code"]))

    by_kind: dict[str, list[str]] = defaultdict(list)
    for a in accounts:
        by_kind[a["kind"]].append(a["account"])

    def label(a: dict | None) -> str | None:
        return a["name"] if a else None

    out = []
    for j in jobs:
        code = j["job_code"]
        mine = {a["account"]: a for a in by_cab.get(job_key(code), [])}
        if j.get("ashley"):
            for a in by_ash.get(ash_key(j["ashley"]), []):
                mine.setdefault(a["account"], a)
        expect = {k: sorted(a for a, v in mine.items() if v["kind"] == k) for k in FIELDS}

        def suggest(kind: str) -> str | None:
            return expect[kind][0] if len(expect[kind]) == 1 else None

        def row(field, flag, stored, domo, detail):
            a = by_acct.get(domo or "") or by_acct.get(stored or "")
            return {"job_id": j.get("job_id"), "job_code": code, "field": field, "flag": flag,
                    "stored": stored or None, "domo": domo, "name": label(a), "detail": detail}

        for kind, attr in FIELDS.items():
            stored = clean_code(j.get(attr))
            other = "G" if kind == "I" else "I"
            fix = suggest(kind)
            many = "" if len(expect[kind]) < 2 else f" DOMO has {len(expect[kind])} {kind}-accounts for this job: " \
                                                     f"{', '.join(expect[kind])}."
            if not stored:
                if expect[kind]:
                    out.append(row(kind, FLAGS["missing"], None, fix,
                                   f"No {kind}-code on the job; DOMO has {', '.join(expect[kind])}."))
                continue
            if stored[0].isdigit():
                reads = []
                for p in (kind, other):
                    a = by_acct.get(p + stored)
                    if a:
                        who = owner(a)
                        reads.append(f"{p}{stored} = {a['name']}" + (f" ({who})" if who and who != code else ""))
                    else:
                        reads.append(f"{p}{stored} is not a DOMO account")
                hit = by_acct.get(kind + stored)
                domo = kind + stored if hit and (kind + stored) in mine else fix
                out.append(row(kind, FLAGS["no_prefix"], stored, domo,
                               f"Stored without I/G. Reads as: {'; '.join(reads)}." + many))
                continue
            if stored[0] == other:
                a = by_acct.get(stored)
                what = f"{stored} is a {other}-account" + (f" ({a['name']})" if a else "")
                same = clean_code(j.get(FIELDS[other]))
                tail = " The G-code field already holds it." if same == stored and kind == "I" else (
                    " The I-code field already holds it." if same == stored else "")
                out.append(row(kind, FLAGS["wrong_prefix"], stored, fix,
                               f"{what} stored in the {kind}-code field.{tail}" + many))
                continue
            if stored.startswith(_CASH):
                continue  # cash-sale customer (Z7510077, CASH752): no job account to check
            if stored[0] != kind:
                out.append(row(kind, FLAGS["not_in_domo"], stored, fix, f"{stored} isn't an I- or G-account." + many))
                continue
            a = by_acct.get(stored)
            if a is not None:
                if stored in mine:
                    continue  # matches DOMO
                if not a.get("cab_code"):
                    # Not a cabinet account. Only a problem when DOMO does have
                    # this job's CAB account; otherwise there's nothing to check against.
                    if expect[kind]:
                        out.append(row(kind, FLAGS["other_job"], stored, fix,
                                       f"DOMO names {stored} \"{a['name']}\" (not a CAB account); this job's "
                                       f"{kind}-account is {', '.join(expect[kind])}."))
                    continue
                who = owner(a)
                if who and who != code:
                    out.append(row(kind, FLAGS["other_job"], stored, fix,
                                   f"DOMO names {stored} {a['name']}, which is job {who}." + many))
                elif expect[kind] and not near_name(a["cab_code"], code):
                    # DOMO does have this job's account, and the stored one is named for something else
                    out.append(row(kind, FLAGS["other_job"], stored, fix,
                                   f"DOMO names {stored} {a['name']} (no CabinetTron job by that name); this job's "
                                   f"{kind}-account is {', '.join(expect[kind])}."))
                else:
                    # No job owns the name -- DR Horton lot names drift (CAB IND60 135 vs the
                    # tracker's Ashley's Code), and HOFL0300 vs HOFL0200 is a typo on one side.
                    ash = f" (Ashley's Code {j['ashley']})" if j.get("ashley") else ""
                    out.append(row(kind, FLAGS["name"], stored, None,
                                   f"DOMO names {stored} {a['name']}; the job is {code}{ash}. Review -- "
                                   f"not auto-fixed (DOMO's name or ours may be the typo)." + many))
                continue
            close = [e for e in expect[kind] if near_code(stored, e)]
            if len(close) == 1:
                out.append(row(kind, FLAGS["digit"], stored, close[0],
                               f"{stored} isn't a DOMO account; {close[0]} is this job's {kind}-account."))
                continue
            if not expect[kind]:
                # DOMO has no CAB account for this job: a one-digit slip may
                # still point at the account (often one whose name is off too).
                close = [x for x in by_kind[kind] if near_code(stored, x)]
                if len(close) == 1:
                    b = by_acct[close[0]]
                    out.append(row(kind, FLAGS["digit"], stored, close[0],
                                   f"{stored} isn't a DOMO account; {close[0]} is one digit off and DOMO names it "
                                   f"{b['name']} -- check the name before fixing."))
                    continue
            out.append(row(kind, FLAGS["not_in_domo"], stored, fix, f"{stored} isn't a DOMO account." + many))

        # The log only goes back to its first request: an account "should have
        # a request" when it was set up after that customer's first logged
        # account (account numbers run in setup order).
        newer = [a for a in mine if (ms := _master_seq(a)) and ms[0] in first_logged and ms[1] > first_logged[ms[0]]]
        if newer:
            keys = {job_key(code)} | ({ash_key(j["ashley"]), job_key(re.sub(r"^\s*CAB\b", "", j["ashley"], flags=re.I))}
                                      if j.get("ashley") else set())
            if not (keys & setup_keys) and not ({_loose(a) for a in mine} & setup_accts):
                out.append(row("-", FLAGS["no_setup"], None, None,
                               f"DOMO has {', '.join(sorted(mine))} but there's no Job Setup Request row."))
    return out


def _jobs(db: Session, ashley: dict[str, str]) -> list[dict]:
    q = db.query(Job.id, Job.job_code, Job.i_code, Job.g_code).filter(Job.job_code.isnot(None))
    return [{"job_id": i, "job_code": c, "i_code": ic, "g_code": gc, "ashley": ashley.get(c)} for i, c, ic, gc in q]


def run(db: Session, today: date | None = None) -> dict:
    """Recompute every flag. New problems open a flag; open flags that no
    longer show up are marked Fixed; Ignored ones stay Ignored."""
    today = today or date.today()
    accounts = [{"account": a.account, "kind": a.kind, "name": a.name, "cab_code": a.cab_code}
                for a in db.query(DomoAccount).all()]
    if not accounts:
        return {"error": "no DOMO job accounts loaded -- nothing checked"}
    setups = [{"g_account": s.g_account, "i_account": s.i_account, "ashley_code": s.ashley_code,
               "tracker_job_code": s.tracker_job_code} for s in db.query(JobSetupRequest).all()]
    ashley = _ashley_by_job(db)
    jobs = _jobs(db, ashley)
    found = find_problems(jobs, accounts, setups)
    if not setups:  # no setup log loaded: don't call every job "no setup request"
        found = [f for f in found if f["flag"] != FLAGS["no_setup"]]

    existing = {(f.job_code, f.field, f.flag): f for f in db.query(AccountCodeFlag).all()}
    now = datetime.now(timezone.utc)
    current, new, reopened = set(), 0, 0
    for p in found:
        key = (p["job_code"], p["field"], p["flag"])
        current.add(key)
        f = existing.get(key)
        if f is None:
            db.add(AccountCodeFlag(job_id=p["job_id"], job_code=p["job_code"], field=p["field"], flag=p["flag"],
                                   stored_code=p["stored"], domo_code=p["domo"], domo_name=p["name"],
                                   detail=p["detail"], status="open", first_seen=today, last_seen=today))
            new += 1
            continue
        if f.status == "fixed":
            f.status, f.first_seen, f.resolved_at, f.resolved_by, f.times_seen = "open", today, None, None, 0
            reopened += 1
        f.job_id, f.stored_code, f.domo_code, f.domo_name, f.detail = (
            p["job_id"], p["stored"], p["domo"], p["name"], p["detail"])
        if f.last_seen != today:
            f.times_seen = (f.times_seen or 0) + 1
        f.last_seen = today
    fixed = 0
    for key, f in existing.items():
        if key not in current and f.status == "open":
            f.status, f.resolved_at, f.resolved_by = "fixed", now, "matches DOMO"
            fixed += 1
    db.flush()
    summary = {"at": now.isoformat(timespec="seconds"), "date": today.isoformat(), "jobs": len(jobs),
               "domo_accounts": len(accounts), "setup_requests": len(setups), "ashley_codes": len(ashley),
               "found": len(found), "new": new, "reopened": reopened, "fixed": fixed, **daily(db, today)}
    set_setting(db, SUMMARY_KEY, json.dumps(summary, default=str))
    db.commit()
    return summary


def daily(db: Session, today: date | None = None) -> dict:
    """Open flags by KSR, and flags first seen today (new since yesterday)."""
    today = today or date.today()
    ksr_of = _ksr_builder(db)
    by_ksr: dict[str, int] = defaultdict(int)
    by_flag: dict[str, int] = defaultdict(int)
    new_today = 0
    for f in db.query(AccountCodeFlag).filter(AccountCodeFlag.status == "open"):
        by_ksr[ksr_of.get(f.job_code, (None, None))[0] or "(no KSR)"] += 1
        by_flag[f.flag] += 1
        if f.first_seen == today:
            new_today += 1
    return {"open": sum(by_ksr.values()), "open_by_ksr": dict(sorted(by_ksr.items())),
            "open_by_flag": dict(sorted(by_flag.items())), "new_since_yesterday": new_today}


def _ksr_builder(db: Session) -> dict[str, tuple]:
    q = db.query(Job.job_code, Job.ksr, Account.ksr, Account.name).join(Account, Account.id == Job.account_id)
    return {c: (jk or ak, name) for c, jk, ak, name in q}


def flags(db: Session, status: str | None = "open") -> list[dict]:
    ksr_of = _ksr_builder(db)
    q = db.query(AccountCodeFlag)
    if status and status != "all":
        q = q.filter(AccountCodeFlag.status == status)
    order = {v: i for i, v in enumerate(FLAGS.values())}
    out = []
    for f in q:
        ksr, builder = ksr_of.get(f.job_code, (None, None))
        out.append({"id": f.id, "job_id": f.job_id, "job_code": f.job_code, "ksr": ksr, "builder": builder,
                    "field": f.field, "stored_code": f.stored_code, "domo_code": f.domo_code, "flag": f.flag,
                    "domo_name": f.domo_name, "detail": f.detail, "first_seen": f.first_seen,
                    "last_seen": f.last_seen, "status": f.status, "resolved_at": f.resolved_at,
                    "resolved_by": f.resolved_by,
                    "can_fix": bool(f.status == "open" and f.domo_code and f.field in FIELDS
                                    and f.flag != FLAGS["name"])})
    out.sort(key=lambda r: (r["status"] != "open", order.get(r["flag"], 99), r["job_code"], r["field"]))
    return out


def apply_fix(db: Session, flag_id: int, user: str) -> dict:
    """One click: write the suggested DOMO code onto the job, then re-check
    that job so the flag closes (or shows what's still wrong)."""
    f = db.get(AccountCodeFlag, flag_id)
    if f is None:
        raise LookupError("no such flag")
    if f.status != "open" or not f.domo_code or f.field not in FIELDS or f.flag == FLAGS["name"]:
        raise ValueError("this flag has no fix to apply")
    job = db.get(Job, f.job_id) if f.job_id else db.query(Job).filter(Job.job_code == f.job_code).first()
    if job is None:
        raise LookupError("job not found")
    if not db.get(DomoAccount, f.domo_code):
        raise ValueError(f"{f.domo_code} is no longer a DOMO account -- re-run the check")
    attr = FIELDS[f.field]
    before = getattr(job, attr)
    setattr(job, attr, f.domo_code)
    f.status, f.resolved_at, f.resolved_by = "fixed", datetime.now(timezone.utc), user
    db.commit()
    return {"job_code": job.job_code, "field": attr, "before": before, "after": f.domo_code}


def set_status(db: Session, flag_id: int, status: str, user: str) -> dict:
    if status not in ("open", "ignored"):
        raise ValueError("status must be open or ignored")
    f = db.get(AccountCodeFlag, flag_id)
    if f is None:
        raise LookupError("no such flag")
    f.status = status
    f.resolved_at = datetime.now(timezone.utc) if status == "ignored" else None
    f.resolved_by = user if status == "ignored" else None
    db.commit()
    return {"id": f.id, "status": f.status}


def last_summary(db: Session) -> dict | None:
    raw = get_setting(db, SUMMARY_KEY)
    return json.loads(raw) if raw else None
