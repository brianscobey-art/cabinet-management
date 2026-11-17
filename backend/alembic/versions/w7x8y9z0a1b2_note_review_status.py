"""notes.review_status: a job sent up with "Submit for Review" is pending,
then approved or held (Brian 11/17/26).

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
"""
import sqlalchemy as sa
from alembic import op

revision = "w7x8y9z0a1b2"
down_revision = "v6w7x8y9z0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notes") as batch:
        batch.add_column(sa.Column("review_status", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notes") as batch:
        batch.drop_column("review_status")
