"""Plan 77 F2 — ttl_cached: CacheService-backed TTL memoization.

Replaces hand-rolled module-level `{'data': …, 'timestamp': …}` TTL dicts;
the ratchet stops new ones from appearing in services/.
"""
import re
import time
from pathlib import Path

import pytest

from app.services.cache_service import CacheService, ttl_cached

SERVICES = Path(__file__).resolve().parents[1] / 'app' / 'services'


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    # Force the in-memory path: a real Redis on the dev box would persist
    # cached values across test runs and own TTL expiry itself.
    import app.services.cache_service as cs
    monkeypatch.setattr(cs, '_get_redis', lambda: None)
    cs._memory_cache.clear()
    yield
    cs._memory_cache.clear()


def test_caches_within_ttl_and_recomputes_after():
    calls = []

    @ttl_cached(ttl=60)
    def compute():
        calls.append(1)
        return {'n': len(calls)}

    assert compute() == {'n': 1}
    assert compute() == {'n': 1}
    assert len(calls) == 1

    compute.invalidate()
    assert compute() == {'n': 2}
    assert len(calls) == 2


def test_ttl_expiry(monkeypatch):
    calls = []

    @ttl_cached(ttl=1)
    def compute():
        calls.append(1)
        return len(calls)

    real_time = time.time
    assert compute() == 1
    monkeypatch.setattr(time, 'time', lambda: real_time() + 5)
    assert compute() == 2


def test_key_fn_separates_arguments():
    calls = []

    @ttl_cached(ttl=60, key_fn=lambda name: name)
    def compute(name):
        calls.append(name)
        return f'value-{name}'

    assert compute('a') == 'value-a'
    assert compute('b') == 'value-b'
    assert compute('a') == 'value-a'
    assert calls == ['a', 'b']


def test_none_results_are_not_cached():
    calls = []

    @ttl_cached(ttl=60)
    def flaky():
        calls.append(1)
        return None if len(calls) == 1 else 'ok'

    assert flaky() is None
    assert flaky() == 'ok'
    assert len(calls) == 2


def test_install_profile_capabilities_ride_the_decorator(app, monkeypatch):
    from app.services import install_profile_service as ips
    probes = []
    monkeypatch.setattr(ips, '_docker_usable', lambda: probes.append(1) or True)
    monkeypatch.setattr(ips, '_binary_present', lambda name: True)

    ips.get_capabilities(force_refresh=True)
    first = len(probes)
    ips.get_capabilities()
    assert len(probes) == first, 'second call within TTL must not re-probe'
    ips.get_capabilities(force_refresh=True)
    assert len(probes) == first + 1, 'force_refresh must re-probe'


def test_no_new_module_level_ttl_dicts():
    """Ratchet: no new `{'data': …, 'timestamp': …}`-style module TTL caches.

    Frozen allowlist (2026-08-19): caches whose semantics genuinely don't fit
    (non-JSON values, lock-guarded snapshots, explicit invalidation networks).
    """
    allowed = {
        'container_status_service.py',  # lock-guarded non-JSON _ContainerIndex snapshot
        'survey_service.py',            # cache-forever bundled catalog, force param
        'registry_service.py',          # remote-index engine (plan 77 F1 owns it)
        'theme_registry_service.py',    # remote-index engine (plan 77 F1 owns it)
        'template_service.py',          # remote-index engine (plan 77 F1 owns it)
        'security_feed_service.py',     # remote-index engine (plan 77 F1 owns it)
    }
    pattern = re.compile(r"^_\w*cache\w*\s*(?::[^=]+)?=\s*\{[^}]*'timestamp'", re.M)
    offenders = []
    for f in sorted(SERVICES.glob('*.py')):
        if f.name in allowed:
            continue
        if pattern.search(f.read_text(encoding='utf-8', errors='replace')):
            offenders.append(f.name)
    assert not offenders, (
        f'Hand-rolled module TTL caches in {offenders} — use '
        '@ttl_cached from cache_service (plan 77 F2).'
    )
