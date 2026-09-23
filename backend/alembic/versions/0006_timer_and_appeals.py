"""self-destruct timer + ban appeals (docs/07 D1, D5)

* ``messages.self_destruct_at`` — ``/timer 24h`` marks the user's own relayed
  copy; a beat sweep deletes it from Telegram once the moment passes. The bot
  owns every topic message, which is what makes this possible at all.
* ``ban_appeals`` — a banned or muted user can ask the staff to reconsider
  (``/appeal``). Moderators decide in the panel; approval lifts the ban through
  the existing audited ``SecurityService.unban``.

Both guarded by inspector checks: fresh ``create_all`` installs already have
them, older databases get them here.

Revision ID: 0006_timer_and_appeals
Revises: 0005_memories
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_timer_and_appeals"
down_revision: str | None = "0005_memories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    if "messages" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("messages")}
        if "self_destruct_at" not in columns:
            op.add_column("messages", sa.Column("self_destruct_at", sa.DateTime(timezone=True), nullable=True))

    if "ban_appeals" not in inspector.get_table_names():
        op.create_table(
            "ban_appeals",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("tg_id", sa.BigInteger(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("decided_by", sa.Integer(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ban_appeals_tg_id", "ban_appeals", ["tg_id"])
        op.create_index("ix_appeal_status", "ban_appeals", ["status", "id"])


def downgrade() -> None:
    inspector = _inspector()
    if "ban_appeals" in inspector.get_table_names():
        op.drop_index("ix_appeal_status", table_name="ban_appeals")
        op.drop_index("ix_ban_appeals_tg_id", table_name="ban_appeals")
        op.drop_table("ban_appeals")
    if "messages" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("messages")}
        if "self_destruct_at" in columns:
            op.drop_column("messages", "self_destruct_at")
