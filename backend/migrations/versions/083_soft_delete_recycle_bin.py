"""Soft delete + recycle bin: tombstones on domains and saved_views, view slugs.

Two things need care here:

1. UNIQUE -> PARTIAL UNIQUE. Both tables had a plain UNIQUE that included what
   is now a tombstoned row, so deleting a domain would permanently burn its
   name and deleting a view would block re-creating one with the same name.
   Each becomes a unique INDEX with a `deleted_at IS NULL` predicate, which
   SQLite (3.8+) and PostgreSQL both support.

2. SQLite cannot drop a constraint in place, so the domains change runs inside
   a batch_alter_table (table rebuild). The saved_views UNIQUE was declared as
   a named constraint, so it is dropped the same way.

Revision ID: 083_soft_delete_recycle_bin
Revises: 082_saved_views
"""
import sqlalchemy as sa
from alembic import op

revision = '083_soft_delete_recycle_bin'
down_revision = '082_saved_views'
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
    # ---- domains -------------------------------------------------------
    if _has_table('domains'):
        existing = _columns('domains')
        with op.batch_alter_table('domains') as batch:
            if 'deleted_at' not in existing:
                batch.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
            if 'deleted_by_id' not in existing:
                batch.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        _mk_index('domains', 'ix_domains_deleted_at', ['deleted_at'])

        # Replace the plain UNIQUE on name with a live-rows-only unique index.
        # The old constraint may be an index or a table constraint depending on
        # how the table was first created, so try both and ignore misses.
        for drop in (
            lambda: op.drop_index('ix_domains_name', table_name='domains'),
            lambda: op.drop_constraint('uq_domains_name', 'domains', type_='unique'),
        ):
            try:
                drop()
            except Exception:  # noqa: BLE001 - constraint shape varies by install age
                pass
        _mk_index('domains', 'ix_domains_name', ['name'])
        _mk_index('domains', 'uq_domains_name_live', ['name'], unique=True, live_only=True)

    # ---- saved_views ---------------------------------------------------
    if _has_table('saved_views'):
        existing = _columns('saved_views')
        # Batch mode validates the whole recipe when the block EXITS, so a
        # missing constraint raises there, not at the drop_constraint() call --
        # wrapping the call in try/except does nothing. Check first instead.
        drop_uq = 'uq_saved_views_user_page_name' in _unique_constraints('saved_views')
        with op.batch_alter_table('saved_views') as batch:
            if 'deleted_at' not in existing:
                batch.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
            if 'deleted_by_id' not in existing:
                batch.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
            if 'slug' not in existing:
                batch.add_column(sa.Column('slug', sa.String(length=140), nullable=True))
            if drop_uq:
                batch.drop_constraint('uq_saved_views_user_page_name', type_='unique')
        _mk_index('saved_views', 'ix_saved_views_deleted_at', ['deleted_at'])
        _mk_index('saved_views', 'ix_saved_views_slug', ['slug'])
        _mk_index('saved_views', 'uq_saved_views_user_page_name_live',
                  ['user_id', 'page', 'name'], unique=True, live_only=True)
        _mk_index('saved_views', 'uq_saved_views_user_page_slug_live',
                  ['user_id', 'page', 'slug'], unique=True, live_only=True)
        # Backfill slugs for views that predate the column.
        _backfill_slugs()


def _backfill_slugs():
    import re
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        'SELECT id, user_id, page, name FROM saved_views WHERE slug IS NULL'
    )).fetchall()
    seen = set()
    for row in rows:
        base = re.sub(r'[^a-z0-9]+', '-', (row.name or '').lower()).strip('-') or f'view-{row.id}'
        slug, n = base, 2
        while (row.user_id, row.page, slug) in seen:
            slug = f'{base}-{n}'
            n += 1
        seen.add((row.user_id, row.page, slug))
        bind.execute(
            sa.text('UPDATE saved_views SET slug = :slug WHERE id = :id'),
            {'slug': slug, 'id': row.id},
        )


def downgrade():
    if _has_table('saved_views'):
        for name in ('uq_saved_views_user_page_slug_live', 'uq_saved_views_user_page_name_live',
                     'ix_saved_views_slug', 'ix_saved_views_deleted_at'):
            try:
                op.drop_index(name, table_name='saved_views')
            except Exception:  # noqa: BLE001
                pass
        with op.batch_alter_table('saved_views') as batch:
            for col in ('slug', 'deleted_by_id', 'deleted_at'):
                try:
                    batch.drop_column(col)
                except Exception:  # noqa: BLE001
                    pass
            batch.create_unique_constraint(
                'uq_saved_views_user_page_name', ['user_id', 'page', 'name'])

    if _has_table('domains'):
        for name in ('uq_domains_name_live', 'ix_domains_deleted_at'):
            try:
                op.drop_index(name, table_name='domains')
            except Exception:  # noqa: BLE001
                pass
        with op.batch_alter_table('domains') as batch:
            for col in ('deleted_by_id', 'deleted_at'):
                try:
                    batch.drop_column(col)
                except Exception:  # noqa: BLE001
                    pass
        try:
            op.drop_index('ix_domains_name', table_name='domains')
        except Exception:  # noqa: BLE001
            pass
        op.create_index('ix_domains_name', 'domains', ['name'], unique=True)
