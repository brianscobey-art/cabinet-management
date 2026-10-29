"""jobs.delivery_instructions for the job page's Jobsite card, and the KSR ->
sales contact backfill (Brian 10/29/26).

Picking a KSR now makes them the job's sales contact (app.api.jobs). Jobs that
already had a KSR picked keep a stale contact (PDAG0556: KSR Paula Cook, sales
contact Brian), so copy the KSR over once here.

Also job_notes.topic (Sales / Delivery / Installation / Service / Warranty / Misc).

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
"""
import sqlalchemy as sa
from alembic import op

revision = "l6m7n8o9p0q1"
down_revision = "k5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("delivery_instructions", sa.Text(), nullable=True))
    op.add_column("job_notes", sa.Column("topic", sa.String(length=20), nullable=True))
    op.execute(
        "UPDATE jobs SET sales_contact_name = ksr, "
        "sales_contact_phone = CASE WHEN ksr = 'Brian Scobey' THEN '850-890-0482' ELSE NULL END, "
        "sales_contact_email = (SELECT u.email FROM users u "
        "  WHERE lower(u.full_name) = lower(jobs.ksr) AND u.is_active ORDER BY u.id LIMIT 1) "
        "WHERE ksr IS NOT NULL AND ksr <> ''"
    )


def downgrade() -> None:
    op.drop_column("job_notes", "topic")
    op.drop_column("jobs", "delivery_instructions")
