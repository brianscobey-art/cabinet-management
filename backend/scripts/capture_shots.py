"""Screenshot each app screen for the corporate showcase deck.

Runs against a local server (default http://127.0.0.1:8090) with an admin token
injected into localStorage so every page loads authenticated. Saves PNGs to the
folder given as argv[1].
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.auth.security import create_access_token
from app.database import SessionLocal
from app.models import Role, User

BASE = "http://127.0.0.1:8090"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")
OUT.mkdir(parents=True, exist_ok=True)

VIEW = {"width": 1600, "height": 900}

# (filename, path, wait_seconds, list of JS click selectors to try before shot)
SHOTS = [
    ("01_suite", "/#/suite", 2.0, []),
    ("02_job_detail", "/#/jobs/221", 2.5, []),
    ("03_ordering", "/#/ordering", 2.5, []),
    ("04_schedule", "/#/schedule", 2.5, []),
    ("05_phases", "/#/phases", 2.0, []),
    ("06_reports", "/#/reports", 2.5, []),
    ("07_forms", "/#/forms", 2.0, []),
    ("08_users", "/#/users", 2.0, []),
    ("09_help", "/#/help", 2.0, []),
    ("10_optimus", "/ordering-platform", 3.0, []),
    ("11_autobot", "/autobot", 4.0, []),
]


def main() -> None:
    db = SessionLocal()
    admin = db.query(User).filter(User.role == Role.admin, User.is_active.is_(True)).first()
    token = create_access_token(admin.email, admin.role.value)
    db.close()
    print("using admin:", admin.email)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=VIEW, device_scale_factor=2)
        # token present before any app JS runs, for both the SPA and the standalone apps
        ctx.add_init_script(
            f"localStorage.setItem('cms_token','{token}');"
            f"localStorage.setItem('autobot_token','{token}');"
        )
        page = ctx.new_page()

        # login page first — no token, so open a clean context
        clean = browser.new_context(viewport=VIEW, device_scale_factor=2)
        lp = clean.new_page()
        lp.goto(BASE + "/#", wait_until="networkidle")
        time.sleep(1.5)
        lp.screenshot(path=str(OUT / "00_login.png"))
        print("00_login:", (lp.inner_text("body")[:60] or "").replace("\n", " "))
        clean.close()

        for name, path, wait, clicks in SHOTS:
            try:
                page.goto(BASE + path, wait_until="networkidle")
            except Exception as e:  # noqa: BLE001
                print(name, "goto warn:", e)
            time.sleep(wait)
            for sel in clicks:
                try:
                    page.click(sel, timeout=2000)
                    time.sleep(1.0)
                except Exception:  # noqa: BLE001
                    pass
            page.screenshot(path=str(OUT / f"{name}.png"))
            sample = (page.inner_text("body")[:70] or "").replace("\n", " ")
            print(f"{name}: {sample}")

        browser.close()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
