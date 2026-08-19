"""SoftDelete adoption for managed databases (plan 77 B5).

Adds the tombstone pair to managed_databases (migration 083 pattern). No
unique constraints exist on the table, so no partial-unique-index rewrite is
needed.

Revision ID: 088_soft_delete_managed_databases
Revises: 087_run_log_entries
"""
import sqlalchemy as sa
from alembic import op

revision = '088_soft_delete_managed_databases'
down_revision = '087_run_log_entries'
branch_labels = None
depends_on = None


def _has_column(table, column):
    bind = op.get_bind()
    return column in [c['name'] for c in sa.inspect(bind).get_columns(table)]


def upgrade():
    if not _has_column('managed_databases', 'deleted_at'):
        op.add_column('managed_databases', sa.Column('deleted_at', sa.DateTime(), nullable=True))
        op.create_index('ix_managed_databases_deleted_at', 'managed_databases', ['deleted_at'])
    if not _has_column('managed_databases', 'deleted_by_id'):
        op.add_column('managed_databases', sa.Column('deleted_by_id', sa.Integer(), nullable=True))


def downgrade():
    if _has_column('managed_databases', 'deleted_at'):
        op.drop_index('ix_managed_databases_deleted_at', table_name='managed_databases')
        op.drop_column('managed_databases', 'deleted_at')
    if _has_column('managed_databases', 'deleted_by_id'):
        op.drop_column('managed_databases', 'deleted_by_id')
