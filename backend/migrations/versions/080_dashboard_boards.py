"""Per-user dashboard boards.

One row is one dashboard tab for one user: name, icon, ordering position and a
native JSON list of widget instances (SQLAlchemy renders JSON as JSON on
PostgreSQL and TEXT on SQLite). ``slug`` records which shipped default the board
was seeded from so it can be reset; user-created boards leave it NULL.

Idempotent: guards on table presence like the other migrations here.

Revision ID: 080_dashboard_boards
Revises: 079_plugin_store
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = '080_dashboard_boards'
down_revision = '079_plugin_store'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'dashboard_boards' in set(inspector.get_table_names()):
        return
    op.create_table(
        'dashboard_boards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('widgets', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dashboard_boards_user_id', 'dashboard_boards', ['user_id'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'dashboard_boards' not in set(inspector.get_table_names()):
        return
    op.drop_index('ix_dashboard_boards_user_id', table_name='dashboard_boards')
    op.drop_table('dashboard_boards')
