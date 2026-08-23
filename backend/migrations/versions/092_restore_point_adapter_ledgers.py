"""Add restore-point replay metadata to environment and DNS ledgers.

Revision ID: 092_restore_point_ledgers
Revises: 091_restore_points
"""

import sqlalchemy as sa
from alembic import op

revision = '092_restore_point_ledgers'
down_revision = '091_restore_points'
branch_labels = None
depends_on = None


def _has_column(table, column):
    return column in {
        item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade():
    if not _has_column('environment_variable_history', 'batch_id'):
        op.add_column(
            'environment_variable_history',
            sa.Column('batch_id', sa.String(length=36), nullable=True),
        )
        op.create_index(
            'ix_environment_variable_history_batch_id',
            'environment_variable_history',
            ['batch_id'],
        )

    if not _has_column('dns_changes', 'before_json'):
        op.add_column(
            'dns_changes',
            sa.Column('before_json', sa.Text(), nullable=True),
        )

    if not _has_column('managed_dns_records', 'ttl'):
        op.add_column(
            'managed_dns_records',
            sa.Column('ttl', sa.Integer(), nullable=True),
        )
    if not _has_column('managed_dns_records', 'priority'):
        op.add_column(
            'managed_dns_records',
            sa.Column('priority', sa.Integer(), nullable=True),
        )
    if not _has_column('managed_dns_records', 'proxied'):
        op.add_column(
            'managed_dns_records',
            sa.Column('proxied', sa.Boolean(), nullable=True),
        )


def downgrade():
    if _has_column('managed_dns_records', 'proxied'):
        op.drop_column('managed_dns_records', 'proxied')
    if _has_column('managed_dns_records', 'priority'):
        op.drop_column('managed_dns_records', 'priority')
    if _has_column('managed_dns_records', 'ttl'):
        op.drop_column('managed_dns_records', 'ttl')
    if _has_column('dns_changes', 'before_json'):
        op.drop_column('dns_changes', 'before_json')
    if _has_column('environment_variable_history', 'batch_id'):
        op.drop_index(
            'ix_environment_variable_history_batch_id',
            table_name='environment_variable_history',
        )
        op.drop_column('environment_variable_history', 'batch_id')
