"""so_amount — the vendor SO total for Optimus's Ordered page

Kept separate from so_total, which is Order Pack's stage-4 dollar gate
(SO vs Carter PO) and must only ever be written by that agent.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
"""
import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ordering_checklists", sa.Column("so_amount", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("ordering_checklists", "so_amount")
