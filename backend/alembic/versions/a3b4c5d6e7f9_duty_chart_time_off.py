"""autobot: per-community duty chart + worker time off

Revision ID: a3b4c5d6e7f9
Revises: f2a3b4c5d6e7
Create Date: 2026-08-07 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3b4c5d6e7f9'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'worker_time_off',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_worker_time_off_worker_id'), 'worker_time_off', ['worker_id'])
    op.create_table(
        'duty_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('community_id', sa.Integer(), nullable=False),
        sa.Column('duty', sa.String(length=30), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['community_id'], ['communities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('community_id', 'duty', name='uq_duty_community_task'),
    )
    op.create_index(op.f('ix_duty_assignments_community_id'), 'duty_assignments', ['community_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_duty_assignments_community_id'), table_name='duty_assignments')
    op.drop_table('duty_assignments')
    op.drop_index(op.f('ix_worker_time_off_worker_id'), table_name='worker_time_off')
    op.drop_table('worker_time_off')
