"""widen backup_history.target to varchar(32)

``target`` was ``VARCHAR(16)``. The column records which backup target ran
(``local``, ``s3``, ``gdrive``), but an *unknown* target is exactly the case
the row exists for: ``BackupService`` stores the requested name with
``status="failed"`` so the operator can see the mistake. A name like
``somewhere-unknown`` (17 chars) is therefore legitimate input — and PostgreSQL
enforces the length SQLite ignores, so the failure row itself failed to insert.

Widened to 32. Guarded by an inspector check: fresh installs already get the
new length from the ORM, older databases get a batch alter (SQLite rebuilds the
table, PostgreSQL issues a plain ``ALTER TYPE``).

Revision ID: 0004_backup_target_widen
Revises: 0003_search_indexes
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_backup_target_widen"
down_revision: str | None = "0003_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _target_length() -> int | None:
    inspector = sa.inspect(op.get_bind())
    if "backup_history" not in inspector.get_table_names():
        return None
    for column in inspector.get_columns("backup_history"):
        if column["name"] == "target":
            column_type = column["type"]
            return getattr(column_type, "length", None)
    return None


def upgrade() -> None:
    length = _target_length()
    if length is None or length >= 32:
        return
    with op.batch_alter_table("backup_history") as batch:
        batch.alter_column(
            "target",
            existing_type=sa.String(length),
            type_=sa.String(32),
            existing_nullable=False,
        )


def downgrade() -> None:
    # narrowing again would truncate recorded target names; keep the width
    return None
