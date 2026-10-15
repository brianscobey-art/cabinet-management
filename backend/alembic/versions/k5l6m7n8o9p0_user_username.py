"""users.username — "first.last" sign-in name (Brian 10/15/26), backfilled from full_name.

Passwords and emails are untouched: the email stays the record key (JWT
subject, invites) and either the username or the email signs you in.

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
"""
import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def derive_username(full_name: str, email: str) -> str:
    """'Brian Scobey' -> 'brian.scobey'; 'Mary Ann O'Neil' -> 'mary.oneil';
    a one-word name uses the email's local part."""
    name = unicodedata.normalize("NFKD", full_name or "").encode("ascii", "ignore").decode()
    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in name.split()]
    words = [w for w in words if w]
    if len(words) >= 2:
        return f"{words[0]}.{words[-1]}"
    local = re.sub(r"[^a-z0-9.]", "", (email or "").split("@")[0].lower())
    return local or (words[0] if words else "user")


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, email, full_name FROM users ORDER BY id")).fetchall()
    taken: set[str] = set()
    for uid, email, full_name in rows:
        base = derive_username(full_name, email)
        name, n = base, 2
        while name in taken:
            name = f"{base}{n}"
            n += 1
        taken.add(name)
        conn.execute(sa.text("UPDATE users SET username = :u WHERE id = :id"), {"u": name, "id": uid})
        # Brian 10/15/26: everyone's address moved to @carterlumber.com. The
        # local part follows the username, so brian.scobey@townsendbuildingsupply.com
        # becomes brian.scobey@carterlumber.com. Addresses on any other domain
        # (test accounts, outside vendors) are left alone.
        if (email or "").lower().endswith("@townsendbuildingsupply.com"):
            new_email = f"{name}@carterlumber.com"
            clash = conn.execute(sa.text("SELECT id FROM users WHERE lower(email) = :e AND id <> :id"),
                                 {"e": new_email, "id": uid}).fetchone()
            if clash is None:
                conn.execute(sa.text("UPDATE users SET email = :e WHERE id = :id"), {"e": new_email, "id": uid})
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "username")
