"""job_costs.wash_labor_codes (per-code excluded overhead breakdown)

Revision ID: d4f5a6b7c8e9
Revises: c3e4f5a6b7d8
Create Date: 2026-07-16 06:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4f5a6b7c8e9'
down_revision = 'c3e4f5a6b7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('job_costs', sa.Column('wash_labor_codes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_costs', 'wash_labor_codes')
