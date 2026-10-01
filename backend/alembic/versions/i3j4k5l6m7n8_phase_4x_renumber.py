"""Renumber the 4.x phases: Pre Walk added, Electrical + Plumbing merged.

Old ladder            New ladder
4.1 Windows        -> 4.2 Windows Installed
4.2 Roof           -> 4.3 Roof Complete
4.3 Electrical     -> 4.3 Roof Complete   (electrical done but plumbing not:
                                            the highest NEW milestone that is
                                            certainly true is still the roof)
4.4 Plumbing       -> 4.4 Mechanicals Complete
4.5 Insulation     -> 4.5 Insulation Complete (unchanged)
(new) 4.1 Pre Walk Complete

One CASE statement so no row is touched twice. Downgrade folds Mechanicals
back to Plumbing; the Electrical rows that became Roof cannot be told apart
from real Roof rows, so they stay.

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
"""
from alembic import op

revision = "i3j4k5l6m7n8"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE phase_updates SET phase = CASE phase
            WHEN '4.1' THEN '4.2'
            WHEN '4.2' THEN '4.3'
            WHEN '4.3' THEN '4.3'
            WHEN '4.4' THEN '4.4'
            ELSE phase END
        WHERE phase IN ('4.1', '4.2', '4.3', '4.4')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE phase_updates SET phase = CASE phase
            WHEN '4.2' THEN '4.1'
            WHEN '4.3' THEN '4.2'
            WHEN '4.4' THEN '4.4'
            ELSE phase END
        WHERE phase IN ('4.2', '4.3', '4.4')
        """
    )
