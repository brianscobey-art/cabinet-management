"""field_measure_notes.sent_at / sent_by / sent_to: notes compiled and sent to
Alex from Reports > Field Measure Notes, so none go twice (Brian 11/11/26).

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
"""
import sqlalchemy as sa
from alembic import op

revision = "v6w7x8y9z0a1"
down_revision = "u5v6w7x8y9z0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("field_measure_notes") as batch:
        batch.add_column(sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("sent_by", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("sent_to", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("field_measure_notes") as batch:
        batch.drop_column("sent_to")
        batch.drop_column("sent_by")
        batch.drop_column("sent_at")
