"""topic memories (/remember)

``Memory`` stores the facts a couple saves on purpose (``/remember yayragan
joyimiz Buxoro``). The panel can export them with the archive and the bot can
list them with ``/memory``.

Guarded by an inspector check: fresh ``create_all`` installs already have the
table, databases created before this revision get it here.

Revision ID: 0005_memories
Revises: 0004_backup_target_widen
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_memories"
down_revision: str | None = "0004_backup_target_widen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("memories"):
        return
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_topic", "memories", ["topic_id", "id"])
    op.create_index("ix_memories_topic_id", "memories", ["topic_id"])


def downgrade() -> None:
    if not _has_table("memories"):
        return
    op.drop_index("ix_memory_topic", table_name="memories")
    op.drop_index("ix_memories_topic_id", table_name="memories")
    op.drop_table("memories")
