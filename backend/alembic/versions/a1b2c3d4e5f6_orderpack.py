"""Order Pack: physical-folder + stage columns on ordering_checklists, pack_runs queue

Phase A of the Order Pack build. The new columns on ordering_checklists carry
everything "New Orders Status.xlsx" used to hold, so the spreadsheet retires;
they live on the SAME table Optimus reads so there is one record and no drift.

Revision ID: a1b2c3d4e5f6
Revises: d7e8f9a0b1c2
"""
import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None

# (name, type, index?)
_COLUMNS = [
    ("buid", sa.String(length=9), True),
    ("plan_abbr", sa.String(length=20), False),
    ("elevation", sa.String(length=10), False),
    ("swing", sa.String(length=20), False),
    ("sub_number", sa.String(length=10), False),
    ("folder_name", sa.String(length=200), False),
    ("current_folder", sa.String(length=40), True),
    ("selections_file", sa.String(length=200), False),
    ("po_file", sa.String(length=200), False),
    ("summary_file", sa.String(length=200), False),
    ("folder_files", sa.JSON(), False),
    ("po_date", sa.Date(), False),
    ("po_total", sa.Numeric(12, 2), False),
    ("so_total", sa.Numeric(12, 2), False),
    ("moved_to_sold_date", sa.Date(), False),
    ("installer_pay_sheet", sa.Boolean(), False),
    ("install_pay", sa.Numeric(12, 2), False),
    ("exception", sa.Text(), False),
    ("last_scan_at", sa.DateTime(timezone=True), False),
]


def upgrade() -> None:
    with op.batch_alter_table("ordering_checklists") as batch:
        for name, type_, _ in _COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))
    for name, _, indexed in _COLUMNS:
        if indexed:
            op.create_index(f"ix_ordering_checklists_{name}", "ordering_checklists", [name])

    op.create_table(
        "pack_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="scan"),
        sa.Column("stage", sa.Integer(), nullable=True),
        sa.Column("job_ids", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("log", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_pack_runs_status", "pack_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pack_runs_status", table_name="pack_runs")
    op.drop_table("pack_runs")
    for name, _, indexed in _COLUMNS:
        if indexed:
            op.drop_index(f"ix_ordering_checklists_{name}", table_name="ordering_checklists")
    with op.batch_alter_table("ordering_checklists") as batch:
        for name, _, _ in _COLUMNS:
            batch.drop_column(name)
