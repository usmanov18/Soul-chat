"""Frozen copy of the schema as it stood at revision ``0001_initial``.

Why this exists
---------------
``0001_initial`` used to call ``Base.metadata.create_all()``. That is convenient
on day one and wrong afterwards: the ORM metadata always describes the *current*
models, so a fresh database would be built at head while ``alembic_version``
still said ``0001_initial``. Every later revision then failed with
``duplicate column name`` on a fresh install and silently no-op'd on a real one.

This module copies the ORM metadata and removes the objects introduced by later
revisions, so ``0001_initial`` describes exactly the schema it claims to. Add the
next revision's objects to ``LATER_REVISION_OBJECTS`` when you write it.

Importing :mod:`app.models` is required — SQLAlchemy populates ``Base.metadata``
as a side effect of the model classes being defined, so without it the metadata
is empty and ``schema_at`` silently returns zero tables.

The copy is dialect-neutral — ``create_all`` compiles it for whatever database
Alembic is bound to, so PostgreSQL and SQLite both get correct DDL.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData

from app import models  # noqa: F401  — importing registers the tables on Base
from app.core.db import Base

# Objects that did NOT exist at 0001_initial: {(table, column)} and {index name}.
LATER_REVISION_OBJECTS: dict[str, dict[str, Any]] = {
    "0002_relay_provenance": {
        "columns": {
            "messages": ("source_message_id", "edited"),
            "users": ("password_hash",),
        },
        "indexes": {"ix_message_source", "ix_messages_source_message_id"},
    },
    "0005_memories": {
        "tables": {"memories"},
    },
}


def _columns_removed(up_to: str) -> dict[str, tuple[str, ...]]:
    """Columns added by revisions *after* ``up_to`` — those must not exist yet."""
    columns: dict[str, list[str]] = {}
    for revision, spec in LATER_REVISION_OBJECTS.items():
        # Revisions sort lexically (0001_… < 0002_… < 0003_…). Anything up to and
        # including ``up_to`` belongs in the schema; everything after does not.
        if revision <= up_to:
            continue
        for table, names in spec.get("columns", {}).items():
            columns.setdefault(table, []).extend(names)
    return {table: tuple(names) for table, names in columns.items()}


def _tables_removed(up_to: str) -> set[str]:
    names: set[str] = set()
    for revision, spec in LATER_REVISION_OBJECTS.items():
        if revision <= up_to:
            continue
        names.update(spec.get("tables", ()))
    return names


def _indexes_removed(up_to: str) -> set[str]:
    names: set[str] = set()
    for revision, spec in LATER_REVISION_OBJECTS.items():
        if revision <= up_to:
            continue
        names.update(spec.get("indexes", ()))
    return names


def schema_at(revision: str) -> MetaData:
    """A ``MetaData`` describing the schema as of ``revision`` (inclusive).

    Pass ``"0000"`` for the pre-history schema, ``"0001_initial"`` for the
    original 24 tables.
    """
    metadata = MetaData()
    removed_tables = _tables_removed(revision)
    for table in Base.metadata.sorted_tables:
        if table.name in removed_tables:
            continue
        table.to_metadata(metadata)

    for table_name, column_names in _columns_removed(revision).items():
        table = metadata.tables[table_name]
        for name in column_names:
            column = table.columns.get(name)
            if column is None:
                continue
            # `Table.columns` is a read-only view; the mutable collection that
            # DDL generation reads from is `_columns`.
            table._columns.remove(column)  # noqa: SLF001

    dropped = _indexes_removed(revision)
    for table in metadata.tables.values():
        table.indexes = {
            index
            for index in table.indexes
            if index.name not in dropped
            # an index on a column that no longer exists cannot be emitted
            and all(column.name in table.columns for column in index.columns)
        }
    return metadata