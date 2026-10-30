"""Four-digit lot numbers for DR Horton houses the Vendor Suite feed created
with the zeros stripped (lot "65" on DRLB50-0065). Only padded where the job
code's own 4-digit suffix proves it (Brian 10/30/26).

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "r2s3t4u5v6w7"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, job_code, lot_number FROM jobs WHERE job_code LIKE 'DR%' AND lot_number IS NOT NULL"
    )).fetchall()
    for job_id, code, lot in rows:
        lot = (lot or "").strip()
        m = re.search(r"-(\d{4})$", code or "")
        if not m or not lot.isdigit() or len(lot) >= 4:
            continue
        if lot.lstrip("0") != m.group(1).lstrip("0"):
            continue  # the code and the lot disagree — leave it for a person
        conn.execute(sa.text("UPDATE jobs SET lot_number = :lot WHERE id = :id"),
                     {"lot": m.group(1), "id": job_id})


def downgrade() -> None:
    pass  # padding is harmless; nothing to undo
