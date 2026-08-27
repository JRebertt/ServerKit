"""Alembic migrations must build the schema the models describe (plan 82 §D).

The test suite's schema comes from ``db.create_all()`` (see conftest), so no
test had ever executed a migration: a model column with no migration keeps
every test green while every real upgrade dies with "no such column" — a
whole-fleet outage class. This test runs ``flask db upgrade`` against a
throwaway sqlite file in a subprocess (full isolation, no shared-app state)
and diffs the migrated schema against ``db.metadata`` in both directions.

sqlite-only on purpose: the drift signal (missing/extra tables and columns)
does not need Postgres parity.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]

# Tables that legitimately exist on one side only. Keep every entry
# justified; additions here should be rare and deliberate.
IGNORED_TABLES = {
    'alembic_version',   # alembic bookkeeping, not a model
    'sqlite_sequence',   # sqlite AUTOINCREMENT bookkeeping
}


def _migrated_schema(db_file):
    con = sqlite3.connect(db_file)
    try:
        schema = {}
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (table,) in rows:
            if table in IGNORED_TABLES:
                continue
            cols = {row[1] for row in
                    con.execute(f'PRAGMA table_info("{table}")')}
            schema[table] = cols
        return schema
    finally:
        con.close()


def test_upgrade_head_matches_models(app, tmp_path):
    db_file = tmp_path / 'migrated.db'
    env = {
        **os.environ,
        'FLASK_ENV': 'testing',
        'TEST_DATABASE_URL': 'sqlite:///' + db_file.as_posix(),
    }
    proc = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'run.py', 'db', 'upgrade'],
        cwd=str(BACKEND_DIR), env=env,
        capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        'flask db upgrade failed:\n' + proc.stderr[-4000:])
    assert db_file.exists(), 'upgrade ran but produced no database file'

    migrated = _migrated_schema(str(db_file))
    assert migrated, 'migrations produced an empty schema'

    from app import db
    models = {
        table.name: {c.name for c in table.columns}
        for table in db.metadata.tables.values()
        if table.name not in IGNORED_TABLES
    }

    problems = []
    for name in sorted(set(models) - set(migrated)):
        problems.append(
            f'table {name}: in models but never created by any migration')
    for name in sorted(set(migrated) - set(models)):
        problems.append(
            f'table {name}: created by migrations but no model describes it '
            f'(dropped model without a drop migration?)')
    for name in sorted(set(models) & set(migrated)):
        missing = models[name] - migrated[name]
        extra = migrated[name] - models[name]
        if missing:
            problems.append(
                f'table {name}: migrations missing columns {sorted(missing)}')
        if extra:
            problems.append(
                f'table {name}: migrations carry extra columns '
                f'{sorted(extra)}')

    assert not problems, (
        'model ↔ migration drift — every real upgrade breaks where the '
        'create_all() test schema stays green:\n  '
        + '\n  '.join(problems))
