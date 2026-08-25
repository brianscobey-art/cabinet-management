"""Carter PO Date — the last New Orders Status column with no home

Missed in c2d3e4f5a6b7. It is populated on 113 of 129 rows, so generating the
workbook without it would blank a real column.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ordering_checklists", sa.Column("carter_po_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("ordering_checklists", "carter_po_date")
