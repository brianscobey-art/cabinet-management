"""layout_prints — which stamped layout went to the printer for each field measure.

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
"""
import sqlalchemy as sa
from alembic import op

revision = "j4k5l6m7n8o9"
down_revision = "i3j4k5l6m7n8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "layout_prints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("batch_id", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=400), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("reprint", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("measured_date", sa.Date(), nullable=True),
        sa.Column("printed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("printed_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_layout_prints_job_id", "layout_prints", ["job_id"])
    op.create_index("ix_layout_prints_batch_id", "layout_prints", ["batch_id"])
    op.create_index("ix_layout_prints_printed_at", "layout_prints", ["printed_at"])


def downgrade() -> None:
    op.drop_index("ix_layout_prints_printed_at", table_name="layout_prints")
    op.drop_index("ix_layout_prints_batch_id", table_name="layout_prints")
    op.drop_index("ix_layout_prints_job_id", table_name="layout_prints")
    op.drop_table("layout_prints")
