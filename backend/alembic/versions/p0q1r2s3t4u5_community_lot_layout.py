"""communities.lot_layout: manual override for how Autobot orders houses inside a
community (None = auto from pin spread, compact = lot order, scattered = fastest)
(Brian 10/30/26).

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
"""
import sqlalchemy as sa
from alembic import op

revision = "p0q1r2s3t4u5"
down_revision = "o9p0q1r2s3t4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("communities") as batch:
        batch.add_column(sa.Column("lot_layout", sa.String(length=12), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("communities") as batch:
        batch.drop_column("lot_layout")
