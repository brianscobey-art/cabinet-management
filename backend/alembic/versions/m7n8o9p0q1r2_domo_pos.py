"""domo_pos: our POs per job from DOMO's Purchase Order Details (Brian 10/29/26).

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
"""
import sqlalchemy as sa
from alembic import op

revision = "m7n8o9p0q1r2"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domo_pos",
        sa.Column("our_po", sa.String(length=40), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_account", sa.String(length=40), nullable=True),
        sa.Column("job_name", sa.String(length=120), nullable=True),
        sa.Column("customer", sa.String(length=200), nullable=True),
        sa.Column("vendor", sa.String(length=160), nullable=True),
        sa.Column("product", sa.String(length=200), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("ordered_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("received_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("last_receipt_date", sa.Date(), nullable=True),
        sa.Column("last_receipt_number", sa.String(length=40), nullable=True),
        sa.Column("sales_order", sa.String(length=40), nullable=True),
        sa.Column("salesperson", sa.String(length=120), nullable=True),
        sa.Column("pos", sa.String(length=80), nullable=True),
        sa.Column("lines", sa.Integer(), nullable=True),
    )
    op.create_index("ix_domo_pos_job_id", "domo_pos", ["job_id"])
    op.create_index("ix_domo_pos_job_account", "domo_pos", ["job_account"])


def downgrade() -> None:
    op.drop_index("ix_domo_pos_job_account", table_name="domo_pos")
    op.drop_index("ix_domo_pos_job_id", table_name="domo_pos")
    op.drop_table("domo_pos")
