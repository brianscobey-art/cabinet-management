"""wash_labor_net on job_costs

Revision ID: b2d3f4a5c6e7
Revises: a1c2e3d4f5b6
Create Date: 2026-07-16 05:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2d3f4a5c6e7'
down_revision = 'a1c2e3d4f5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('job_costs', sa.Column('wash_labor_net', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('job_costs', 'wash_labor_net')
