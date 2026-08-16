"""Centralized error log tracking: new `error_logs` table.

Fingerprint-deduped store for unhandled backend exceptions (500 handler) and
frontend-reported client errors. Indexes match the access patterns: dedup
lookup by fingerprint, admin list filtering by source/resolved, ordering by
last_seen.

Revision ID: 085_error_logs
Revises: 084_soft_delete_applications
"""
import sqlalchemy as sa
from alembic import op

revision = '085_error_logs'
down_revision = '084_soft_delete_applications'
branch_labels = None
depends_on = None


def _has_table(name):
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade():
    if _has_table('error_logs'):
        return
    op.create_table(
        'error_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('exception_type', sa.String(length=200), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('endpoint', sa.String(length=255), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('context_json', sa.Text(), nullable=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('first_seen', sa.DateTime(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('resolved', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )
    op.create_index('ix_error_logs_fingerprint', 'error_logs', ['fingerprint'])
    op.create_index('ix_error_logs_source', 'error_logs', ['source'])
    op.create_index('ix_error_logs_last_seen', 'error_logs', ['last_seen'])
    op.create_index('ix_error_logs_resolved', 'error_logs', ['resolved'])


def downgrade():
    if not _has_table('error_logs'):
        return
    for name in ('ix_error_logs_resolved', 'ix_error_logs_last_seen',
                 'ix_error_logs_source', 'ix_error_logs_fingerprint'):
        try:
            op.drop_index(name, table_name='error_logs')
        except Exception:  # noqa: BLE001
            pass
    op.drop_table('error_logs')
