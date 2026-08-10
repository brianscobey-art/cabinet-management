"""autobot: per-job lat/lon pins

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-07 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('lat', sa.Float(), nullable=True))
    op.add_column('jobs', sa.Column('lon', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'lon')
    op.drop_column('jobs', 'lat')
