"""The six New Orders Status columns CabinetTron didn't hold

CabinetTron already carries ~33 of that workbook's 39 columns. These are the
rest, so the app can own the sheet outright instead of reading someone else's
file: Setup Date, Carter SO #, and the four lumber counts plus Misc that come
off the floorplan callouts.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

COLS = [
    ("setup_date", sa.Date()),
    ("carter_so_number", sa.String(50)),
    ("lumber_2x4x8", sa.Integer()),
    ("lumber_1x4x8", sa.Integer()),
    ("lumber_1x6x8", sa.Integer()),
    ("plywood_half", sa.Integer()),
    ("misc_materials", sa.String(200)),
]


def upgrade() -> None:
    for name, type_ in COLS:
        op.add_column("ordering_checklists", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLS):
        op.drop_column("ordering_checklists", name)
