"""trigram indexes for substring search (PostgreSQL only)

Search is ``Message.text ILIKE '%query%'``. A leading wildcard cannot use a
b-tree index, so every search read the whole ``messages`` table — seconds once
the table reaches a million rows.

``pg_trgm`` adds a GIN index over trigrams that *does* serve ``ILIKE '%…%'``,
which is exactly this shape of query and needs no change to the query code.

PostgreSQL only, and deliberately not in the models: ``CREATE INDEX … USING
gin`` is not valid SQLite, so declaring it on ``Message.__table_args__`` would
break ``create_all`` (and therefore every test) on SQLite. The migration is
dialect-guarded instead, which keeps SQLite a no-op.

Operator note: the extension needs a superuser or a role with ``CREATE`` on the
database the first time. If the deployment role cannot do it, run once by hand:

    CREATE EXTENSION IF NOT EXISTS pg_trgm;

and the index creation below will succeed on its own.

Revision ID: 0003_search_indexes
Revises: 0002_relay_provenance
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_search_indexes"
down_revision: str | None = "0002_relay_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, column)
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_messages_text_trgm", "messages", "text"),
    ("ix_messages_caption_trgm", "messages", "caption"),
    ("ix_users_username_trgm", "users", "username"),
    ("ix_users_first_name_trgm", "users", "first_name"),
    ("ix_users_last_name_trgm", "users", "last_name"),
)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():
        # SQLite has no trigram GIN; search stays a sequential scan there, which
        # is fine because SQLite is the development database.
        return

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    for name, table, column in INDEXES:
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {name} "
                f"ON {table} USING gin ({column} gin_trgm_ops)"
            )
        )


def downgrade() -> None:
    if not _is_postgresql():
        return
    for name, _, _ in INDEXES:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
    # the extension is left in place on purpose: other objects may depend on it