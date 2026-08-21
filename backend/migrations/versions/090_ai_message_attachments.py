"""Persist AI message attachment reference manifests.

Resolved attachment summaries are deliberately not stored in this column. The
assistant reloads and reauthorizes every reference on each submitted message.

Revision ID: 090_ai_message_attachments
Revises: 089_user_language
"""
import sqlalchemy as sa
from alembic import op

revision = '090_ai_message_attachments'
down_revision = '089_user_language'
branch_labels = None
depends_on = None


def _has_column(table, column):
    bind = op.get_bind()
    return column in {col['name'] for col in sa.inspect(bind).get_columns(table)}


def upgrade():
    if _has_column('ai_messages', 'attachments_json'):
        return
    op.add_column(
        'ai_messages',
        sa.Column('attachments_json', sa.Text(), nullable=True),
    )


def downgrade():
    if not _has_column('ai_messages', 'attachments_json'):
        return
    op.drop_column('ai_messages', 'attachments_json')
