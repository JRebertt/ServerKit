"""Promote status-page components to first-class monitors.

A ``StatusComponent`` was already a full synthetic check (check_type / target /
interval / timeout, HealthCheck history, uptime windows, auto-incidents) — it
was just *framed* as "a component of a status page" and could not exist without
one. This migration makes it stand on its own so /monitoring can own it:

- ``status_components.page_id`` -> nullable (a monitor needs no status page)
- ``status_incidents.page_id``  -> nullable (a pageless monitor's auto-incident
  has no page either; without this the outage path raises IntegrityError)

Plus the columns backing the monitor UI, one per surfaced control:

- ``is_paused``            pause/resume without overloading ``status``
- ``check_method``         HTTP verb (Configuration section)
- ``expected_status``      accepted status range, e.g. "200-299"
- ``keyword``              body substring for the Keyword check type
- ``follow_redirects`` / ``verify_tls``   probe switches
- ``retries``              failed checks tolerated before an incident opens
- ``consecutive_failures`` running counter that drives ``retries``
- ``cert_issuer`` / ``cert_expires_at``   TLS certificate KPI

Idempotent: MigrationService._fix_missing_columns runs db.create_all() on boot
before Alembic, so a fresh database already matches the model. Guard on the live
schema like previous migrations.

Revision ID: 081_monitors_first_class
Revises: 080_dashboard_boards
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = '081_monitors_first_class'
down_revision = '080_dashboard_boards'
branch_labels = None
depends_on = None


# Batch mode rebuilds the table on SQLite, which needs every reflected FK to
# carry a name. These tables' FKs are unnamed, so supply the convention.
NAMING_CONVENTION = {
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
}

NEW_COLUMNS = [
    ('is_paused', sa.Boolean(), {'nullable': False, 'server_default': sa.false()}),
    ('check_method', sa.String(length=8), {'nullable': True, 'server_default': 'GET'}),
    ('expected_status', sa.String(length=32), {'nullable': True, 'server_default': '200-299'}),
    ('keyword', sa.String(length=256), {'nullable': True}),
    ('follow_redirects', sa.Boolean(), {'nullable': False, 'server_default': sa.true()}),
    ('verify_tls', sa.Boolean(), {'nullable': False, 'server_default': sa.true()}),
    ('retries', sa.Integer(), {'nullable': False, 'server_default': '2'}),
    ('consecutive_failures', sa.Integer(), {'nullable': False, 'server_default': '0'}),
    ('cert_issuer', sa.String(length=256), {'nullable': True}),
    ('cert_expires_at', sa.DateTime(), {'nullable': True}),
]


def _columns(inspector, table):
    if table not in set(inspector.get_table_names()):
        return {}
    return {c['name']: c for c in inspector.get_columns(table)}


def _make_page_id_nullable(inspector, table):
    """Drop the NOT NULL on <table>.page_id, if it is still there."""
    col = _columns(inspector, table).get('page_id')
    if col is None or col.get('nullable'):
        return
    with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.alter_column('page_id', existing_type=sa.Integer(), nullable=True)


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'status_components' not in set(inspector.get_table_names()):
        return

    existing = _columns(inspector, 'status_components')
    missing = [(n, t, kw) for n, t, kw in NEW_COLUMNS if n not in existing]
    if missing:
        with op.batch_alter_table('status_components') as batch_op:
            for name, col_type, kwargs in missing:
                batch_op.add_column(sa.Column(name, col_type, **kwargs))

    _make_page_id_nullable(inspector, 'status_components')
    _make_page_id_nullable(inspector, 'status_incidents')


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'status_components' not in set(inspector.get_table_names()):
        return

    existing = _columns(inspector, 'status_components')
    present = [n for n, _t, _kw in NEW_COLUMNS if n in existing]
    if present:
        with op.batch_alter_table('status_components') as batch_op:
            for name in present:
                batch_op.drop_column(name)

    # page_id goes back to NOT NULL. Rows created as pageless monitors cannot
    # satisfy that, so drop them first rather than failing the downgrade.
    conn.execute(sa.text('DELETE FROM status_incidents WHERE page_id IS NULL'))
    conn.execute(sa.text('DELETE FROM status_components WHERE page_id IS NULL'))
    for table in ('status_components', 'status_incidents'):
        with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.alter_column('page_id', existing_type=sa.Integer(), nullable=False)
