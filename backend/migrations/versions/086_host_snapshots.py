"""Panel-host spec baseline: new `host_snapshots` table.

Persists the panel host's CPU/RAM/swap and per-filesystem inventory so a change
across a reboot (a VPS resize, a newly attached volume) can be detected at all.
An in-memory cache cannot serve as the baseline: the resize requires a
power-off, so the process holding it dies at exactly the moment the before-value
is needed.

Indexed on captured_at (the diff reads the newest previous row) and boot_id
(distinguishes an across-reboot change from a hot one).

Revision ID: 086_host_snapshots
Revises: 085_error_logs
"""
import sqlalchemy as sa
from alembic import op

revision = '086_host_snapshots'
down_revision = '085_error_logs'
branch_labels = None
depends_on = None


def _has_table(name):
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade():
    if _has_table('host_snapshots'):
        return
    op.create_table(
        'host_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('captured_at', sa.DateTime(), nullable=True),
        sa.Column('boot_id', sa.String(length=64), nullable=True),
        sa.Column('cpu_cores', sa.Integer(), nullable=True),
        sa.Column('ram_bytes', sa.BigInteger(), nullable=True),
        sa.Column('swap_bytes', sa.BigInteger(), nullable=True),
        sa.Column('container', sa.String(length=32), nullable=True),
        sa.Column('filesystems_json', sa.Text(), nullable=True),
        sa.Column('changes_json', sa.Text(), nullable=True),
        sa.Column('advisories_json', sa.Text(), nullable=True),
    )
    op.create_index('ix_host_snapshots_captured_at', 'host_snapshots', ['captured_at'])
    op.create_index('ix_host_snapshots_boot_id', 'host_snapshots', ['boot_id'])


def downgrade():
    if not _has_table('host_snapshots'):
        return
    for name in ('ix_host_snapshots_boot_id', 'ix_host_snapshots_captured_at'):
        try:
            op.drop_index(name, table_name='host_snapshots')
        except Exception:  # noqa: BLE001
            pass
    op.drop_table('host_snapshots')
