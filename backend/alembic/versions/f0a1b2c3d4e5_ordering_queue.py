"""ordering queue flag

Revision ID: f0a1b2c3d4e5
Revises: e5a6b7c8d9f0
Create Date: 2026-07-20

"""
from alembic import op
import sqlalchemy as sa


revision = 'f0a1b2c3d4e5'
down_revision = 'e5a6b7c8d9f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ordering_checklists') as batch:
        batch.add_column(sa.Column('queued', sa.Boolean(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('queued_at', sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ordering_checklists') as batch:
        batch.drop_column('queued_at')
        batch.drop_column('queued')
