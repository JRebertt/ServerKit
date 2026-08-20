"""SDK compatibility contract (plan 25 Phase 1 #1/#2).

Locks three things:
  - the backend SDK_VERSION mirror matches the frontend `SDK_VERSION` export,
  - GET /api/v1/plugins/contributions reports it,
  - the semver-range gate (`sdk_version_satisfies`) behaves.
"""
import os
import re

import pytest

from app.utils.sdk import SDK_VERSION, sdk_version_satisfies

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SDK_JS = os.path.join(_REPO_ROOT, 'frontend', 'src', 'plugins', 'sdk', 'index.js')


def test_backend_mirror_matches_frontend_sdk_version():
    """backend/app/utils/sdk.py SDK_VERSION must equal the JS export, or the
    runtime `sdk_version` report lies to extensions."""
    with open(_SDK_JS, 'r', encoding='utf-8') as f:
        src = f.read()
    m = re.search(r'export\s+const\s+SDK_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', src)
    assert m, 'SDK_VERSION export not found in frontend/src/plugins/sdk/index.js'
    assert m.group(1) == SDK_VERSION, (
        f'SDK version drift: JS={m.group(1)!r} backend={SDK_VERSION!r}. Update both in lock-step.'
    )


def test_contributions_reports_sdk_version(client, auth_headers):
    resp = client.get('/api/v1/plugins/contributions', headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get('sdk_version') == SDK_VERSION
    assert isinstance(body.get('frontends'), dict)


@pytest.mark.parametrize('range_str,current,expected', [
    ('', '1.0.0', True),
    (None, '1.0.0', True),
    ('*', '9.9.9', True),
    ('1.0.0', '1.0.0', True),
    ('1.0.0', '1.0.1', False),
    ('^1.0.0', '1.4.2', True),
    ('^1.0.0', '2.0.0', False),
    ('^1.2.0', '1.1.0', False),
    ('~1.2.0', '1.2.9', True),
    ('~1.2.0', '1.3.0', False),
    ('>=1.0.0', '1.0.0', True),
    ('>=1.0.0', '0.9.0', False),
    ('>=1.0.0,<2.0.0', '1.5.0', True),
    ('>=1.0.0 <2.0.0', '2.0.0', False),
    ('^0.1.0', '0.1.5', True),
    ('^0.1.0', '0.2.0', False),
])
def test_sdk_version_satisfies(range_str, current, expected):
    assert sdk_version_satisfies(range_str, current) is expected


def test_sdk_version_satisfies_defaults_to_panel():
    assert sdk_version_satisfies(f'^{SDK_VERSION.split(".")[0]}.0.0') is True


# --- install-time SDK gate -------------------------------------------------
#
# Both this module's docstring and the frontend loader claimed the range was
# "checked at install" long before anything called it. The consequences split
# by extension kind: a runtime ESM extension installed fine and failed later at
# the load gate, while a builtin/in-repo extension never passes that gate at
# all, so its range went unchecked everywhere.

def _manifest(**overrides):
    base = {'name': 'demo-ext', 'display_name': 'Demo Extension', 'version': '1.0.0'}
    base.update(overrides)
    return base


def test_install_refuses_an_extension_built_for_a_newer_sdk():
    from app.services.plugin_service import _assert_manifest_sdk_compatible

    major = int(SDK_VERSION.split('.')[0])
    with pytest.raises(ValueError) as excinfo:
        _assert_manifest_sdk_compatible(_manifest(sdk_version=f'^{major + 1}.0.0'))

    message = str(excinfo.value)
    # The operator has to be able to act on it: what it needs, what we have.
    assert 'Demo Extension' in message
    assert SDK_VERSION in message
    assert f'^{major + 1}.0.0' in message


def test_install_allows_a_satisfied_range():
    from app.services.plugin_service import _assert_manifest_sdk_compatible

    major = int(SDK_VERSION.split('.')[0])
    _assert_manifest_sdk_compatible(_manifest(sdk_version=f'^{major}.0.0'))


@pytest.mark.parametrize('value', [None, '', '   ', '*'])
def test_install_fails_open_without_a_pinned_range(value):
    """Deliberate: matches the load gate's 'grace'. An extension that pins
    nothing installs anywhere rather than being blocked by a field its author
    never filled in."""
    from app.services.plugin_service import _assert_manifest_sdk_compatible

    manifest = _manifest() if value is None else _manifest(sdk_version=value)
    _assert_manifest_sdk_compatible(manifest)


def test_current_sdk_surface_is_reachable_by_a_caret_pin():
    """An extension pinning ^1.3.0 (the localization surface) must install on
    this panel — the pin authors are told to use in docs/EXTENSIONS.md."""
    from app.services.plugin_service import _assert_manifest_sdk_compatible

    _assert_manifest_sdk_compatible(_manifest(sdk_version='^1.3.0'))
