"""COAST suite: job timeline (job_events) and the Tailgate installer on a job.

Adds only. Nothing existing changes, so it is safe to run on a copy of live
data in the test environment first.

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
    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("job_code", sa.String(50), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("level", sa.String(10), nullable=False, server_default="ok"),
        sa.Column("issues", sa.JSON(), nullable=True),
        sa.Column("hold_code", sa.String(40), nullable=True),
        sa.Column("status_from", sa.String(20), nullable=True),
        sa.Column("status_to", sa.String(20), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_event", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for col in ("job_id", "job_code", "source", "kind", "level", "hold_code", "created_at"):
        op.create_index(f"ix_job_events_{col}", "job_events", [col])
    op.add_column("jobs", sa.Column("installer", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "installer")
    for col in ("job_id", "job_code", "source", "kind", "level", "hold_code", "created_at"):
        op.drop_index(f"ix_job_events_{col}", table_name="job_events")
    op.drop_table("job_events")
