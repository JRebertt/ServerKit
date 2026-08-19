"""Generic run-scoped log rows (plan 77 E1): new `run_log_entries` table.

DeploymentJobLog stays the store for the deploy kind; every other run kind
(unified jobs, sandbox runs, site imports, backups) persists its stream lines
here, keyed by (run_kind, run_id) — the same key as the run_<kind>_<id>
socket room and the /api/v1/runs polling twin.

Revision ID: 087_run_log_entries
Revises: 086_host_snapshots
"""
import sqlalchemy as sa
from alembic import op

revision = '087_run_log_entries'
down_revision = '086_host_snapshots'
branch_labels = None
depends_on = None


def _has_table(name):
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade():
    if _has_table('run_log_entries'):
        return
    op.create_table(
        'run_log_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_kind', sa.String(length=40), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=True),
        sa.Column('level', sa.String(length=10), nullable=False, server_default='info'),
        sa.Column('message', sa.Text(), nullable=False, server_default=''),
        sa.Column('data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_run_log_entries_kind_run_id', 'run_log_entries',
        ['run_kind', 'run_id', 'id'],
    )


def downgrade():
    if not _has_table('run_log_entries'):
        return
    op.drop_index('ix_run_log_entries_kind_run_id', table_name='run_log_entries')
    op.drop_table('run_log_entries')
