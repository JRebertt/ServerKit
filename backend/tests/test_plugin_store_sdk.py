"""Per-plugin key/value storage (plugins_sdk.store).

The tax this removes: before it, an extension that needed to remember anything
had to add a model AND an Alembic migration to core — which is why extension
tables sit in the panel's own migration history.

What the tests pin down is the part a shared table makes load-bearing: two
plugins can never see or clobber each other's keys, one plugin can't fill the
table, and an uninstall that wasn't asked to purge leaves the data alone.
"""

import pytest

from app import db
from app.models.plugin_store import PluginStore
from app.plugins_sdk.store_sdk import MAX_VALUE_BYTES, PluginStoreError, store

# Installs plugins, and plugin_service hot-loads their blueprints onto the
# live app. Flask refuses register_blueprint once an app has served a
# request, so these need a private app (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


@pytest.fixture
def mine(app):
    return store.for_plugin('serverkit-demo')


class TestRoundTrip:
    def test_set_then_get(self, app, mine):
        mine.set('world:1:seed', 8675309)
        assert mine.get('world:1:seed') == 8675309

    def test_stores_json_shapes(self, app, mine):
        value = {'players': ['a', 'b'], 'settings': {'hardcore': True, 'slots': 20},
                 'motd': None}
        mine.set('world:1', value)
        assert mine.get('world:1') == value

    def test_missing_key_returns_the_default(self, app, mine):
        assert mine.get('nope') is None
        assert mine.get('nope', 'fallback') == 'fallback'

    def test_has_distinguishes_a_stored_none_from_absence(self, app, mine):
        mine.set('explicit', None)
        # get() alone can't tell these apart, which is why has() exists.
        assert mine.get('explicit') is None and mine.get('absent') is None
        assert mine.has('explicit') is True
        assert mine.has('absent') is False

    def test_set_overwrites_without_duplicating_the_row(self, app, mine):
        mine.set('k', 'first')
        mine.set('k', 'second')
        assert mine.get('k') == 'second'
        assert PluginStore.query.filter_by(plugin_slug='serverkit-demo',
                                           key='k').count() == 1

    def test_setdefault_only_writes_when_unset(self, app, mine):
        assert mine.setdefault('k', 'original') == 'original'
        assert mine.setdefault('k', 'ignored') == 'original'

    def test_delete(self, app, mine):
        mine.set('k', 1)
        assert mine.delete('k') is True
        assert mine.delete('k') is False
        assert mine.get('k') is None

    def test_keys_and_all_with_a_prefix(self, app, mine):
        mine.set('world:1:seed', 1)
        mine.set('world:2:seed', 2)
        mine.set('backup:last', 3)

        assert mine.keys() == ['backup:last', 'world:1:seed', 'world:2:seed']
        assert mine.keys(prefix='world:') == ['world:1:seed', 'world:2:seed']
        assert mine.all(prefix='world:') == {'world:1:seed': 1, 'world:2:seed': 2}

    def test_prefix_wildcards_are_matched_literally(self, app, mine):
        # '_' and '%' are LIKE wildcards; an unescaped prefix would match keys
        # the caller never asked for.
        mine.set('a_b', 'wanted')
        mine.set('axb', 'not wanted')
        assert mine.keys(prefix='a_') == ['a_b']


class TestIsolation:
    def test_two_plugins_cannot_see_or_clobber_each_other(self, app):
        one = store.for_plugin('plugin-one')
        two = store.for_plugin('plugin-two')

        one.set('shared-key', 'from one')
        two.set('shared-key', 'from two')

        assert one.get('shared-key') == 'from one'
        assert two.get('shared-key') == 'from two'
        assert one.keys() == ['shared-key']

        one.clear()
        assert one.get('shared-key') is None
        assert two.get('shared-key') == 'from two'


class TestRefusals:
    def test_rejects_unserialisable_values(self, app, mine):
        # Caught at set() rather than at commit, where the error is opaque and
        # the session is already poisoned.
        with pytest.raises(PluginStoreError):
            mine.set('k', object())

    def test_rejects_oversized_values(self, app, mine):
        with pytest.raises(PluginStoreError):
            mine.set('k', 'x' * (MAX_VALUE_BYTES + 1))

    def test_rejects_empty_keys(self, app, mine):
        for key in ('', '   ', None, 7):
            with pytest.raises(PluginStoreError):
                mine.set(key, 1)

    def test_rejects_overlong_keys(self, app, mine):
        with pytest.raises(PluginStoreError):
            mine.set('k' * 256, 1)

    def test_a_store_needs_a_slug(self, app):
        with pytest.raises(PluginStoreError):
            store.for_plugin('')

    def test_a_refused_value_leaves_the_session_usable(self, app, mine):
        with pytest.raises(PluginStoreError):
            mine.set('k', object())
        # The point of validating early: the next write still works.
        mine.set('k', 'fine')
        assert mine.get('k') == 'fine'


class TestUninstall:
    def _install_row(self, slug):
        from app.models.plugin import InstalledPlugin
        plugin = InstalledPlugin(slug=slug, name=slug, display_name=slug,
                                 version='1.0.0',
                                 status=InstalledPlugin.STATUS_ACTIVE)
        db.session.add(plugin)
        db.session.commit()
        return plugin

    def test_purge_removes_only_that_plugins_rows(self, app):
        store.for_plugin('plugin-one').set('k', 1)
        store.for_plugin('plugin-two').set('k', 2)

        assert store.purge('plugin-one') == 1
        assert store.for_plugin('plugin-one').get('k') is None
        assert store.for_plugin('plugin-two').get('k') == 2

    def test_uninstall_with_purge_clears_the_store(self, app, tmp_path, monkeypatch):
        from app.services import plugin_service

        plugin = self._install_row('demo-purge')
        store.for_plugin('demo-purge').set('k', 'data')
        monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(tmp_path / 'b'))
        monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(tmp_path / 'f'))

        plugin_service.uninstall_plugin(plugin.id, purge=True)

        assert store.for_plugin('demo-purge').get('k') is None

    def test_uninstall_without_purge_keeps_the_store(self, app, tmp_path, monkeypatch):
        # Same rule the ext_* tables follow: reinstalling finds its state.
        from app.services import plugin_service

        plugin = self._install_row('demo-keep')
        store.for_plugin('demo-keep').set('k', 'data')
        monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(tmp_path / 'b'))
        monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(tmp_path / 'f'))

        plugin_service.uninstall_plugin(plugin.id, purge=False)

        assert store.for_plugin('demo-keep').get('k') == 'data'


def test_sdk_is_reachable_from_the_package(app):
    from app import plugins_sdk

    plugins_sdk.store.for_plugin('serverkit-demo').set('k', 'v')
    assert plugins_sdk.store.for_plugin('serverkit-demo').get('k') == 'v'
