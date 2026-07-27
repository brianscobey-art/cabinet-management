"""field measure verification tables

Revision ID: e5f6a7b8c9d0
Revises: a2b3c4d5e6f7
Create Date: 2026-07-17 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'field_measures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('complete_date', sa.Date(), nullable=True),
        sa.Column('correct', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('correct_by', sa.String(length=255), nullable=True),
        sa.Column('correct_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('incorrect', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('incorrect_by', sa.String(length=255), nullable=True),
        sa.Column('incorrect_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('super_notified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('super_notified_by', sa.String(length=255), nullable=True),
        sa.Column('super_notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_field_measures_job_id'), 'field_measures', ['job_id'], unique=True)
    op.create_table(
        'field_measure_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('author', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_field_measure_notes_job_id'), 'field_measure_notes', ['job_id'])
    op.create_index(op.f('ix_field_measure_notes_created_at'), 'field_measure_notes', ['created_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_field_measure_notes_created_at'), table_name='field_measure_notes')
    op.drop_index(op.f('ix_field_measure_notes_job_id'), table_name='field_measure_notes')
    op.drop_table('field_measure_notes')
    op.drop_index(op.f('ix_field_measures_job_id'), table_name='field_measures')
    op.drop_table('field_measures')
