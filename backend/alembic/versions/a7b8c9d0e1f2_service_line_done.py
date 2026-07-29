"""service line done/note for the field service report

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('service_lines', sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('service_lines', sa.Column('done_by', sa.String(length=255), nullable=True))
    op.add_column('service_lines', sa.Column('done_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('service_lines', sa.Column('note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('service_lines', 'note')
    op.drop_column('service_lines', 'done_at')
    op.drop_column('service_lines', 'done_by')
    op.drop_column('service_lines', 'done')
