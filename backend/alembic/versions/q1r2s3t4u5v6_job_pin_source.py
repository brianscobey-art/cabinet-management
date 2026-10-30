"""jobs.pin_source / pin_address / pin_at / pin_by: hand-set house pins from the
field and re-pinning when an address changes (Brian 10/30/26).

Existing pins are stamped as Google lookups made for the current address, so
nothing re-geocodes on deploy.

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
"""
import sqlalchemy as sa
from alembic import op

revision = "q1r2s3t4u5v6"
down_revision = "p0q1r2s3t4u5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("pin_source", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("pin_address", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("pin_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("pin_by", sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE jobs SET pin_source = 'google', pin_address = address "
        "WHERE lat IS NOT NULL AND lon IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("pin_by")
        batch.drop_column("pin_at")
        batch.drop_column("pin_address")
        batch.drop_column("pin_source")
