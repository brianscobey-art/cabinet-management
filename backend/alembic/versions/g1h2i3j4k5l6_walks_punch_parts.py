"""walks_punch_parts — visit outcomes + trip chaining, part reasons/costs

Post walk, full punch and blue tape are tracked in Autobot/CabinetTron instead
of the punch workbook: a visit now carries what happened (result, notes, photo
folder), the request/confirmation dates the coordinator logs, the closing date
a blue tape has to beat, and a link to the trip it followed. A part carries why
it is needed, who installs it, what it cost and who pays.

Revision ID: g1h2i3j4k5l6
Revises: d3e4f5a6b7c8
"""
import sqlalchemy as sa
from alembic import op

revision = "g1h2i3j4k5l6"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visits", sa.Column("result", sa.String(length=20), nullable=True))
    op.add_column("visits", sa.Column("result_notes", sa.Text(), nullable=True))
    op.add_column("visits", sa.Column("photos_url", sa.String(length=500), nullable=True))
    op.add_column("visits", sa.Column("requested_on", sa.Date(), nullable=True))
    op.add_column("visits", sa.Column("confirmed_with", sa.String(length=120), nullable=True))
    op.add_column("visits", sa.Column("closing_date", sa.Date(), nullable=True))
    op.add_column("visits", sa.Column("return_date", sa.Date(), nullable=True))
    op.add_column("visits", sa.Column("parent_visit_id", sa.Integer(), nullable=True))
    op.add_column("visits", sa.Column("trip", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_visits_parent_visit_id", "visits", ["parent_visit_id"])

    op.add_column("service_parts", sa.Column("reason", sa.String(length=30), nullable=True))
    op.add_column("service_parts", sa.Column("found_on", sa.String(length=20), nullable=True))
    op.add_column("service_parts", sa.Column("install_by", sa.String(length=20), nullable=True))
    op.add_column("service_parts", sa.Column("cost", sa.Numeric(10, 2), nullable=True))
    op.add_column("service_parts", sa.Column("who_pays", sa.String(length=30), nullable=True))
    op.add_column("service_parts", sa.Column("installed_at", sa.Date(), nullable=True))
    op.add_column("service_parts", sa.Column("installed_by", sa.String(length=120), nullable=True))


def downgrade() -> None:
    for col in ("installed_by", "installed_at", "who_pays", "cost", "install_by", "found_on", "reason"):
        op.drop_column("service_parts", col)
    op.drop_index("ix_visits_parent_visit_id", table_name="visits")
    for col in ("trip", "parent_visit_id", "return_date", "closing_date", "confirmed_with",
                "requested_on", "photos_url", "result_notes", "result"):
        op.drop_column("visits", col)
