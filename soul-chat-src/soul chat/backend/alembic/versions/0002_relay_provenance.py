"""relay provenance + stored admin password hash

Adds what the edit mirror and the admin login need:

* ``messages.source_message_id`` — the private-message id a relayed line came
  from; makes a redelivered Telegram update idempotent.
* ``messages.edited`` — the relayed copy changed after it was posted.
* ``users.password_hash`` — a real credential instead of the derived bootstrap hash.

``0001_initial`` builds the schema from the ORM metadata, so on a *fresh*
database these objects already exist. Every step here is therefore guarded by an
inspector check: the migration is a no-op on a fresh install and applies cleanly
to a database created before this revision.

Revision ID: 0002_relay_provenance
Revises: 0001_initial
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_relay_provenance"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return name in {i["name"] for i in _inspector().get_indexes(table)}


def upgrade() -> None:
    if not _has_column("messages", "source_message_id"):
        op.add_column("messages", sa.Column("source_message_id", sa.BigInteger(), nullable=True))
    if not _has_column("messages", "edited"):
        op.add_column(
            "messages",
            sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_index("messages", "ix_messages_source_message_id"):
        op.create_index("ix_messages_source_message_id", "messages", ["source_message_id"])
    if not _has_index("messages", "ix_message_source"):
        # Partial index: only relayed DM copies carry a source id, so only those
        # rows participate. Without the WHERE clause two group messages (source
        # NULL) would violate the uniqueness constraint.
        op.create_index(
            "ix_message_source",
            "messages",
            ["topic_id", "sender_id", "source_message_id"],
            unique=True,
            postgresql_where=sa.text("source_message_id IS NOT NULL"),
            sqlite_where=sa.text("source_message_id IS NOT NULL"),
        )
    if not _has_column("users", "password_hash"):
        op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    if _has_column("users", "password_hash"):
        op.drop_column("users", "password_hash")
    if _has_index("messages", "ix_message_source"):
        op.drop_index("ix_message_source", table_name="messages")
    if _has_index("messages", "ix_messages_source_message_id"):
        op.drop_index("ix_messages_source_message_id", table_name="messages")
    if _has_column("messages", "edited"):
        op.drop_column("messages", "edited")
    if _has_column("messages", "source_message_id"):
        op.drop_column("messages", "source_message_id")