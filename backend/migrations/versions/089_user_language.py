"""Per-user UI language preference: `users.language`.

Plan 79 B2. Nullable on purpose — NULL means "follow the panel default"
(`default_language` in system settings), which is a different state from an
explicit choice of English, so existing rows are left alone rather than
backfilled to 'en'.

Revision ID: 089_user_language
Revises: 088_soft_delete_managed_databases
"""
import sqlalchemy as sa
from alembic import op

revision = '089_user_language'
down_revision = '088_soft_delete_managed_databases'
branch_labels = None
depends_on = None


def _has_column(table, column):
    bind = op.get_bind()
    return column in {col['name'] for col in sa.inspect(bind).get_columns(table)}


def upgrade():
    if _has_column('users', 'language'):
        return
    op.add_column('users', sa.Column('language', sa.String(length=10), nullable=True))


def downgrade():
    if not _has_column('users', 'language'):
        return
    op.drop_column('users', 'language')
