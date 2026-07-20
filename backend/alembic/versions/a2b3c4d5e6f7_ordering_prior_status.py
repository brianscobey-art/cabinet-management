"""ordering prior status for undo

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-07-20

"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f7'
down_revision = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ordering_checklists') as batch:
        batch.add_column(sa.Column('prior_status', sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ordering_checklists') as batch:
        batch.drop_column('prior_status')
