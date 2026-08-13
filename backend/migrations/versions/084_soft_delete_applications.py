"""Soft delete for applications: tombstone columns + a live-rows-only slug index.

Same shape as 083 (domains / saved_views), with one table-specific hazard:

`applications.private_slug` is UNIQUE and is what the `/p/<slug>` private-URL
route resolves against. Left as a plain UNIQUE, deleting an app would burn its
slug forever — the recycle bin's whole promise is that the delete is undoable,
and "you can have the app back but not its URL" is not that. It becomes a
unique INDEX predicated on `deleted_at IS NULL`, so a tombstone releases the
slug and a live row still cannot collide.

Deliberately NOT touched: `applications.name` has no unique constraint (two
apps may share a name today), so there is nothing to convert. Do not add one
here — that would be a behaviour change wearing a migration's clothes.

Revision ID: 084_soft_delete_applications
Revises: 083_soft_delete_recycle_bin
"""
import sqlalchemy as sa
from alembic import op

revision = '084_soft_delete_applications'
down_revision = '083_soft_delete_recycle_bin'
branch_labels = None
depends_on = None


def _has_table(name):
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _columns(table):
    bind = op.get_bind()
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def _indexes(table):
    bind = op.get_bind()
    return {i['name'] for i in sa.inspect(bind).get_indexes(table)}


def _unique_constraints(table):
    bind = op.get_bind()
    try:
        return {c['name'] for c in sa.inspect(bind).get_unique_constraints(table)}
    except NotImplementedError:      # some dialects
        return set()


def _mk_index(table, name, cols, unique=False, live_only=False):
    """create_index that tolerates the index already existing.

    `deleted_at` is declared index=True on the mixin, so a database built from
    the models rather than replayed through migrations already has it — and a
    bare create_index would abort the upgrade on exactly the installs we most
    want to keep working.
    """
    if name in _indexes(table):
        return
    kwargs = {}
    if live_only:
        kwargs = {
            'sqlite_where': sa.text('deleted_at IS NULL'),
            'postgresql_where': sa.text('deleted_at IS NULL'),
        }
    op.create_index(name, table, cols, unique=unique, **kwargs)


def upgrade():
    if not _has_table('applications'):
        return

    existing = _columns('applications')
    # Batch mode validates the whole recipe when the block EXITS, so a missing
    # constraint raises there rather than at the drop call — check first instead
    # of wrapping it in try/except (the lesson from 083).
    drop_uq = 'uq_applications_private_slug' in _unique_constraints('applications')
    with op.batch_alter_table('applications') as batch:
        if 'deleted_at' not in existing:
            batch.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in existing:
            batch.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        if drop_uq:
            batch.drop_constraint('uq_applications_private_slug', type_='unique')

    _mk_index('applications', 'ix_applications_deleted_at', ['deleted_at'])

    # The unique may have been materialised as an index instead of a table
    # constraint depending on how old the install is; drop whichever exists.
    for drop in (
        lambda: op.drop_index('ix_applications_private_slug', table_name='applications'),
    ):
        try:
            drop()
        except Exception:  # noqa: BLE001 - constraint shape varies by install age
            pass

    # Plain lookup index (the /p/<slug> route reads it) + the live-only unique.
    _mk_index('applications', 'ix_applications_private_slug', ['private_slug'])
    _mk_index('applications', 'uq_applications_private_slug_live',
              ['private_slug'], unique=True, live_only=True)


def downgrade():
    if not _has_table('applications'):
        return
    for name in ('uq_applications_private_slug_live', 'ix_applications_deleted_at'):
        try:
            op.drop_index(name, table_name='applications')
        except Exception:  # noqa: BLE001
            pass
    with op.batch_alter_table('applications') as batch:
        for col in ('deleted_by_id', 'deleted_at'):
            try:
                batch.drop_column(col)
            except Exception:  # noqa: BLE001
                pass
