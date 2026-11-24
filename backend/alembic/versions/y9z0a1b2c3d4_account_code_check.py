"""domo_accounts + job_setup_requests + account_code_flags: Account Code Match
check, tracker/CabinetTron I- and G-codes vs DOMO (Brian 11/24/26).

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
"""
import sqlalchemy as sa
from alembic import op

revision = "y9z0a1b2c3d4"
down_revision = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domo_accounts",
        sa.Column("account", sa.String(length=40), primary_key=True),
        sa.Column("kind", sa.String(length=1), nullable=False),
        sa.Column("customer", sa.String(length=200), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("cab_code", sa.String(length=80), nullable=True),
        sa.Column("linked_g", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_domo_accounts_cab_code", "domo_accounts", ["cab_code"])
    op.create_table(
        "job_setup_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_date", sa.Date(), nullable=True),
        sa.Column("ashley_code", sa.String(length=80), nullable=True),
        sa.Column("g_account", sa.String(length=40), nullable=True),
        sa.Column("i_account", sa.String(length=40), nullable=True),
        sa.Column("g_limit", sa.String(length=20), nullable=True),
        sa.Column("i_limit", sa.String(length=20), nullable=True),
        sa.Column("request_no", sa.String(length=20), nullable=True),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("tracker_job_code", sa.String(length=50), nullable=True),
    )
    op.create_table(
        "account_code_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_code", sa.String(length=50), nullable=False),
        sa.Column("field", sa.String(length=1), nullable=False),
        sa.Column("flag", sa.String(length=40), nullable=False),
        sa.Column("stored_code", sa.String(length=40), nullable=True),
        sa.Column("domo_code", sa.String(length=40), nullable=True),
        sa.Column("domo_name", sa.String(length=300), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="open"),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("times_seen", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("job_code", "field", "flag", name="uq_account_code_flag"),
    )
    op.create_index("ix_account_code_flags_job_id", "account_code_flags", ["job_id"])
    op.create_index("ix_account_code_flags_job_code", "account_code_flags", ["job_code"])
    op.create_index("ix_account_code_flags_status", "account_code_flags", ["status"])


def downgrade() -> None:
    op.drop_table("account_code_flags")
    op.drop_table("job_setup_requests")
    op.drop_index("ix_domo_accounts_cab_code", table_name="domo_accounts")
    op.drop_table("domo_accounts")
