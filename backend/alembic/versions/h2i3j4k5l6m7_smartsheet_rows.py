"""smartsheet_rows + smartsheet_history — Tract Builder Management feed

The Smartsheet sheets carry ~250 columns each and the eleven builders do not
agree on which of them exist, so the row is stored as JSON with only the join
key and the cabinet flag lifted out. History stores a SPAN per field per value
rather than a row per field per day: an unchanged field costs one date update,
which is what makes "this has been blank for 24 days" cheap to answer.

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
"""
import sqlalchemy as sa
from alembic import op

revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smartsheet_rows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sheet", sa.String(length=64), nullable=False),
        sa.Column("sheet_id", sa.String(length=32), nullable=True),
        sa.Column("row_id", sa.String(length=32), nullable=True),
        sa.Column("key_sub", sa.String(length=120), nullable=False),
        sa.Column("key_lot", sa.String(length=40), nullable=False),
        sa.Column("subdivision", sa.String(length=160), nullable=True),
        sa.Column("lot", sa.String(length=40), nullable=True),
        sa.Column("has_cabinets", sa.Boolean(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smartsheet_rows_sheet", "smartsheet_rows", ["sheet"])
    op.create_index("ix_smartsheet_rows_has_cabinets", "smartsheet_rows", ["has_cabinets"])
    op.create_index("ix_smartsheet_rows_key", "smartsheet_rows", ["key_sub", "key_lot"])

    op.create_table(
        "smartsheet_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key_sub", sa.String(length=120), nullable=False),
        sa.Column("key_lot", sa.String(length=40), nullable=False),
        sa.Column("field", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.Column("days_held", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smartsheet_history_key", "smartsheet_history",
                    ["key_sub", "key_lot", "field"])


def downgrade() -> None:
    op.drop_index("ix_smartsheet_history_key", table_name="smartsheet_history")
    op.drop_table("smartsheet_history")
    for name in ("ix_smartsheet_rows_key", "ix_smartsheet_rows_has_cabinets",
                 "ix_smartsheet_rows_sheet"):
        op.drop_index(name, table_name="smartsheet_rows")
    op.drop_table("smartsheet_rows")
