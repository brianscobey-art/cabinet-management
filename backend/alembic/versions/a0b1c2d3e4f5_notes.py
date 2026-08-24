"""Team notes / tasks (notes, note_tags, note_reads)

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
"""
import sqlalchemy as sa
from alembic import op

revision = "a0b1c2d3e4f5"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("note_type", sa.String(length=16), nullable=False, server_default="fyi"),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("author_email", sa.String(length=255), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("assignee_email", sa.String(length=255), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.String(length=255), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("notes.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("job_id", "author_email", "assignee_email", "parent_id", "created_at"):
        op.create_index(f"ix_notes_{col}", "notes", [col])

    op.create_table(
        "note_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("notes.id"), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=False),
    )
    op.create_index("ix_note_tags_note_id", "note_tags", ["note_id"])
    op.create_index("ix_note_tags_user_note", "note_tags", ["user_email", "note_id"], unique=True)

    op.create_table(
        "note_reads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("notes.id"), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_note_reads_note_id", "note_reads", ["note_id"])
    op.create_index("ix_note_reads_user_note", "note_reads", ["user_email", "note_id"], unique=True)


def downgrade() -> None:
    op.drop_table("note_reads")
    op.drop_table("note_tags")
    op.drop_table("notes")
