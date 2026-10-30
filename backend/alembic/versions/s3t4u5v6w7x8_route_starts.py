"""route_starts: the Start route button — when and where someone actually headed
out today, so today's plan re-times from there (Brian 10/30/26).

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
"""
import sqlalchemy as sa
from alembic import op

revision = "s3t4u5v6w7x8"
down_revision = "r2s3t4u5v6w7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_starts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("workers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("started_by", sa.String(length=120), nullable=True),
        sa.UniqueConstraint("worker_id", "day", name="uq_route_start_worker_day"),
    )
    op.create_index("ix_route_starts_worker_id", "route_starts", ["worker_id"])


def downgrade() -> None:
    op.drop_index("ix_route_starts_worker_id", table_name="route_starts")
    op.drop_table("route_starts")