"""Copy real sold jobs from the LIVE database into the TEST copy, read-only.

Brian asked (11/5/26) to use sold jobs as test jobs. This brings a chosen set
of jobs, and everything that hangs off them, from live into test so the new
process can be run against real-world mess without touching live.

Run it on the test service's Shell (or anywhere with the test DATABASE_URL):

    APP_ENV=test python -m scripts.copy_jobs_from_live --pick 25 --dry-run
    APP_ENV=test python -m scripts.copy_jobs_from_live --pick 25
    APP_ENV=test python -m scripts.copy_jobs_from_live --codes DRPCE-0412,WEL-0318

The live connection string is read from the LIVE_DATABASE_URL env var (Render
-> the live database -> External Database URL), never typed on the command
line, so it stays out of shell history.

Double checks, in order:
1. Target must be the test copy: APP_ENV=test, and its DATABASE_URL must not be
   the same database as LIVE_DATABASE_URL.
2. Live is opened read-only. Postgres sessions run with
   default_transaction_read_only=on, so any write is refused by the server
   itself; SQLite is opened with mode=ro. The script only ever SELECTs there.
3. Contact emails and phone numbers are masked on the way in (pass
   --keep-contacts to keep them), so nothing in test can reach a real person.
4. A job whose job code is already in test is skipped, so re-running is safe.
5. Every insert goes in one transaction on the test database: it all lands or
   none of it does. --dry-run reports the counts and writes nothing.

What comes along with each job: its account and community (reused if test
already has one with the same name), room and hardware selections, quotes and
line items, orders, ordering checklist, field measures, phase history, notes,
documents (paths only: the files themselves live in OneDrive/R2, which the
test copy cannot read), service requests, parts and lines, visits, job costs,
Domo POs, install and QC reports. Workers are matched by name; unmatched
visits are left unassigned.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.config import get_settings
from app.database import Base, _normalize
from app.models import JobStatus

META = Base.metadata
T = META.tables

# Statuses that mean "sold": an order exists or is in progress. Never voids.
SOLD_STATUSES = [
    "1.2-NdOrd", "1.3-Ord Prcss", "1.4-OrdSub", "1.5-OrdPO", "2.0-Ord", "2.1-Inst",
    "3.0-Nd QW", "3.1-Parts", "4.0-Punch", "4.1-Blue", "5.0-EPO", "6.0-Clsd", "7.0-War",
]

# Children of a job, parents before children. Each entry: table, and the
# column that ties it to an already-copied row.
CHILDREN = [
    ("room_selections", "job_id"), ("hardware_selections", "job_id"),
    ("quotes", "job_id"), ("quote_line_items", "quote_id"), ("orders", "job_id"),
    ("ordering_checklists", "job_id"), ("field_measures", "job_id"),
    ("field_measure_notes", "job_id"), ("phase_updates", "job_id"),
    ("job_notes", "job_id"), ("job_documents", "job_id"), ("layout_prints", "job_id"),
    ("job_costs", "job_id"), ("domo_pos", "job_id"), ("install_reports", "job_id"),
    ("qc_reports", "job_id"), ("notes", "job_id"), ("note_reads", "note_id"),
    ("note_tags", "note_id"), ("service_requests", "job_id"),
    ("service_parts", "service_request_id"), ("service_lines", "service_request_id"),
    ("visits", "job_id"),
]

_EMAIL = re.compile(r"(^|_)e?mail$")
_PHONE = re.compile(r"(^|_)phone$")


class Refused(SystemExit):
    pass


def _same_database(a: str, b: str) -> bool:
    ua, ub = make_url(_normalize(a)), make_url(_normalize(b))
    if ua.get_backend_name() != ub.get_backend_name():
        return False
    if ua.get_backend_name() == "sqlite":
        return os.path.abspath(ua.database or "") == os.path.abspath(ub.database or "")
    return (ua.host, ua.port or 5432, ua.database) == (ub.host, ub.port or 5432, ub.database)


def open_live_readonly(url: str):
    """Engine on live that physically cannot write."""
    url = _normalize(url)
    if url.startswith("sqlite"):
        path = make_url(url).database
        return create_engine(f"sqlite:///file:{path}?mode=ro&uri=true",
                             connect_args={"check_same_thread": False})
    return create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})


def _mask(table: str, row: dict, new_id_hint: int) -> dict:
    for col in list(row):
        if row[col] in (None, ""):
            continue
        if _EMAIL.search(col):
            row[col] = f"masked+{table}{new_id_hint}@example.invalid"
        elif _PHONE.search(col):
            row[col] = None
    return row


def pick_jobs(live, codes: list[str] | None, pick: int | None) -> list[dict]:
    """The jobs to copy. With --pick, spread across statuses and accounts so
    the sample covers as many different situations as possible."""
    jobs = T["jobs"]
    with live.connect() as c:
        if codes:
            rows = [dict(r._mapping) for r in c.execute(select(jobs).where(jobs.c.job_code.in_(codes)))]
            missing = set(codes) - {r["job_code"] for r in rows}
            if missing:
                print(f"Not found on live (skipped): {', '.join(sorted(missing))}")
            return rows
        rows = [dict(r._mapping) for r in c.execute(
            select(jobs).where(jobs.c.status.in_([JobStatus(v) for v in SOLD_STATUSES]))
            .order_by(jobs.c.id.desc()))]
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        status = getattr(r["status"], "value", r["status"])
        buckets[(status, r["account_id"])].append(r)
    chosen: list[dict] = []
    while len(chosen) < pick and any(buckets.values()):
        for key in sorted(buckets, key=lambda k: (SOLD_STATUSES.index(k[0]), k[1])):
            if buckets[key] and len(chosen) < pick:
                chosen.append(buckets[key].pop(0))
    return chosen


def copy_jobs(live, target, job_rows: list[dict], keep_contacts: bool = False,
              dry_run: bool = False) -> dict:
    counts: dict[str, int] = defaultdict(int)
    skipped: list[str] = []
    idmap: dict[str, dict] = defaultdict(dict)

    with live.connect() as src, target.begin() as dst:
        def insert(table: str, row: dict) -> int:
            old_id = row.pop("id", None)
            if not keep_contacts:
                _mask(table, row, old_id or 0)
            counts[table] += 1
            if dry_run:
                new_id = -(len(idmap[table]) + 1)
            else:
                res = dst.execute(T[table].insert().values(**row))
                new_id = res.inserted_primary_key[0] if "id" in T[table].c else None
            if old_id is not None:
                idmap[table][old_id] = new_id
            return new_id

        existing_codes = {r[0] for r in dst.execute(select(T["jobs"].c.job_code)) if r[0]}
        todo = []
        for j in job_rows:
            if j["job_code"] and j["job_code"] in existing_codes:
                skipped.append(j["job_code"])
            else:
                todo.append(dict(j))

        # Parents: accounts and communities, reused by name when test has them.
        acct_ids = {j["account_id"] for j in todo}
        for a in src.execute(select(T["accounts"]).where(T["accounts"].c.id.in_(acct_ids))):
            a = dict(a._mapping)
            hit = dst.execute(select(T["accounts"].c.id).where(T["accounts"].c.name == a["name"])).first()
            if hit:
                idmap["accounts"][a["id"]] = hit[0]
            else:
                insert("accounts", a)
        comm_ids = {j["community_id"] for j in todo if j["community_id"]}
        for cm in src.execute(select(T["communities"]).where(T["communities"].c.id.in_(comm_ids))):
            cm = dict(cm._mapping)
            cm["account_id"] = idmap["accounts"][cm["account_id"]]
            hit = dst.execute(select(T["communities"].c.id).where(
                (T["communities"].c.name == cm["name"])
                & (T["communities"].c.account_id == cm["account_id"]))).first()
            if hit:
                idmap["communities"][cm["id"]] = hit[0]
            else:
                insert("communities", cm)

        for j in todo:
            j["account_id"] = idmap["accounts"][j["account_id"]]
            j["community_id"] = idmap["communities"].get(j["community_id"])
            insert("jobs", j)

        # Workers are matched by name only; never copied (they are people).
        worker_by_name = {r[1]: r[0] for r in dst.execute(select(T["workers"].c.id, T["workers"].c.name))}
        live_worker_name = {r[0]: r[1] for r in src.execute(select(T["workers"].c.id, T["workers"].c.name))}

        parent_of = {"job_id": "jobs", "quote_id": "quotes", "note_id": "notes",
                     "service_request_id": "service_requests"}
        for table, key in CHILDREN:
            parents = list(idmap[parent_of[key]])
            if not parents:
                continue
            t = T[table]
            rows = [dict(r._mapping) for r in src.execute(
                select(t).where(t.c[key].in_(parents)).order_by(*t.primary_key.columns))]
            for r in rows:
                for col in t.columns:
                    if not col.foreign_keys or r.get(col.name) is None:
                        continue
                    target_table = next(iter(col.foreign_keys)).column.table.name
                    if target_table == "workers":
                        r[col.name] = worker_by_name.get(live_worker_name.get(r[col.name]))
                    else:
                        r[col.name] = idmap[target_table].get(r[col.name])
                if table == "orders" and r.get("quote_id") is None:
                    counts["orders_skipped_no_quote"] += 1
                    continue
                insert(table, r)

        if dry_run:
            dst.rollback()
    return {"copied": dict(counts), "skipped_already_in_test": skipped, "dry_run": dry_run}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--codes", help="comma-separated job codes to copy")
    g.add_argument("--pick", type=int, help="copy this many sold jobs, spread across statuses and builders")
    ap.add_argument("--keep-contacts", action="store_true", help="do not mask emails and phones")
    ap.add_argument("--dry-run", action="store_true", help="report what would be copied, write nothing")
    args = ap.parse_args(argv)

    s = get_settings()
    if not s.is_test:
        raise Refused("Refusing: APP_ENV is not 'test'. This script only ever writes into the test copy.")
    live_url = os.environ.get("LIVE_DATABASE_URL", "")
    if not live_url:
        raise Refused("Set LIVE_DATABASE_URL to the live database's external connection string.")
    if _same_database(live_url, s.database_url):
        raise Refused("Refusing: DATABASE_URL and LIVE_DATABASE_URL point at the same database.")

    live = open_live_readonly(live_url)
    target = create_engine(_normalize(s.database_url))
    codes = [c.strip() for c in args.codes.split(",")] if args.codes else None
    jobs = pick_jobs(live, codes, args.pick)
    if not jobs:
        print("No matching jobs on live.")
        sys.exit(1)
    print(f"Copying {len(jobs)} job(s): {', '.join(j['job_code'] or str(j['id']) for j in jobs)}")
    print(copy_jobs(live, target, jobs, keep_contacts=args.keep_contacts, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
