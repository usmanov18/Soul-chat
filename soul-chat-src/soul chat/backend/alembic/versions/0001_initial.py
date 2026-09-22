"""initial schema — 24 tables

The schema is taken from :func:`alembic_schema.schema_at`, which is a copy of
the ORM metadata with everything added by *later* revisions removed. That keeps
this revision frozen in time: a database migrated from zero ends up byte
identical to one built at head, and later revisions can add their columns
without hitting ``duplicate column name``.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from alembic_schema import schema_at

    schema_at(revision).create_all(bind=op.get_bind())


def downgrade() -> None:
    from alembic_schema import schema_at

    # drop_all walks the metadata in reverse dependency order, so foreign keys
    # never block the teardown.
    schema_at(revision).drop_all(bind=op.get_bind())