"""Persist the revocation epoch for all browser authentication tokens.

Existing JWTs lack this claim and intentionally require a fresh login.
"""
from alembic import op
import sqlalchemy as sa

revision = '097_user_auth_version'
down_revision = '096_index_all_fk_columns'
branch_labels = None
depends_on = None


def upgrade():
    # The initial migration bootstraps from current model metadata, so fresh
    # installs may already have the new schema by the time they reach here.
    inspector = sa.inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('users')}
    if 'auth_version' not in columns:
        op.add_column('users', sa.Column('auth_version', sa.String(32),
                                       nullable=False, server_default='0'))
    if 'revoked_sessions' not in inspector.get_table_names():
        op.create_table('revoked_sessions',
                        sa.Column('session_id', sa.String(32), primary_key=True),
                        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
                        sa.Column('revoked_at', sa.DateTime(), nullable=False))
        op.create_index('ix_revoked_sessions_user_id', 'revoked_sessions', ['user_id'])


def downgrade():
    op.drop_table('revoked_sessions')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('auth_version')
