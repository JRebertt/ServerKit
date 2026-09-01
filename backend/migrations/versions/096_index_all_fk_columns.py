"""Index every foreign-key column.

An audit found 102 FK columns with no index: every join, per-parent listing,
and the ORM delete cascades (app/models/_delete_cascade_policy.py) were
scanning whole tables on them. The models now declare index=True on every FK
column; this migration creates the same indexes on existing installs.

Derived from the live schema at upgrade time rather than a frozen list, so it
is idempotent and matches whatever tables the install actually has: any
single-column FK that is not already the leading column of an index, not the
primary key, and not single-column unique gets `ix_<table>_<column>` — the
same name Flask-SQLAlchemy's index=True produces.

Revision ID: 096_index_all_fk_columns
Revises: 095_purge_orphaned_child_rows
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

revision = '096_index_all_fk_columns'
down_revision = '095_purge_orphaned_child_rows'
branch_labels = None
depends_on = None

SKIP_TABLES = {'alembic_version', 'sqlite_sequence'}
EXTENSION_TABLE_PREFIX = 'ext_'   # extension-owned; core migrations keep out

created_names = []


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table in inspector.get_table_names():
        if table in SKIP_TABLES or table.startswith(EXTENSION_TABLE_PREFIX):
            continue
        indexes = inspector.get_indexes(table)
        leading = {ix['column_names'][0] for ix in indexes if ix['column_names']}
        existing_names = {ix['name'] for ix in indexes}
        pk = set(inspector.get_pk_constraint(table).get('constrained_columns') or [])
        unique_single = {uc['column_names'][0]
                         for uc in inspector.get_unique_constraints(table)
                         if len(uc['column_names']) == 1}
        for fk in inspector.get_foreign_keys(table):
            cols = fk.get('constrained_columns') or []
            if len(cols) != 1:
                continue
            col = cols[0]
            name = f'ix_{table}_{col}'
            if (col in leading or col in pk or col in unique_single
                    or name in existing_names):
                continue
            op.create_index(name, table, [col])
            leading.add(col)
            existing_names.add(name)


def downgrade():
    # Dropping ix_<table>_<col> indexes is safe but pointless — leave them.
    pass
