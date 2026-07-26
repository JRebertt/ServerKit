"""Searchable entities contributed by plugins (plugins_sdk.search).

A plugin's objects were unreachable from the command palette — the one place
users are told to look — because the fan-out was a hardcoded list of core
types. Registering a provider puts them in it, and the palette renders unknown
types already, so it takes no frontend change.

The provider is trusted to scope its own rows (core applies no post-filter), but
NOT trusted with the shape: the cap, the type tag and the path are enforced on
the host side, which is what most of this file pins down.
"""

import pytest
from flask_jwt_extended import create_access_token

from app import db
from app.models.application import Application
from app.services import search_provider_registry
from app.services.search_service import SearchService


@pytest.fixture(autouse=True)
def _clean_registry():
    search_provider_registry.clear()
    yield
    search_provider_registry.clear()


@pytest.fixture
def owner(app):
    """A developer with one application, and their auth headers."""
    from app.models import User
    from werkzeug.security import generate_password_hash

    with app.app_context():
        user = User(email='srch_sdk@test.local', username='srch_sdk',
                    password_hash=generate_password_hash('x'),
                    role=User.ROLE_DEVELOPER, is_active=True)
        db.session.add(user)
        db.session.commit()
        db.session.add(Application(name='FindableApp', app_type='php',
                                   user_id=user.id, root_path='/srv/findable'))
        db.session.commit()
        return {'id': user.id,
                'headers': {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}}


def _row(label='World one', path='/minecraft/worlds/1', **extra):
    return {'label': label, 'path': path, **extra}


class TestRegistry:
    def test_registers_and_resolves(self):
        provider = lambda query: []
        search_provider_registry.register('demo.thing', provider)
        assert search_provider_registry.get('demo.thing') is provider
        assert 'demo.thing' in search_provider_registry.types()

    def test_core_types_cannot_be_hijacked(self):
        # Rows tagged 'service' or 'vault' are trusted to have been scoped by
        # core, so a plugin must not be able to mint them.
        for entity_type in search_provider_registry.CORE_TYPES:
            with pytest.raises(ValueError):
                search_provider_registry.register(entity_type, lambda query: [])

    def test_duplicate_registration_needs_replace(self):
        search_provider_registry.register('demo.thing', lambda query: [])
        with pytest.raises(ValueError):
            search_provider_registry.register('demo.thing', lambda query: [])
        search_provider_registry.register('demo.thing', lambda query: [], replace=True)

    def test_rejects_non_callable(self):
        with pytest.raises(ValueError):
            search_provider_registry.register('demo.thing', 'not-callable')


class TestRowCleaning:
    def test_tags_rows_with_the_registered_type(self):
        rows = search_provider_registry.clean_rows(
            'demo.thing', [_row(type='service')], 5)
        # A provider claiming to be a core type is overruled, not obeyed.
        assert rows[0]['type'] == 'demo.thing'

    def test_fills_in_a_missing_sublabel(self):
        assert search_provider_registry.clean_rows('demo.thing', [_row()], 5)[0]['sublabel'] == ''

    def test_drops_rows_without_a_label_or_path(self):
        bad = [{'path': '/x'}, {'label': 'no path'}, {'label': '  ', 'path': '/x'}]
        assert search_provider_registry.clean_rows('demo.thing', bad, 5) == []

    def test_drops_off_site_paths(self):
        # The palette hands `path` straight to navigate(); a protocol-relative
        # value would walk the user off the panel.
        bad = [_row(path='//evil.example'), _row(path='https://evil.example'),
               _row(path='relative')]
        assert search_provider_registry.clean_rows('demo.thing', bad, 5) == []

    def test_enforces_the_cap_even_when_the_provider_ignores_it(self):
        many = [_row(label=f'World {i}', path=f'/w/{i}') for i in range(50)]
        assert len(search_provider_registry.clean_rows('demo.thing', many, 5)) == 5

    def test_survives_junk(self):
        assert search_provider_registry.clean_rows('demo.thing', None, 5) == []
        assert search_provider_registry.clean_rows('demo.thing', ['nope', 7], 5) == []


class TestFanOut:
    def test_contributed_rows_reach_the_endpoint(self, app, client, owner):
        search_provider_registry.register(
            'minecraft.world',
            lambda query: [_row(label='Overworld', sublabel='Minecraft world',
                                path='/minecraft/worlds/1')])

        res = client.get('/api/v1/search?q=over', headers=owner['headers'])

        assert res.status_code == 200
        rows = res.get_json()['results']
        contributed = [r for r in rows if r['type'] == 'minecraft.world']
        assert contributed == [{'type': 'minecraft.world', 'label': 'Overworld',
                                'sublabel': 'Minecraft world',
                                'path': '/minecraft/worlds/1'}]

    def test_a_broken_provider_does_not_break_search(self, app, client, owner):
        def explode(query):
            raise RuntimeError('provider is broken')

        search_provider_registry.register('demo.broken', explode)

        res = client.get('/api/v1/search?q=findable', headers=owner['headers'])

        # The core rows still arrive — a bad provider degrades to no rows of
        # its type rather than 500-ing the palette.
        assert res.status_code == 200
        assert any(r['type'] == 'service' for r in res.get_json()['results'])

    def test_provider_is_told_who_is_asking(self, app, owner):
        seen = {}

        def capture(query):
            seen['term'] = query.term
            seen['user_id'] = query.user.id
            seen['limit'] = query.limit
            seen['workspace_id'] = query.workspace_id
            return []

        search_provider_registry.register('demo.capture', capture)

        with app.app_context():
            from app.models import User
            SearchService.search(User.query.get(owner['id']), 'findable')

        # Without the user the provider cannot scope its rows, which is the
        # contract it is required to honour.
        assert seen['term'] == 'findable'
        assert seen['user_id'] == owner['id']
        assert seen['limit'] == 5
        assert seen['workspace_id'] is None

    def test_short_terms_never_reach_providers(self, app, client, owner):
        called = []
        search_provider_registry.register('demo.thing',
                                          lambda query: called.append(1) or [])

        assert client.get('/api/v1/search?q=a', headers=owner['headers']).status_code == 200
        assert called == []


class TestSdkFacade:
    def test_sdk_registers_and_lists(self, app):
        from app import plugins_sdk

        plugins_sdk.search.register('demo.sdk', lambda query: [])
        assert 'demo.sdk' in plugins_sdk.search.types()

    def test_sdk_exposes_the_query_type(self):
        from app import plugins_sdk

        query = plugins_sdk.search.Query(term='abc', limit=3)
        assert (query.term, query.limit, query.user) == ('abc', 3, None)
