"""autobot: local-only workers (national_ok flag)

Revision ID: b4c5d6e7f8a0
Revises: a3b4c5d6e7f9
Create Date: 2026-08-07 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a0'
down_revision = 'a3b4c5d6e7f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'workers',
        sa.Column('national_ok', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column('workers', 'national_ok')
