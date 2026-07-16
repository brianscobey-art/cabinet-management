"""job po_check_number and po_paid_date

Revision ID: c3e4f5a6b7d8
Revises: b2d3f4a5c6e7
Create Date: 2026-07-16 06:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3e4f5a6b7d8'
down_revision = 'b2d3f4a5c6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('po_check_number', sa.String(length=40), nullable=True))
    op.add_column('jobs', sa.Column('po_paid_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'po_paid_date')
    op.drop_column('jobs', 'po_check_number')
