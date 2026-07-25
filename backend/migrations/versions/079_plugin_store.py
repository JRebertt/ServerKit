"""Per-plugin key/value store.

Gives an extension somewhere to keep its own state without adding a model and a
migration to core for every small thing it needs to remember. One row is one key
for one plugin; the value is a native JSON column, which SQLAlchemy renders as
JSON on PostgreSQL and TEXT on SQLite.

Idempotent: guards on table presence like the other migrations here.

Revision ID: 079_plugin_store
Revises: 078_themes
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = '079_plugin_store'
down_revision = '078_themes'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'plugin_store' in set(inspector.get_table_names()):
        return
    op.create_table(
        'plugin_store',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plugin_slug', sa.String(length=128), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plugin_slug', 'key', name='uq_plugin_store_slug_key'),
    )
    op.create_index('ix_plugin_store_plugin_slug', 'plugin_store', ['plugin_slug'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'plugin_store' not in set(inspector.get_table_names()):
        return
    op.drop_index('ix_plugin_store_plugin_slug', table_name='plugin_store')
    op.drop_table('plugin_store')
