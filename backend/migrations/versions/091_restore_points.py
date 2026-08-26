"""Add the generic restore-point timeline.

Revision ID: 091_restore_points
Revises: 090_ai_message_attachments
"""

import sqlalchemy as sa
from alembic import op

revision = '091_restore_points'
down_revision = '090_ai_message_attachments'
branch_labels = None
depends_on = None


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if _has_table('restore_points'):
        return

    op.create_table(
        'restore_points',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('server_id', sa.String(length=36), nullable=True),
        sa.Column('scope_type', sa.String(length=32), nullable=False),
        sa.Column('scope_id', sa.String(length=255), nullable=False),
        sa.Column('trigger', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('coverage_json', sa.Text(), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('keep', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_restore_points_actor_user_id', 'restore_points', ['actor_user_id'],
    )
    op.create_index(
        'ix_restore_points_expires_at', 'restore_points', ['expires_at'],
    )
    op.create_index(
        'ix_restore_points_server_id', 'restore_points', ['server_id'],
    )
    op.create_index(
        'ix_restore_points_scope', 'restore_points', ['scope_type', 'scope_id'],
    )
    op.create_index(
        'ix_restore_points_scope_timeline', 'restore_points',
        ['server_id', 'scope_type', 'scope_id', 'created_at'],
    )


def downgrade():
    if not _has_table('restore_points'):
        return
    op.drop_table('restore_points')
