"""other_labor_net on job_costs and domo_txns table

Revision ID: a1c2e3d4f5b6
Revises: f8bffbec2dbc
Create Date: 2026-07-16 05:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c2e3d4f5b6'
down_revision = 'f8bffbec2dbc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('job_costs', sa.Column('other_labor_net', sa.Numeric(precision=12, scale=2), nullable=True))
    op.create_table(
        'domo_txns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('txn_date', sa.Date(), nullable=True),
        sa.Column('job_field', sa.String(length=80), nullable=True),
        sa.Column('code_type', sa.String(length=1), nullable=True),
        sa.Column('code_prefix', sa.String(length=40), nullable=True),
        sa.Column('sku', sa.String(length=40), nullable=True),
        sa.Column('sales', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('cost', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('job_code', sa.String(length=50), nullable=True),
        sa.Column('account_name', sa.String(length=120), nullable=True),
        sa.Column('community_name', sa.String(length=120), nullable=True),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_domo_txns_txn_date'), 'domo_txns', ['txn_date'])
    op.create_index(op.f('ix_domo_txns_code_type'), 'domo_txns', ['code_type'])
    op.create_index(op.f('ix_domo_txns_code_prefix'), 'domo_txns', ['code_prefix'])
    op.create_index(op.f('ix_domo_txns_sku'), 'domo_txns', ['sku'])
    op.create_index(op.f('ix_domo_txns_job_id'), 'domo_txns', ['job_id'])
    op.create_index(op.f('ix_domo_txns_account_name'), 'domo_txns', ['account_name'])


def downgrade() -> None:
    op.drop_index(op.f('ix_domo_txns_account_name'), table_name='domo_txns')
    op.drop_index(op.f('ix_domo_txns_job_id'), table_name='domo_txns')
    op.drop_index(op.f('ix_domo_txns_sku'), table_name='domo_txns')
    op.drop_index(op.f('ix_domo_txns_code_prefix'), table_name='domo_txns')
    op.drop_index(op.f('ix_domo_txns_code_type'), table_name='domo_txns')
    op.drop_index(op.f('ix_domo_txns_txn_date'), table_name='domo_txns')
    op.drop_table('domo_txns')
    op.drop_column('job_costs', 'other_labor_net')
