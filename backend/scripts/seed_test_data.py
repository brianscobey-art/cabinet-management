"""Fill the TEST copy of the app with made-up sample data.

Usage (from backend/, on the test service's Shell or locally with the test
DATABASE_URL in the environment):

    APP_ENV=test python -m scripts.seed_test_data admin@example.com "Test Admin"

Prompts for the admin password so it never lands in shell history.

Safety rails:
- refuses to run unless APP_ENV=test (never against the live site),
- refuses to run if the database already holds any job,
- every name, address and dollar figure below is invented. No live customer
  or company data is copied; bringing a sanitized copy of live data over is a
  separate step that waits for Brian's go-ahead (see TESTING.md).
"""

import getpass
import sys
from datetime import date, timedelta
from decimal import Decimal

from app.auth.security import hash_password
from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Account,
    AccountType,
    Community,
    HardwareSelection,
    Job,
    JobStatus,
    JobType,
    Role,
    RoomSelection,
    User,
)

# (lot, status, days from today for install, plan, po amount)
SAMPLE_LOTS = [
    ("101", JobStatus.track, 60, "Sample Plan 1800", "6450.00"),
    ("102", JobStatus.preord, 45, "Sample Plan 1800", "6450.00"),
    ("103", JobStatus.ordsub, 30, "Sample Plan 2200", "7925.00"),
    ("104", JobStatus.ord, 14, "Sample Plan 2200", "7925.00"),
    ("105", JobStatus.inst, 3, "Sample Plan 2600", "9310.00"),
    ("106", JobStatus.ndqw, -2, "Sample Plan 2600", "9310.00"),
    ("107", JobStatus.punch, -15, "Sample Plan 1800", "6450.00"),
    ("108", JobStatus.closed, -60, "Sample Plan 2200", "7925.00"),
]


def seed(db, admin_email: str | None, admin_name: str | None, admin_password: str | None) -> dict:
    """Create the sample records. Split out from main() so tests and the test
    copy's boot bootstrap can call it. Pass admin_email=None to skip the login."""
    if not get_settings().is_test:
        raise SystemExit("Refusing to seed: APP_ENV is not 'test'. This script never runs on live.")
    if db.query(Job.id).first() is not None:
        raise SystemExit("Refusing to seed: this database already has jobs in it.")

    if admin_email and not db.query(User).filter(User.email == admin_email).first():
        db.add(User(email=admin_email, full_name=admin_name,
                    hashed_password=hash_password(admin_password), role=Role.admin))

    builder = Account(name="Sample Builder Homes", type=AccountType.builder,
                      notes="TEST DATA: invented builder account")
    retail = Account(name="Sample Retail Customer", type=AccountType.retail,
                     notes="TEST DATA: invented retail customer")
    db.add_all([builder, retail])
    db.flush()

    community = Community(account_id=builder.id, name="Test Meadows", market="Chipley FL",
                          lat=30.7819, lon=-85.5386)
    db.add(community)
    db.flush()

    today = date.today()
    jobs = []
    for lot, status, offset, plan, amount in SAMPLE_LOTS:
        job = Job(
            job_code=f"TEST-{lot}",
            account_id=builder.id,
            community_id=community.id,
            lot_number=lot,
            address=f"{lot} Sample Lane, Chipley FL 32428",
            job_type=JobType.tract,
            plan=plan,
            status=status,
            install_date=today + timedelta(days=offset),
            sales_contact_name="Sample Purchasing Agent",
            sales_contact_email="purchasing@example.com",
            field_contact_name="Sample Superintendent",
            field_contact_email="super@example.com",
            po_amount=Decimal(amount),
            notes="TEST DATA",
        )
        db.add(job)
        jobs.append(job)

    remodel = Job(
        job_code="TEST-R1",
        account_id=retail.id,
        address="1 Example Street, Chipley FL 32428",
        job_type=JobType.remodel,
        status=JobStatus.preord,
        sales_contact_name="Sample Homeowner",
        sales_contact_email="homeowner@example.com",
        field_contact_name="Sample Homeowner",
        po_amount=Decimal("14800.00"),
        notes="TEST DATA",
    )
    db.add(remodel)
    jobs.append(remodel)
    db.flush()

    for job in jobs:
        db.add_all([
            RoomSelection(job_id=job.id, room="Kitchen", zone="Perimeter",
                          cabinet_brand="Everluxe", series="Sample Series",
                          door_style="Shaker", finish="White"),
            RoomSelection(job_id=job.id, room="Kitchen", zone="Island",
                          cabinet_brand="Everluxe", series="Sample Series",
                          door_style="Shaker", finish="Gray"),
            HardwareSelection(job_id=job.id, room="Kitchen", vendor="Sample Hardware Co",
                              item="5 in. bar pull", qty=24),
        ])
    db.commit()
    return {"accounts": 2, "communities": 1, "jobs": len(jobs), "admin": admin_email}


def main() -> None:
    if len(sys.argv) != 3:
        print('Usage: APP_ENV=test python -m scripts.seed_test_data <admin email> "<full name>"')
        sys.exit(1)
    email, name = sys.argv[1].lower().strip(), sys.argv[2]
    password = getpass.getpass("Password for the test admin: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)
    with SessionLocal() as db:
        print(seed(db, email, name, password))


if __name__ == "__main__":
    main()
