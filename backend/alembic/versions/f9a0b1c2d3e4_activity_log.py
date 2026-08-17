"""activity_log — who did what, when

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""
import sqlalchemy as sa
from alembic import op

revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("entity", sa.String(length=60), nullable=True),
        sa.Column("entity_id", sa.String(length=40), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=60), nullable=True),
    )
    op.create_index("ix_activity_log_at", "activity_log", ["at"])
    op.create_index("ix_activity_log_user_email", "activity_log", ["user_email"])
    op.create_index("ix_activity_log_entity", "activity_log", ["entity"])
    op.create_index("ix_activity_at_user", "activity_log", ["at", "user_email"])


def downgrade() -> None:
    op.drop_table("activity_log")
