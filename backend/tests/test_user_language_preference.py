"""Per-user UI language preference (plan 79 B2).

Two things are proved here:

1. The backend's supported-language list has not drifted from the frontend
   manifest, which is the canonical one. A backend that accepts a code the
   browser has no bundle for stores a preference that silently does nothing.
2. `PUT /api/v1/auth/me` persists the choice, normalises regional tags, clears
   back to "follow the panel default", and refuses junk.
"""

import json
from pathlib import Path

import pytest

from app.utils.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / 'frontend' / 'src' / 'i18n' / 'languages.json'
)


def test_backend_language_list_matches_the_frontend_manifest():
    """The manifest is canonical; this list only exists so the API can validate.

    If this fails, the fix is almost always to update SUPPORTED_LANGUAGES in
    app/utils/i18n.py -- not to edit the manifest, which is what actually
    decides which bundles ship.
    """
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    manifest_codes = tuple(entry['code'] for entry in manifest['languages'])

    assert manifest_codes == SUPPORTED_LANGUAGES, (
        f'frontend manifest ships {manifest_codes}, '
        f'backend accepts {SUPPORTED_LANGUAGES}'
    )


def test_manifest_entries_are_complete():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    for entry in manifest['languages']:
        assert entry['dir'] in ('ltr', 'rtl'), entry
        assert entry['status'] in ('stable', 'provisional'), entry
        assert entry['name'] and entry['nativeName'], entry

    codes = [entry['code'] for entry in manifest['languages']]
    assert DEFAULT_LANGUAGE in codes
    assert len(codes) == len(set(codes)), 'duplicate language code in manifest'


@pytest.mark.parametrize('raw,expected', [
    ('en', 'en'),
    ('es', 'es'),
    ('ES', 'es'),
    ('es-MX', 'es'),        # region tags resolve language-only ...
    ('es_419', 'es'),       # ... including the underscore form
    ('en-GB', 'en'),
    ('  es  ', 'es'),
    ('fr', None),           # well-formed but not shipped
    ('zz-ZZ', None),
    ('', None),
    ('   ', None),
    ('e', None),
    ('en; DROP TABLE users', None),
    ('../../etc/passwd', None),
    ('a' * 40, None),
    (None, None),
    (12, None),
    (['en'], None),
])
def test_normalize_language(raw, expected):
    assert normalize_language(raw) == expected


def test_put_me_persists_language(client, auth_headers):
    response = client.put('/api/v1/auth/me', json={'language': 'es'},
                          headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()['user']['language'] == 'es'

    # Survives a fresh read -- the point of the column over localStorage.
    response = client.get('/api/v1/auth/me', headers=auth_headers)
    assert response.get_json()['user']['language'] == 'es'


def test_put_me_normalizes_a_regional_tag(client, auth_headers):
    response = client.put('/api/v1/auth/me', json={'language': 'es-MX'},
                          headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()['user']['language'] == 'es'


def test_put_me_rejects_an_unsupported_language(client, auth_headers):
    response = client.put('/api/v1/auth/me', json={'language': 'fr'},
                          headers=auth_headers)
    assert response.status_code == 400
    assert 'fr' in response.get_json()['error']


def test_put_me_clears_back_to_the_panel_default(client, auth_headers):
    client.put('/api/v1/auth/me', json={'language': 'es'}, headers=auth_headers)

    response = client.put('/api/v1/auth/me', json={'language': None},
                          headers=auth_headers)
    assert response.status_code == 200
    # NULL, not 'en': "follow the panel default" is its own state.
    assert response.get_json()['user']['language'] is None


def test_new_user_has_no_language_preference(client, auth_headers):
    response = client.get('/api/v1/auth/me', headers=auth_headers)
    assert response.get_json()['user']['language'] is None


def test_setup_status_exposes_the_panel_default(client):
    """The sign-in screen renders before any authenticated call can answer."""
    response = client.get('/api/v1/auth/setup-status')
    assert response.status_code == 200
    assert response.get_json()['default_language'] == DEFAULT_LANGUAGE


def test_preference_updates_do_not_burn_the_credential_throttle(client, auth_headers):
    """Switching language repeatedly must not 429.

    PUT /me is throttled at 3/minute for credential edits. Language rides the
    same route, and the client applies the change locally before the request
    lands -- so a throttled write means the UI shows Spanish while the user row
    still says English, and the choice quietly reverts on the next sign-in from
    another browser. That is precisely the promise the column exists to keep.
    """
    for code in ('es', 'en', 'es', 'en', 'es'):
        response = client.put('/api/v1/auth/me', json={'language': code},
                              headers=auth_headers)
        assert response.status_code == 200, response.get_json()


def test_credential_updates_are_still_throttled(client, auth_headers):
    """The exemption must not open the door it was carved out of."""
    statuses = [
        client.put('/api/v1/auth/me', json={'password': 'new-password-123'},
                   headers=auth_headers).status_code
        for _ in range(5)
    ]
    assert 429 in statuses, statuses
