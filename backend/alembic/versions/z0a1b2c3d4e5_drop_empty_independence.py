"""Remove the duplicate "Independence" community (Alex Talley 9/23/26,
Brian OK 11/25/26). "Independence 60's" is the real one; the bare
"Independence" under the same builder has no houses. Its one canceled
phase-check visit moves to Independence 60's (history kept); its duty
assignments (rotation settings for an empty community) go with it.

Only when the bare one still has no jobs and its sibling exists.

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
"""
import sqlalchemy as sa
from alembic import op

revision = "z0a1b2c3d4e5"
down_revision = "y9z0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT a.id AS dup, b.id AS keep FROM communities a JOIN communities b "
        "ON a.account_id = b.account_id AND b.name = 'Independence 60''s' "
        "WHERE a.name = 'Independence'")).fetchall()
    for dup, keep in rows:
        if conn.execute(sa.text("SELECT count(*) FROM jobs WHERE community_id = :d"), {"d": dup}).scalar():
            continue
        conn.execute(sa.text("UPDATE visits SET community_id = :k WHERE community_id = :d"), {"k": keep, "d": dup})
        conn.execute(sa.text("DELETE FROM duty_assignments WHERE community_id = :d"), {"d": dup})
        conn.execute(sa.text("DELETE FROM communities WHERE id = :d"), {"d": dup})


def downgrade() -> None:
    pass  # nothing to restore: the community was empty
