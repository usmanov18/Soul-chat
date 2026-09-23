"""Alembic migration chain.

The regression this guards is subtle and was already shipped once:
``0001_initial`` used to build the schema from the *live* ORM metadata, so a
database migrated from zero silently arrived at head while ``alembic_version``
claimed ``0001_initial``. Every later revision then failed with
``duplicate column name`` on a fresh install.

``alembic_schema.schema_at`` freezes each revision's view of the schema, and
the test below proves the two ways of getting to head — migrating from zero and
``create_all`` — produce the same columns and indexes.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _schema(db_path: Path) -> dict[str, set[str]]:
    """``{table: {columns…}}`` straight from SQLite, ignoring row data."""
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        return {
            table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for table in sorted(tables)
        }
    finally:
        conn.close()


def _indexes(db_path: Path) -> set[tuple[str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()


def test_migrating_from_zero_reaches_head(tmp_path: Path):
    db = tmp_path / "migrated.db"

    result = _run_alembic(db, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    # assert against `head`, not a hardcoded revision: this test must keep
    # passing when the next migration lands
    head = _run_alembic(db, "heads")
    assert head.stdout.split()[0] in _run_alembic(db, "current").stdout

    schema = _schema(db)
    assert "alembic_version" in schema
    assert len(schema) >= 24
    # the columns 0002 adds must be there
    assert "source_message_id" in schema["messages"]
    assert "edited" in schema["messages"]
    assert "password_hash" in schema["users"]


def test_migrated_schema_matches_create_all(tmp_path: Path):
    """The whole point: migrate-from-zero == build-at-head, column for column."""
    migrated = tmp_path / "migrated.db"
    created = tmp_path / "created.db"

    assert _run_alembic(migrated, "upgrade", "head").returncode == 0

    # build the same database the way `manage.py initdb` does
    from sqlalchemy import create_engine

    from app import models  # noqa: F401
    from app.core.db import Base

    engine = create_engine(f"sqlite:///{created}")
    Base.metadata.create_all(engine)
    engine.dispose()

    migrated_schema = _schema(migrated)
    created_schema = _schema(created)

    # alembic bookkeeping is the only expected difference
    migrated_schema.pop("alembic_version", None)

    assert set(migrated_schema) == set(created_schema), (
        f"tables differ: only-migrated={set(migrated_schema) - set(created_schema)} "
        f"only-created={set(created_schema) - set(migrated_schema)}"
    )
    for table in migrated_schema:
        assert migrated_schema[table] == created_schema[table], f"columns differ in {table}"


def test_indexes_match_create_all(tmp_path: Path):
    migrated = tmp_path / "migrated.db"
    created = tmp_path / "created.db"

    assert _run_alembic(migrated, "upgrade", "head").returncode == 0

    from sqlalchemy import create_engine

    from app import models  # noqa: F401
    from app.core.db import Base

    engine = create_engine(f"sqlite:///{created}")
    Base.metadata.create_all(engine)
    engine.dispose()

    assert _indexes(migrated) == _indexes(created)


def test_the_partial_unique_index_survives_the_migration(tmp_path: Path):
    """Without the WHERE clause two group messages (source NULL) would collide."""
    db = tmp_path / "partial.db"
    assert _run_alembic(db, "upgrade", "head").returncode == 0

    conn = sqlite3.connect(db)
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='ix_message_source'"
    ).fetchone()[0]
    conn.close()

    normalised = ddl.upper()
    assert "UNIQUE" in normalised
    assert "WHERE SOURCE_MESSAGE_ID IS NOT NULL" in normalised


def test_downgrade_removes_the_columns(tmp_path: Path):
    db = tmp_path / "down.db"
    assert _run_alembic(db, "upgrade", "head").returncode == 0

    result = _run_alembic(db, "downgrade", "0001_initial")
    assert result.returncode == 0, result.stderr

    schema = _schema(db)
    assert "source_message_id" not in schema["messages"]
    assert "edited" not in schema["messages"]
    assert "password_hash" not in schema["users"]
    assert "ix_message_source" not in {name for name, _ in _indexes(db)}


def test_downgrade_then_upgrade_again(tmp_path: Path):
    db = tmp_path / "roundtrip.db"
    assert _run_alembic(db, "upgrade", "head").returncode == 0
    assert _run_alembic(db, "downgrade", "base").returncode == 0

    # `base` drops every table
    assert _schema(db) == {"alembic_version": {"version_num"}}

    assert _run_alembic(db, "upgrade", "head").returncode == 0
    schema = _schema(db)
    assert "source_message_id" in schema["messages"]
    assert len(schema) >= 24


def test_0002_is_idempotent_on_a_legacy_database(tmp_path: Path):
    """A database stamped at 0001 before 0002 existed still upgrades cleanly.

    The fixture builds a *faithful* pre-0002 database: the 0001 schema exactly
    as ``schema_at('0001_initial')`` describes it, plus the version stamp.
    """
    from sqlalchemy import create_engine

    from alembic_schema import schema_at

    db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db}")
    schema_at("0001_initial").create_all(engine)
    engine.dispose()

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version VALUES ('0001_initial')")
    conn.commit()
    conn.close()

    result = _run_alembic(db, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    schema = _schema(db)
    assert "source_message_id" in schema["messages"]
    assert "edited" in schema["messages"]
    assert "password_hash" in schema["users"]


def test_schema_at_freezes_earlier_revisions():
    """Unit level: the helper must not leak later columns into 0001."""
    from alembic_schema import schema_at

    initial = schema_at("0001_initial")
    assert len(initial.tables) == 24
    assert "source_message_id" not in initial.tables["messages"].columns
    assert "edited" not in initial.tables["messages"].columns
    assert "password_hash" not in initial.tables["users"].columns
    assert not any(i.name == "ix_message_source" for i in initial.tables["messages"].indexes)

    head = schema_at("9999")
    assert "source_message_id" in head.tables["messages"].columns
    assert any(i.name == "ix_message_source" for i in head.tables["messages"].indexes)


@pytest.mark.parametrize("revision,minimum", [("0001_initial", 24), ("9999", 25)])
def test_schema_at_keeps_every_table(revision: str, minimum: int):
    """``schema_at`` must keep every table that existed at the revision.

    Head-agnostic on the upper bound: new revisions legitimately add tables
    (``memories`` became the 25th), so head is a floor, 0001 an exact freeze.
    """
    from alembic_schema import schema_at

    assert len(schema_at(revision).tables) >= minimum


# ---------------------------------------------------------------------------
# 0003 — trigram search indexes
# ---------------------------------------------------------------------------
def test_search_index_migration_is_a_noop_on_sqlite(tmp_path: Path):
    """``CREATE INDEX … USING gin`` is not valid SQLite — it must be skipped."""
    db = tmp_path / "trgm.db"
    result = _run_alembic(db, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    current = _run_alembic(db, "current")
    # head-agnostic: 0004 and later revisions keep this test valid; the chain
    # itself must still contain the guarded 0003 revision.
    head = _run_alembic(db, "heads")
    assert head.stdout.split()[0] in current.stdout
    assert "0003_search_indexes" in _run_alembic(db, "history").stdout

    conn = sqlite3.connect(db)
    indexes = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )}
    conn.close()
    assert not any(name.endswith("_trgm") for name in indexes)


def test_search_index_migration_downgrades_on_sqlite(tmp_path: Path):
    db = tmp_path / "trgm2.db"
    assert _run_alembic(db, "upgrade", "head").returncode == 0
    assert _run_alembic(db, "downgrade", "0002_relay_provenance").returncode == 0

    current = _run_alembic(db, "current")
    assert "0002_relay_provenance" in current.stdout


def test_trigram_indexes_cover_every_searched_column():
    """Every ILIKE '%…%' in the search path needs a trigram index or it scans."""
    import re

    service = (BACKEND_ROOT / "app" / "services" / "analytics_service.py").read_text()
    migration = (BACKEND_ROOT / "alembic" / "versions" / "0003_search_indexes.py").read_text()

    # the model class in front of each .ilike maps onto a table
    table_by_model = {"Message": "messages", "User": "users", "Topic": "topics"}
    searched = {
        table_by_model[model]
        for model in re.findall(r"\b(Message|User|Topic)\.\w+\.ilike\(", service)
    }
    assert searched, "no ilike found — the search path changed, update this test"

    # the migration declares ("index name", table, column) triples
    covered = {table for _, table, _ in re.findall(r'"(ix_\w+_trgm)", "(\w+)", "(\w+)"', migration)}
    assert searched <= covered, f"searched but unindexed tables: {searched - covered}"


def test_index_list_is_complete_for_the_message_and_user_columns():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "migration_0003", BACKEND_ROOT / "alembic" / "versions" / "0003_search_indexes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pairs = {(table, column) for _, table, column in module.INDEXES}
    assert ("messages", "text") in pairs
    assert ("messages", "caption") in pairs
    assert ("users", "username") in pairs
    assert ("users", "first_name") in pairs
    assert ("users", "last_name") in pairs


def test_postgresql_branch_emits_trigram_ddl(monkeypatch):
    """The SQLite tests can never reach the PG branch — assert its SQL directly."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "migration_0003_pg", BACKEND_ROOT / "alembic" / "versions" / "0003_search_indexes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    executed: list[str] = []

    class _FakeOp:
        @staticmethod
        def execute(statement) -> None:
            executed.append(str(statement))

        @staticmethod
        def get_bind():
            class _Bind:
                class dialect:
                    name = "postgresql"

            return _Bind()

    monkeypatch.setattr(module, "op", _FakeOp)
    module.upgrade()

    joined = "\n".join(executed)
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in joined
    for name, table, column in module.INDEXES:
        assert f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin ({column} gin_trgm_ops)" in joined


def test_postgresql_branch_downgrades(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "migration_0003_pg2", BACKEND_ROOT / "alembic" / "versions" / "0003_search_indexes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    executed: list[str] = []

    class _FakeOp:
        @staticmethod
        def execute(statement) -> None:
            executed.append(str(statement))

        @staticmethod
        def get_bind():
            class _Bind:
                class dialect:
                    name = "postgresql"

            return _Bind()

    monkeypatch.setattr(module, "op", _FakeOp)
    module.downgrade()

    joined = "\n".join(executed)
    for name, _, _ in module.INDEXES:
        assert f"DROP INDEX IF EXISTS {name}" in joined
    # the extension is intentionally kept — other objects may depend on it
    assert "DROP EXTENSION" not in joined


def test_sqlite_branch_executes_nothing(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "migration_0003_lite", BACKEND_ROOT / "alembic" / "versions" / "0003_search_indexes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    executed: list[str] = []

    class _FakeOp:
        @staticmethod
        def execute(statement) -> None:
            executed.append(str(statement))

        @staticmethod
        def get_bind():
            class _Bind:
                class dialect:
                    name = "sqlite"

            return _Bind()

    monkeypatch.setattr(module, "op", _FakeOp)
    module.upgrade()
    module.downgrade()

    assert executed == []