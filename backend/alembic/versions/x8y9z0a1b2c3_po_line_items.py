"""po_line_items + i_account_lines: item-level PO detail from DOMO's PO
drill-down card, and the I-Account Detail email (Brian 11/24/26).

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
"""
import sqlalchemy as sa
from alembic import op

revision = "x8y9z0a1b2c3"
down_revision = "w7x8y9z0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "po_line_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("po_number", sa.String(length=40), nullable=False),
        sa.Column("line_type", sa.String(length=10), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("supplier_id", sa.String(length=20), nullable=True),
        sa.Column("supplier_name", sa.String(length=160), nullable=True),
        sa.Column("vendor_alias", sa.String(length=80), nullable=True),
        sa.Column("carter_sku", sa.String(length=200), nullable=True),
        sa.Column("item_code", sa.String(length=200), nullable=True),
        sa.Column("qty_ordered", sa.Numeric(12, 2), nullable=True),
        sa.Column("ordered_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("qty_received", sa.Numeric(12, 2), nullable=True),
        sa.Column("received_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("account", sa.String(length=40), nullable=True),
        sa.Column("account_name", sa.String(length=200), nullable=True),
        sa.Column("cab_job_code", sa.String(length=60), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("salesperson", sa.String(length=120), nullable=True),
        sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("po_number", "account", "cab_job_code", "job_id"):
        op.create_index(f"ix_po_line_items_{col}", "po_line_items", [col])
    op.create_table(
        "i_account_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("g_account", sa.String(length=40), nullable=True),
        sa.Column("i_account", sa.String(length=40), nullable=True),
        sa.Column("i_account_name", sa.String(length=200), nullable=True),
        sa.Column("sku", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("sales", sa.Numeric(12, 2), nullable=True),
    )
    op.create_index("ix_i_account_lines_g_account", "i_account_lines", ["g_account"])
    op.create_index("ix_i_account_lines_i_account", "i_account_lines", ["i_account"])


def downgrade() -> None:
    op.drop_table("i_account_lines")
    op.drop_table("po_line_items")
