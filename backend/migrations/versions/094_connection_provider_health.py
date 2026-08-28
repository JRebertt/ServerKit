"""Add normalized health observations to container registry connections.

Revision ID: 094_connection_provider_health
Revises: 093_container_scale_policies
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from alembic import op

revision = '094_connection_provider_health'
down_revision = '093_container_scale_policies'
branch_labels = None
depends_on = None


def _columns(table):
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column['name'] for column in inspector.get_columns(table)}


def upgrade():
    columns = _columns('container_registries')
    if not columns:
        return
    with op.batch_alter_table('container_registries') as batch:
        if 'last_tested_at' not in columns:
            batch.add_column(sa.Column('last_tested_at', sa.DateTime(), nullable=True))
        if 'last_test_ok' not in columns:
            batch.add_column(sa.Column('last_test_ok', sa.Boolean(), nullable=True))
        if 'last_test_error' not in columns:
            batch.add_column(sa.Column('last_test_error', sa.String(length=500), nullable=True))


def downgrade():
    columns = _columns('container_registries')
    if not columns:
        return
    with op.batch_alter_table('container_registries') as batch:
        if 'last_test_error' in columns:
            batch.drop_column('last_test_error')
        if 'last_test_ok' in columns:
            batch.drop_column('last_test_ok')
        if 'last_tested_at' in columns:
            batch.drop_column('last_tested_at')

