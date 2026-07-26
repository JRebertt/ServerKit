"""Plugin-facing SDK for per-plugin state.

    from app.plugins_sdk import store

    mine = store.for_plugin('serverkit-minecraft')
    mine.set('world:1:seed', 8675309)
    seed = mine.get('world:1:seed')
    mine.delete('world:1:seed')

Use this instead of adding a model and a migration to core for every small
thing an extension needs to remember. Values are JSON — dicts, lists, strings,
numbers, booleans, None — persisted in one shared table, namespaced by slug so
two plugins can never collide on a key.

Reach for a real table (a declared ``ext_<slug>_*`` model) when you need to
query BY the data rather than by key: relations, ordering, aggregates, or more
rows than you would ever want to load at once. This is a key/value store, not a
database, and it will not save you from either.

Rows survive an ordinary uninstall — a reinstall finds its state where it left
it — and are deleted when the operator uninstalls *and* asks to purge data,
matching how extension-declared tables are treated.
"""

import json

from app import db
from app.models.plugin_store import PluginStore

#: Serialized-size ceiling for one value. The table is shared by every
#: installed plugin, so one of them cannot be allowed to put a hundred
#: megabytes in it — and a value that big wants a file or a table, not a key.
MAX_VALUE_BYTES = 256 * 1024

_MISSING = object()


class PluginStoreError(ValueError):
    """A value or key the store refuses to persist."""


class BoundStore:
    """The store as seen by one plugin. Get it from ``store.for_plugin()``."""

    def __init__(self, slug):
        if not slug or not isinstance(slug, str):
            raise PluginStoreError('a plugin store needs a plugin slug')
        self.slug = slug

    # ------------------------------------------------------------------ read
    def get(self, key, default=None):
        """The value stored at *key*, or *default* if nothing is stored."""
        row = self._row(key)
        return default if row is None else row.value

    def has(self, key):
        """True if *key* is set — distinguishes a stored ``None`` from absence."""
        return self._row(key) is not None

    def keys(self, prefix=None):
        """This plugin's keys, sorted; optionally only those under *prefix*."""
        query = PluginStore.query.filter_by(plugin_slug=self.slug)
        if prefix:
            query = query.filter(PluginStore.key.like(f'{_escape_like(prefix)}%',
                                                      escape='\\'))
        return sorted(row.key for row in query.all())

    def all(self, prefix=None):
        """Every key/value this plugin has stored, as a dict."""
        query = PluginStore.query.filter_by(plugin_slug=self.slug)
        if prefix:
            query = query.filter(PluginStore.key.like(f'{_escape_like(prefix)}%',
                                                      escape='\\'))
        return {row.key: row.value for row in query.all()}

    # ----------------------------------------------------------------- write
    def set(self, key, value):
        """Store *value* at *key*, replacing anything already there."""
        key = _clean_key(key)
        _check_value(value)

        row = self._row(key)
        if row is not None:
            row.value = value
            db.session.commit()
            return value

        db.session.add(PluginStore(plugin_slug=self.slug, key=key, value=value))
        try:
            db.session.commit()
        except Exception:
            # Another writer inserted the same key between the read and the
            # commit. The unique constraint is what makes that safe; take their
            # row and apply our write to it rather than failing the caller.
            db.session.rollback()
            row = self._row(key)
            if row is None:
                raise
            row.value = value
            db.session.commit()
        return value

    def setdefault(self, key, value):
        """Store *value* only if *key* is unset; return whatever is stored."""
        existing = self.get(key, _MISSING)
        if existing is not _MISSING:
            return existing
        return self.set(key, value)

    def delete(self, key):
        """Remove *key*. True if something was removed."""
        row = self._row(key)
        if row is None:
            return False
        db.session.delete(row)
        db.session.commit()
        return True

    def clear(self):
        """Remove everything this plugin has stored. Returns the row count."""
        return purge(self.slug)

    # --------------------------------------------------------------- helpers
    def _row(self, key):
        return PluginStore.query.filter_by(
            plugin_slug=self.slug, key=_clean_key(key)).first()


class StoreSdk:
    """Stable storage surface for plugins."""

    def for_plugin(self, slug):
        """The store belonging to *slug*."""
        return BoundStore(slug)

    def purge(self, slug):
        """Delete every row belonging to *slug*. Returns the row count."""
        return purge(slug)


def purge(slug):
    """Delete every stored row for *slug*; returns how many were removed.

    Called by the uninstaller, and available to a plugin's own teardown.
    """
    if not slug:
        return 0
    removed = PluginStore.query.filter_by(plugin_slug=slug).delete(
        synchronize_session=False)
    db.session.commit()
    return removed


def _clean_key(key):
    if not isinstance(key, str) or not key.strip():
        raise PluginStoreError('store keys must be non-empty strings')
    key = key.strip()
    if len(key) > 255:
        raise PluginStoreError('store keys are limited to 255 characters')
    return key


def _check_value(value):
    """Refuse a value the column can't hold, with a message that says why.

    Without this the failure surfaces as an opaque error at commit time — after
    the session is already poisoned, and usually far from the offending call.
    """
    try:
        encoded = json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise PluginStoreError(f'store values must be JSON-serializable: {exc}') from exc
    if len(encoded.encode('utf-8')) > MAX_VALUE_BYTES:
        raise PluginStoreError(
            f'store value is larger than {MAX_VALUE_BYTES // 1024} KB — '
            'keep bulk data in a file or a table of your own')


def _escape_like(prefix):
    """Escape LIKE wildcards so a prefix containing % or _ matches literally."""
    return (str(prefix).replace('\\', '\\\\')
            .replace('%', '\\%').replace('_', '\\_'))


store = StoreSdk()
