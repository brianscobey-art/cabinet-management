"""KSR attribution + sale date (manager sales report)

Adds accounts.ksr (default KSR per account), jobs.ksr (per-job override), and
jobs.sale_date (seeded from the tracker's Cabinet Order Date, editable).

Revision ID: c6d7e8f9a0b1
Revises: b4c5d6e7f8a0
"""
import sqlalchemy as sa
from alembic import op

revision = "c6d7e8f9a0b1"
down_revision = "b4c5d6e7f8a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("ksr", sa.String(length=120), nullable=True))
    op.add_column("jobs", sa.Column("ksr", sa.String(length=120), nullable=True))
    op.add_column("jobs", sa.Column("sale_date", sa.Date(), nullable=True))
    # Cached real driving miles from the Chipley store to the job (OSRM), for the
    # manager report's travel/field-capacity section. Filled lazily; NULL = not
    # yet computed (report falls back to a straight-line estimate meanwhile).
    op.add_column("jobs", sa.Column("base_drive_miles", sa.Float(), nullable=True))

    # Seed a starting default KSR per account from today's reality (national ->
    # Alex, retail -> Paula). Brian reassigns the real reps (Laurie/Paula's
    # accounts) from the account grid; local builders start blank on purpose.
    op.execute(
        "UPDATE accounts SET ksr = 'Alex Talley' "
        "WHERE type = 'builder' AND (name LIKE 'DR Horton%' OR name LIKE 'Century%')"
    )
    op.execute("UPDATE accounts SET ksr = 'Paula Cook' WHERE type = 'retail'")


def downgrade() -> None:
    op.drop_column("jobs", "base_drive_miles")
    op.drop_column("jobs", "sale_date")
    op.drop_column("jobs", "ksr")
    op.drop_column("accounts", "ksr")
