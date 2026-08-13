"""Per-user saved table views.

Stores named table states (filter/search/sort/columns/page-size) per list
page, with one default per (user, page).

Idempotent: guards on table presence like the other migrations here.

Revision ID: 082_saved_views
Revises: 081_monitors_first_class
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa

revision = '082_saved_views'
down_revision = '081_monitors_first_class'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'saved_views' in set(inspector.get_table_names()):
        return
    op.create_table(
        'saved_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('page', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'page', 'name', name='uq_saved_views_user_page_name'),
    )
    op.create_index('ix_saved_views_user_id', 'saved_views', ['user_id'])
    op.create_index('ix_saved_views_page', 'saved_views', ['page'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'saved_views' not in set(inspector.get_table_names()):
        return
    op.drop_index('ix_saved_views_page', table_name='saved_views')
    op.drop_index('ix_saved_views_user_id', table_name='saved_views')
    op.drop_table('saved_views')
