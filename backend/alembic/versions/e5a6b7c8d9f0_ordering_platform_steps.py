"""ordering platform sub-steps and reference numbers

Revision ID: e5a6b7c8d9f0
Revises: d4f5a6b7c8e9
Create Date: 2026-07-20

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5a6b7c8d9f0'
down_revision = 'd4f5a6b7c8e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ordering_checklists') as batch:
        batch.add_column(sa.Column('steps', sa.JSON(), nullable=False, server_default='{}'))
        batch.add_column(sa.Column('po_number', sa.String(length=50), nullable=True))
        batch.add_column(sa.Column('so_number', sa.String(length=50), nullable=True))
        batch.add_column(sa.Column('carter_po_number', sa.String(length=50), nullable=True))
        batch.add_column(sa.Column('vendor', sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ordering_checklists') as batch:
        batch.drop_column('vendor')
        batch.drop_column('carter_po_number')
        batch.drop_column('so_number')
        batch.drop_column('po_number')
        batch.drop_column('steps')
