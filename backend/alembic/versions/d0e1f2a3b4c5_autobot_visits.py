"""autobot: universal visits, community pins, part gating flags

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-06 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'visits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visit_type', sa.String(length=30), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('community_id', sa.Integer(), nullable=True),
        sa.Column('service_request_id', sa.Integer(), nullable=True),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lon', sa.Float(), nullable=True),
        sa.Column('open_date', sa.Date(), nullable=True),
        sa.Column('close_date', sa.Date(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_min', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='pending'),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.String(length=255), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.ForeignKeyConstraint(['community_id'], ['communities.id']),
        sa.ForeignKeyConstraint(['service_request_id'], ['service_requests.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_visits_visit_type'), 'visits', ['visit_type'])
    op.create_index(op.f('ix_visits_job_id'), 'visits', ['job_id'])
    op.create_index(op.f('ix_visits_community_id'), 'visits', ['community_id'])
    op.create_index(op.f('ix_visits_service_request_id'), 'visits', ['service_request_id'])
    op.create_index(op.f('ix_visits_status'), 'visits', ['status'])

    op.add_column('communities', sa.Column('lat', sa.Float(), nullable=True))
    op.add_column('communities', sa.Column('lon', sa.Float(), nullable=True))

    op.add_column(
        'service_parts',
        sa.Column('trade_blocking', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'service_parts',
        sa.Column('received', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('service_parts', 'received')
    op.drop_column('service_parts', 'trade_blocking')
    op.drop_column('communities', 'lon')
    op.drop_column('communities', 'lat')
    op.drop_index(op.f('ix_visits_status'), table_name='visits')
    op.drop_index(op.f('ix_visits_service_request_id'), table_name='visits')
    op.drop_index(op.f('ix_visits_community_id'), table_name='visits')
    op.drop_index(op.f('ix_visits_job_id'), table_name='visits')
    op.drop_index(op.f('ix_visits_visit_type'), table_name='visits')
    op.drop_table('visits')
