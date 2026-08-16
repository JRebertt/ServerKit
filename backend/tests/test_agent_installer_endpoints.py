"""Tests for the unauthenticated fleet-agent installer endpoints.

Regression cover for issue #101: ``GET /api/v1/servers/install.sh`` answered 404
on every Docker deployment because the Dockerfile never copied ``scripts/`` into
the image. Nothing caught it, and no ordinary endpoint test could have: pytest
runs from the source tree, where ``scripts/install.sh`` is always present. The
bug lived in the *packaging*, not the code.

So this file tests both halves:

1. the endpoints behave (they serve a script, unauthenticated, and fail loudly
   with a server-error status when the file is absent), and
2. the packaging invariant -- every installer the panel serves off disk is
   actually copied into the image by the Dockerfile.

Test (2) is the one that would have caught #101.
"""

import os
import re
from unittest.mock import patch

import pytest

from app.api import servers as servers_api
from app.api.servers import _get_scripts_dir


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The installers the panel serves over HTTP, and the route each is served from.
SERVED_INSTALLERS = [
    ('install.sh', '/api/v1/servers/install.sh'),
    ('install.ps1', '/api/v1/servers/install.ps1'),
]


# ---------------------------------------------------------------- endpoints


@pytest.mark.parametrize('filename,route', SERVED_INSTALLERS)
def test_installer_is_served_without_auth(client, filename, route):
    """Enrollment happens on a box that has no panel credentials yet.

    The one-liner is ``curl ... | sudo bash`` run on a brand new server, so these
    two routes must stay reachable anonymously.
    """
    response = client.get(route)

    assert response.status_code == 200, (
        f'{route} returned {response.status_code}; the panel prints this URL in '
        f'its own Add Server dialog, so a non-200 means fleet enrollment is dead'
    )
    assert len(response.get_data(as_text=True)) > 0


def test_install_sh_serves_the_real_script(client):
    body = client.get('/api/v1/servers/install.sh').get_data(as_text=True)

    assert body.startswith('#!/bin/bash')
    # Placeholder substitution ran: the shipped file says your-serverkit.com,
    # the served copy must point at this panel instead.
    assert 'https://your-serverkit.com' not in body
    assert '--token' in body


def test_install_ps1_serves_the_real_script(client):
    body = client.get('/api/v1/servers/install.ps1').get_data(as_text=True)

    assert 'Install-ServerKitAgent' in body
    assert 'https://your-serverkit.com' not in body


def test_missing_installer_is_a_server_error_not_a_404(client, monkeypatch):
    """A missing installer is this panel's fault, and must not read as a bad URL.

    #101 was reported as "incorrect paths in setup" because the panel answered
    404 -- the reporter reasonably concluded they had the wrong URL, when in fact
    the server was missing a file it was supposed to ship. 5xx moves the blame to
    where it belongs and stops the next person re-filing the same wrong diagnosis.
    """
    monkeypatch.setenv('SERVERKIT_SCRIPTS_DIR', os.path.join(REPO_ROOT, 'no-such-dir'))

    for _filename, route in SERVED_INSTALLERS:
        response = client.get(route)

        assert response.status_code >= 500, (
            f'{route} answered {response.status_code} for a missing file; 4xx '
            f'blames the caller for a server-side packaging fault'
        )
        payload = response.get_json()
        # The operator needs the path that was actually searched, not a bare
        # "not found" -- that is the single fact that makes this diagnosable.
        assert 'searched_path' in payload
        assert 'no-such-dir' in payload['searched_path']


def test_scripts_dir_env_override_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv('SERVERKIT_SCRIPTS_DIR', str(tmp_path))
    assert _get_scripts_dir() == str(tmp_path)


# ---------------------------------------------------------------- packaging


def _dockerfile_copied_paths():
    """Every source path the root Dockerfile COPYs out of the build context."""
    with open(os.path.join(REPO_ROOT, 'Dockerfile'), 'r', encoding='utf-8') as f:
        dockerfile = f.read()

    # Join line continuations so a wrapped COPY is still one instruction.
    dockerfile = re.sub(r'\\\s*\n', ' ', dockerfile)

    copied = set()
    for line in dockerfile.splitlines():
        line = line.strip()
        if not line.upper().startswith('COPY '):
            continue
        args = [a for a in line.split()[1:] if not a.startswith('--')]
        if len(args) < 2:
            continue
        # Last arg is the destination; everything before it is a source. Sources
        # on a `COPY --from=<stage>` come from another stage, not the repo.
        if '--from=' in line:
            continue
        copied.update(args[:-1])
    return copied


@pytest.mark.parametrize('filename,_route', SERVED_INSTALLERS)
def test_dockerfile_ships_every_installer_the_panel_serves(filename, _route):
    """The invariant that #101 violated.

    The panel reads these files from its own filesystem at request time. If the
    Dockerfile does not copy them, the endpoints 404 in every container while
    passing every test in this suite -- because pytest runs against the source
    tree, where the files always exist. Assert the packaging directly.
    """
    copied = _dockerfile_copied_paths()

    assert f'scripts/{filename}' in copied, (
        f'scripts/{filename} is served by the panel at request time but the '
        f'Dockerfile never copies it into the image, so the endpoint will 404 in '
        f'every Docker deployment. Dockerfile COPY sources found: {sorted(copied)}'
    )


@pytest.mark.parametrize('filename,_route', SERVED_INSTALLERS)
def test_installer_exists_where_the_panel_looks_for_it(filename, _route):
    """Source-tree layout check: the resolver must point at the real files."""
    path = os.path.join(_get_scripts_dir(), filename)
    assert os.path.isfile(path), f'{filename} not found at resolved path {path}'


def test_served_installers_are_self_contained(filename='install.sh'):
    """They must not source scripts/lib -- the image ships only these two files.

    If an installer ever grows a `source scripts/lib/...`, shipping just the two
    files stops being sufficient and the Dockerfile has to copy more.
    """
    path = os.path.join(_get_scripts_dir(), filename)
    with open(path, 'r', encoding='utf-8') as f:
        body = f.read()

    assert not re.search(r'^\s*(source|\.)\s+\S*scripts/lib', body, re.MULTILINE), (
        'install.sh now depends on scripts/lib; the Dockerfile copies only '
        'scripts/install.sh and scripts/install.ps1, so update it to match'
    )


# ------------------------------------------------- agent release coordinates
#
# The second half of #101. The Go agent moved out of this monorepo into
# jhd3197/serverkit-agent and now publishes plain vX.Y.Z releases; nothing here
# followed it. The panel kept asking jhd3197/ServerKit for `agent-v*` tags that
# exist in no repo, so /agent/version answered 503 to every agent polling for an
# update and the served installer downloaded from a 404. Fixing the Dockerfile
# alone would only have moved the failure one step later.


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# Mirrors the real release list, malformed "v" tag and all.
_RELEASES = [
    {'tag_name': 'v', 'published_at': 'x', 'html_url': 'u', 'assets': []},
    {
        'tag_name': 'v1.2.0',
        'published_at': '2026-01-01T00:00:00Z',
        'html_url': 'https://github.com/jhd3197/serverkit-agent/releases/tag/v1.2.0',
        'assets': [
            {'name': 'serverkit-agent-1.2.0-linux-amd64.tar.gz',
             'browser_download_url': 'https://example/linux-amd64'},
            {'name': 'checksums.txt', 'browser_download_url': 'https://example/checksums'},
        ],
    },
    {'tag_name': 'v1.1.0', 'published_at': 'y', 'html_url': 'u', 'assets': []},
]


@pytest.fixture(autouse=True)
def _clear_release_cache():
    """The release lookup memoises for 5 minutes at module scope."""
    servers_api._releases_cache['data'] = None
    servers_api._releases_cache['expires'] = None
    yield
    servers_api._releases_cache['data'] = None
    servers_api._releases_cache['expires'] = None


def test_agent_repo_default_points_at_the_agent_repo():
    assert servers_api.AGENT_GITHUB_REPO == 'jhd3197/serverkit-agent'


def test_latest_agent_release_queries_the_agent_repo(app):
    with app.app_context():
        with patch.object(servers_api.requests, 'get',
                          return_value=_FakeResponse(_RELEASES)) as mock_get:
            release = servers_api._get_latest_agent_release()

        url = mock_get.call_args[0][0]

    assert 'jhd3197/serverkit-agent' in url, (
        f'agent releases were requested from {url}; the binaries are published '
        f'in jhd3197/serverkit-agent'
    )
    assert release is not None
    # "v" must not win, and the tag must not be mangled by a prefix strip.
    assert release['version'] == '1.2.0'
    assert release['tag'] == 'v1.2.0'
    assert release['assets']['linux-amd64'] == 'https://example/linux-amd64'


def test_release_lookup_ignores_malformed_and_non_version_tags(app):
    """A release list with nothing usable must resolve to None, not to ''."""
    junk = [
        {'tag_name': 'v', 'published_at': 'x', 'html_url': 'u', 'assets': []},
        {'tag_name': 'nightly', 'published_at': 'x', 'html_url': 'u', 'assets': []},
    ]
    with app.app_context():
        with patch.object(servers_api.requests, 'get', return_value=_FakeResponse(junk)):
            assert servers_api._get_latest_agent_release() is None


def test_served_install_sh_points_at_the_agent_repo(client):
    """End of the chain: what the box actually downloads has to exist.

    Asserting on the *served* body, after placeholder substitution -- that is the
    text `curl | bash` executes.
    """
    body = client.get('/api/v1/servers/install.sh').get_data(as_text=True)

    assert 'jhd3197/serverkit-agent' in body
    # The dead tag scheme must not survive anywhere that becomes a URL.
    live_agent_v = [
        line for line in body.splitlines()
        if 'agent-v' in line and not line.lstrip().startswith('#')
    ]
    assert not live_agent_v, f'served installer still builds agent-v* URLs: {live_agent_v}'


def test_served_install_ps1_points_at_the_agent_repo(client):
    body = client.get('/api/v1/servers/install.ps1').get_data(as_text=True)

    assert 'jhd3197/serverkit-agent' in body
    live_agent_v = [
        line for line in body.splitlines()
        if 'agent-v' in line and not line.lstrip().startswith('#')
    ]
    assert not live_agent_v, f'served installer still builds agent-v* URLs: {live_agent_v}'
