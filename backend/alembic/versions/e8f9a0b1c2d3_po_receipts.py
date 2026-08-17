"""PO receipts (DOMO PO Receipt List) + POTracker PO->job map

Revision ID: e8f9a0b1c2d3
Revises: a1b2c3d4e5f6
"""
import sqlalchemy as sa
from alembic import op

revision = "e8f9a0b1c2d3"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "po_receipts",
        sa.Column("receipt_number", sa.String(length=40), primary_key=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("pos", sa.String(length=80), nullable=True),
        sa.Column("supplier", sa.String(length=120), nullable=True),
        sa.Column("supplier_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("landed_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("order_number", sa.String(length=40), nullable=True),
    )
    op.create_index("ix_po_receipts_order_number", "po_receipts", ["order_number"])
    op.create_table(
        "job_pos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("our_po", sa.String(length=40), nullable=True),
        sa.Column("job_code", sa.String(length=50), nullable=True),
        sa.Column("vendor", sa.String(length=120), nullable=True),
        sa.Column("product", sa.String(length=200), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("tent_due_date", sa.Date(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
    )
    op.create_index("ix_job_pos_our_po", "job_pos", ["our_po"])
    op.create_index("ix_job_pos_job_code", "job_pos", ["job_code"])
    op.create_index("ix_job_pos_our_po_job", "job_pos", ["our_po", "job_code"])


def downgrade() -> None:
    op.drop_table("job_pos")
    op.drop_index("ix_po_receipts_order_number", table_name="po_receipts")
    op.drop_table("po_receipts")
