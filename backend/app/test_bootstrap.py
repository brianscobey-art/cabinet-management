"""One-time setup for the TEST copy of the app, driven by env vars on boot.

The test service on Render can be set up entirely from its environment, with
no Shell session: set the vars below, let it deploy, read the log, then remove
the vars. Does nothing at all unless APP_ENV=test.

    TEST_ADMIN_EMAIL / TEST_ADMIN_NAME
        Create this admin login if it does not exist. It starts with a random
        password nobody knows; a set-password link (good for INVITE_EXPIRE_HOURS)
        is written to the service log once, so the owner picks their own password.
        TEST_ADMIN_RELINK=1 writes a fresh link for an existing login.
    TEST_SEED_SAMPLE=1
        Fill an empty database with the made-up sample jobs (scripts.seed_test_data).
    TEST_COPY_JOBS=25  (or a comma-separated list of job codes)
        With LIVE_DATABASE_URL set, copy that many sold jobs from live, read-only
        (scripts.copy_jobs_from_live). Runs once per value; a reboot does not copy again.
"""

from __future__ import annotations

import logging
import os
import secrets

from app.config import get_settings

logger = logging.getLogger("uvicorn.error")


def run() -> dict:
    s = get_settings()
    if not s.is_test:
        return {"skipped": "not the test copy"}
    from app.database import SessionLocal, engine

    out: dict = {}
    with SessionLocal() as db:
        out["admin"] = _admin(db, s)
        if os.environ.get("TEST_SEED_SAMPLE", "").strip() == "1":
            out["sample"] = _sample(db)
        want = os.environ.get("TEST_COPY_JOBS", "").strip()
        if want:
            out["copy"] = _copy(db, engine, want)
    logger.info("TEST bootstrap: %s", out)
    return out


def _admin(db, s) -> str:
    from app.auth.router import _unique_username, derive_username
    from app.auth.security import create_invite_token, hash_password
    from app.models import Role, User

    email = os.environ.get("TEST_ADMIN_EMAIL", "").strip().lower()
    if not email:
        return "no TEST_ADMIN_EMAIL"
    name = os.environ.get("TEST_ADMIN_NAME", "").strip() or email.split("@")[0]
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, full_name=name,
                    username=_unique_username(db, derive_username(name, email)),
                    hashed_password=hash_password(secrets.token_urlsafe(32)), role=Role.admin)
        db.add(user)
        db.commit()
        status = "created"
    elif os.environ.get("TEST_ADMIN_RELINK", "").strip() == "1":
        status = "relinked"
    else:
        return "exists"
    url = f"{s.app_base_url.rstrip('/')}/#/set-password?token={create_invite_token(email)}"
    # The one place this link is shown. Test copy only; it sets the password
    # for this test login and nothing else.
    logger.warning("TEST bootstrap: set-password link for %s: %s", email, url)
    return status


def _sample(db) -> str:
    from app.models import Job
    from scripts.seed_test_data import seed

    if db.query(Job.id).first() is not None:
        return "skipped: database already has jobs"
    return str(seed(db, None, None, None))


def _copy(db, engine, want: str) -> str:
    from app.models.appsetting import get_setting, set_setting
    from scripts import copy_jobs_from_live as C

    live_url = os.environ.get("LIVE_DATABASE_URL", "")
    if not live_url:
        return "skipped: LIVE_DATABASE_URL not set"
    if C._same_database(live_url, get_settings().database_url):
        return "refused: LIVE_DATABASE_URL is this database"
    flag = f"test_copy_done:{want}"[:64]
    if get_setting(db, flag):
        return f"already done: {get_setting(db, flag)}"
    live = C.open_live_readonly(live_url)
    try:
        if want.isdigit():
            jobs = C.pick_jobs(live, None, int(want))
        else:
            jobs = C.pick_jobs(live, [c.strip() for c in want.split(",") if c.strip()], None)
        result = C.copy_jobs(live, engine, jobs)
    finally:
        live.dispose()
    summary = (f"{result['copied'].get('jobs', 0)} jobs copied, "
               f"{len(result['skipped_already_in_test'])} already in test")
    set_setting(db, flag, summary)
    db.commit()
    return summary
