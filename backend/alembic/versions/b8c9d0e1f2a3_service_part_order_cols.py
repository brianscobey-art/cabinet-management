"""service part style/color/vendor/order columns

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-30 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('service_parts', sa.Column('style', sa.String(length=100), nullable=True))
    op.add_column('service_parts', sa.Column('color', sa.String(length=100), nullable=True))
    op.add_column('service_parts', sa.Column('vendor', sa.String(length=120), nullable=True))
    op.add_column('service_parts', sa.Column('order_number', sa.String(length=60), nullable=True))
    op.add_column('service_parts', sa.Column('order_date', sa.Date(), nullable=True))
    op.add_column('service_parts', sa.Column('due_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('service_parts', 'due_date')
    op.drop_column('service_parts', 'order_date')
    op.drop_column('service_parts', 'order_number')
    op.drop_column('service_parts', 'vendor')
    op.drop_column('service_parts', 'color')
    op.drop_column('service_parts', 'style')
