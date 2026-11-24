"""Test copy only: load jobs from a tracker snapshot for the Account Code check.

The test site has no copy of live's jobs, and live's codes have already been
corrected, so the check is proven against the tracker as it stood on a given
day. CSV columns: Job Code, Builder, KSR, I-Code, G-Code, Ashley's Code.
Existing jobs get their I/G codes and KSR replaced; missing ones are created
under a builder account of the same name. Ashley's Codes go to app_settings
(the test copy can't read the tracker). Refused on the live site.
"""
from __future__ import annotations

import csv
import io
import json

from sqlalchemy.orm import Session

from app.account_codes import ASHLEY_KEY
from app.models import Account, AccountCodeFlag, AccountType, Job, JobType, set_setting


def load_jobs(db: Session, text: str) -> dict:
    accounts = {a.name: a for a in db.query(Account).all()}
    jobs = {j.job_code: j for j in db.query(Job).filter(Job.job_code.isnot(None)).all()}
    ashley, created, updated = {}, 0, 0
    for r in csv.DictReader(io.StringIO(text)):
        code = (r.get("Job Code") or "").strip()
        if not code:
            continue
        builder = (r.get("Builder") or "").strip() or "(no builder)"
        acct = accounts.get(builder)
        if acct is None:
            acct = Account(name=builder, type=AccountType.builder)
            db.add(acct)
            db.flush()
            accounts[builder] = acct
        job = jobs.get(code)
        if job is None:
            job = Job(job_code=code, account_id=acct.id, address="(tracker snapshot)", job_type=JobType.tract,
                      sales_contact_name="-", field_contact_name="-")
            db.add(job)
            jobs[code] = job
            created += 1
        else:
            updated += 1
        job.i_code = (r.get("I-Code") or "").strip() or None
        job.g_code = (r.get("G-Code") or "").strip() or None
        ksr = (r.get("KSR") or "").strip()
        job.ksr = None if ksr in ("", "0") else ksr
        ash = (r.get("Ashley's Code") or "").strip()
        if ash:
            ashley[code] = ash
    set_setting(db, ASHLEY_KEY, json.dumps(ashley))
    # a snapshot replaces the world: start the flags over so the run shows that day only
    db.query(AccountCodeFlag).delete()
    db.commit()
    return {"jobs_created": created, "jobs_updated": updated, "ashley_codes": len(ashley)}
