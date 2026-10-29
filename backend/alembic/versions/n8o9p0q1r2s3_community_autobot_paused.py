"""communities.autobot_paused: hold a community out of Autobot without touching
its jobs (Brian 10/29/26, Clear Lake Estates POs being voided).

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
"""
import sqlalchemy as sa
from alembic import op

revision = "n8o9p0q1r2s3"
down_revision = "m7n8o9p0q1r2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("communities") as batch:
        batch.add_column(
            sa.Column("autobot_paused", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("communities") as batch:
        batch.drop_column("autobot_paused")
