"""install_reports + qc_reports: field reports read from Smartsheet (Brian 10/30/26).

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
"""
import sqlalchemy as sa
from alembic import op

revision = "o9p0q1r2s3t4"
down_revision = "n8o9p0q1r2s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "install_reports",
        sa.Column("row_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_code", sa.String(length=50), nullable=True),
        sa.Column("install_date", sa.Date(), nullable=True),
        sa.Column("installer", sa.String(length=120), nullable=True),
        sa.Column("complete", sa.Boolean(), nullable=True),
        sa.Column("trade_stopping", sa.Boolean(), nullable=True),
        sa.Column("needed_to_finish", sa.Text(), nullable=True),
        sa.Column("shoe_sticks", sa.Float(), nullable=True),
        sa.Column("damage_parts", sa.Boolean(), nullable=True),
        sa.Column("damage_detail", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actions", sa.String(length=300), nullable=True),
    )
    op.create_index("ix_install_reports_job_id", "install_reports", ["job_id"])
    op.create_index("ix_install_reports_job_code", "install_reports", ["job_code"])
    op.create_table(
        "qc_reports",
        sa.Column("row_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_code", sa.String(length=50), nullable=True),
        sa.Column("pwid", sa.String(length=20), nullable=True),
        sa.Column("walked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("walked_by", sa.String(length=255), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("answers", sa.Text(), nullable=True),
        sa.Column("visit_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_qc_reports_job_id", "qc_reports", ["job_id"])
    op.create_index("ix_qc_reports_job_code", "qc_reports", ["job_code"])


def downgrade() -> None:
    op.drop_table("qc_reports")
    op.drop_table("install_reports")
