"""The bundled registry index must mirror the published one.

`app/data/registry_index.json` is what the Marketplace falls back to when the
live registry is unreachable, and what the test suite reads (SERVERKIT_REGISTRY_URL
set-but-empty). It was hand-maintained, and it rotted: seven entries carried a
sha256 that did not match the artifact their own `source` pointed at, at the
same version. Nothing caught it, because a wrong-but-well-formed hash looks
exactly like a right one offline, and installs only consult this file on panels
that are already having a bad day.

The offline tests below pin the cheap invariants. `test_matches_published_index`
is the one that would have caught the rot: it downloads the published index and
compares the pinned tuples. It skips when the network is unavailable so a plane
or a firewalled runner does not fail the suite, but it does NOT skip on a
mismatch.
"""
import json
import os
from pathlib import Path

import pytest

BUNDLED = Path(__file__).resolve().parent.parent / 'app' / 'data' / 'registry_index.json'
BUILTIN_DIR = Path(__file__).resolve().parent.parent.parent / 'builtin-extensions'
PUBLISHED = 'https://raw.githubusercontent.com/jhd3197/serverkit-extensions/main/index.json'
SHA256_HEX = 64


@pytest.fixture(scope='module')
def bundled():
    with open(BUNDLED, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_parses_and_declares_a_known_schema(bundled):
    assert bundled['schema_version'] in (1, 2, 3)
    assert bundled['extensions'], 'a fallback index with no entries blanks the Marketplace'


def test_slugs_are_unique(bundled):
    slugs = [e['slug'] for e in bundled['extensions']]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    assert not dupes, f'duplicate slugs: {sorted(dupes)}'


def test_installable_entries_pin_an_artifact(bundled):
    """Every non-bundled entry needs a source and a well-formed digest.

    Weak on its own -- the rot this file suffered produced hashes that pass
    every one of these checks. Kept because a malformed digest is a different,
    also-real failure, and because it costs nothing offline.
    """
    for e in bundled['extensions']:
        if e.get('bundled'):
            continue  # catalog listing for a builtin; nothing to download
        slug = e['slug']
        assert e.get('source', '').startswith('https://'), f'{slug}: source must be https'
        digest = e.get('sha256')
        assert digest, f'{slug}: no sha256, so an install cannot verify what it downloaded'
        assert len(digest) == SHA256_HEX and all(
            c in '0123456789abcdef' for c in digest
        ), f'{slug}: sha256 must be 64 lowercase hex chars'


def test_source_url_agrees_with_the_declared_version(bundled):
    """A release-asset URL carries its version; it must not contradict `version`.

    This is the offline half of the drift check: it catches the specific shape
    of staleness where `version` is bumped but `source` still points at the
    previous release's zip (or the reverse).
    """
    for e in bundled['extensions']:
        source = e.get('source', '')
        if '/releases/download/' not in source:
            continue
        tag = source.split('/releases/download/')[1].split('/')[0]
        assert tag.lstrip('v') == str(e['version']), (
            f"{e['slug']}: version {e['version']} but source points at tag {tag}"
        )


def test_bundled_entries_match_what_the_panel_actually_ships(bundled):
    """A `bundled: true` entry promises an extension that ships inside the panel.

    Those entries carry no source/sha256 -- there is nothing to download and
    nothing to checksum -- so every other check in this file skips them, and
    `test_matches_published_index` only proves the catalog agrees with the
    registry, not that either agrees with the code. A bundled entry can
    therefore name a version the panel does not ship, or an extension it does
    not ship at all, and nothing notices.

    This is the offline half of that: it needs no network and fails on the PR
    that introduces the mismatch. Only checked in this direction -- a builtin
    that is deliberately absent from the catalog is a product decision, not rot.
    """
    for e in bundled['extensions']:
        if not e.get('bundled'):
            continue
        slug = e['slug']
        manifest = BUILTIN_DIR / slug / 'plugin.json'
        assert manifest.is_file(), (
            f'{slug}: listed as bundled, but {manifest.parent.name}/plugin.json '
            f'does not exist -- the catalog offers an extension the panel does not ship'
        )
        with open(manifest, 'r', encoding='utf-8') as f:
            shipped = json.load(f)
        assert str(shipped.get('version')) == str(e.get('version')), (
            f'{slug}: catalog says {e.get("version")}, '
            f'builtin-extensions/{slug}/plugin.json ships {shipped.get("version")}'
        )


@pytest.mark.skipif(
    os.environ.get('SERVERKIT_SKIP_NETWORK_TESTS') == '1',
    reason='network tests disabled',
)
def test_matches_published_index(bundled):
    """The bundled copy must equal serverkit-extensions/index.json on main.

    Skips when the index cannot be fetched -- offline is not a failure. A
    reachable index that disagrees IS a failure: it means a panel that falls
    back to this file would install, or refuse, something different from what
    an online panel does.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(PUBLISHED, timeout=20) as r:
            published = json.load(r)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        pytest.skip(f'published index unreachable: {exc}')

    def pinned(index):
        return {
            e['slug']: (e.get('version'), e.get('source'), e.get('sha256'))
            for e in index['extensions']
        }

    ours, theirs = pinned(bundled), pinned(published)

    missing = sorted(set(theirs) - set(ours))
    extra = sorted(set(ours) - set(theirs))
    changed = sorted(s for s in set(ours) & set(theirs) if ours[s] != theirs[s])

    detail = []
    if missing:
        detail.append(f'missing from the bundled copy: {missing}')
    if extra:
        detail.append(f'present only in the bundled copy: {extra}')
    for slug in changed:
        detail.append(f'{slug}: bundled {ours[slug]} != published {theirs[slug]}')
    assert not detail, (
        'bundled registry index has drifted from the published one; '
        'regenerate it from serverkit-extensions/index.json.\n  '
        + '\n  '.join(detail)
    )
