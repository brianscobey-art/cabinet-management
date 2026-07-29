"""service requests: parts + labor lines

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-17 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'service_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_service_requests_job_id'), 'service_requests', ['job_id'])
    op.create_table(
        'service_parts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('service_request_id', sa.Integer(), nullable=False),
        sa.Column('part', sa.String(length=200), nullable=False),
        sa.Column('cabinet', sa.String(length=100), nullable=True),
        sa.Column('qty', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['service_request_id'], ['service_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_service_parts_service_request_id'), 'service_parts', ['service_request_id'])
    op.create_table(
        'service_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('service_request_id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=True),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['service_request_id'], ['service_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['part_id'], ['service_parts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_service_lines_service_request_id'), 'service_lines', ['service_request_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_service_lines_service_request_id'), table_name='service_lines')
    op.drop_table('service_lines')
    op.drop_index(op.f('ix_service_parts_service_request_id'), table_name='service_parts')
    op.drop_table('service_parts')
    op.drop_index(op.f('ix_service_requests_job_id'), table_name='service_requests')
    op.drop_table('service_requests')
