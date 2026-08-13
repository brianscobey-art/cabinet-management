"""app_settings key/value store (manager report share token, etc.)

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
"""
import sqlalchemy as sa
from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
