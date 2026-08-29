"""RATELIMIT_STORAGE_URI plumbing (flask-limiter storage backend).

Default stays in-memory — correct for the deliberate single-worker
deployment. Setting the env var surfaces the key in app.config, where
flask-limiter's init_app picks it up, which both shares limit state across
processes and silences the "in-memory storage ... not recommended for
production" warning.
"""
import importlib.util
import os
import warnings

import pytest

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.py')


@pytest.fixture
def probe_config(monkeypatch):
    """Re-evaluate config.py's class body under a patched environment.

    Private throwaway module, deliberately NOT importlib.reload(config) —
    see test_external_reverse_proxy.py's probe_config for why reload is a
    trap.
    """
    def _load(**env):
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        spec = importlib.util.spec_from_file_location('_sk_config_probe', CONFIG_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


def test_storage_uri_unset_stays_out_of_config(probe_config):
    """Unset (or empty) env var must not leak a blank URI into app.config —
    flask-limiter would hand it to the storage URI parser."""
    probed = probe_config(RATELIMIT_STORAGE_URI=None)
    assert not hasattr(probed.Config, 'RATELIMIT_STORAGE_URI')
    probed = probe_config(RATELIMIT_STORAGE_URI='')
    assert not hasattr(probed.Config, 'RATELIMIT_STORAGE_URI')


def test_storage_uri_env_is_picked_up(probe_config):
    probed = probe_config(RATELIMIT_STORAGE_URI='redis://localhost:6379/0')
    assert probed.Config.RATELIMIT_STORAGE_URI == 'redis://localhost:6379/0'
    # Inherits into every environment-specific config.
    assert probed.TestingConfig.RATELIMIT_STORAGE_URI == 'redis://localhost:6379/0'


def test_config_key_silences_in_memory_warning():
    """flask-limiter's init_app reads RATELIMIT_STORAGE_URI from app.config —
    the mechanism our config key relies on. A bare Flask app with a fresh
    Limiter keeps this clear of the shared module-level one."""
    from flask import Flask
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    bare = Flask(__name__)
    bare.config['RATELIMIT_STORAGE_URI'] = 'memory://'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        Limiter(key_func=get_remote_address).init_app(bare)
    assert not [w for w in caught if 'in-memory storage' in str(w.message)]


def test_missing_config_key_still_warns():
    """Control for the test above: without the key the warning fires, so its
    absence above is the config doing the work, not a dead assertion."""
    from flask import Flask
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    bare = Flask(__name__)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        Limiter(key_func=get_remote_address).init_app(bare)
    assert any('in-memory storage' in str(w.message) for w in caught)
