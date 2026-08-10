"""autobot: workers roster + visit assignment

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-07 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('is_tech', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sales_match', sa.String(length=60), nullable=True),
        sa.Column('home_town', sa.String(length=120), nullable=True),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lon', sa.Float(), nullable=True),
        sa.Column('radius_miles', sa.Float(), nullable=False, server_default='30'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('visits') as batch:
        batch.add_column(sa.Column('assigned_to', sa.Integer(), nullable=True))
        batch.create_index(op.f('ix_visits_assigned_to'), ['assigned_to'])
        batch.create_foreign_key('fk_visits_assigned_to_workers', 'workers', ['assigned_to'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('visits') as batch:
        batch.drop_constraint('fk_visits_assigned_to_workers', type_='foreignkey')
        batch.drop_index(op.f('ix_visits_assigned_to'))
        batch.drop_column('assigned_to')
    op.drop_table('workers')
