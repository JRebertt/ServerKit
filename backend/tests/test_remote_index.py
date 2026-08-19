"""Plan 77 F1 — CachedRemoteIndex: the one remote-catalog engine.

No network: the fetcher is monkeypatched. These pin the hardened semantics
(last-good under full TTL after a failure; bundled held only error_ttl) that
the per-service copies used to drift on.
"""
import json
import time

import pytest

from app.utils.remote_index import CachedRemoteIndex


def _normalize(payload, base_url):
    items = payload.get('items') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [{'slug': x['slug'], 'base': base_url} for x in items if x.get('slug')]


def _index(tmp_path, monkeypatch, env=None, bundled=None, **kwargs):
    if env is not None:
        monkeypatch.setenv('X_INDEX_URL', env)
    else:
        monkeypatch.delenv('X_INDEX_URL', raising=False)
    bundled_path = None
    if bundled is not None:
        bundled_path = tmp_path / 'bundled.json'
        bundled_path.write_text(json.dumps(bundled), encoding='utf-8')
    return CachedRemoteIndex(
        name='X', env_var='X_INDEX_URL',
        default_url='https://example.test/index.json',
        normalize_fn=_normalize,
        bundled_path=str(bundled_path) if bundled_path else None,
        bundled_base_url='bundled://',
        ttl=100, error_ttl=10,
        **kwargs,
    )


class _Fetch:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        result = self.results.pop(0) if self.results else self.results_last
        if isinstance(result, Exception):
            raise result
        self.results_last = result
        return result


def test_success_caches_within_ttl(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch)
    fetch = _Fetch([[{'slug': 'a', 'base': 'https://example.test/index.json'}]])
    monkeypatch.setattr(idx, '_fetch_remote', fetch)
    first = idx.get()
    assert first[0]['slug'] == 'a'
    assert idx.source_label() == 'remote'
    assert idx.get() is first
    assert fetch.calls == 1


def test_force_refetches(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch)
    fetch = _Fetch([[{'slug': 'a'}], [{'slug': 'b'}]])
    monkeypatch.setattr(idx, '_fetch_remote', fetch)
    idx.get()
    assert idx.get(force=True)[0]['slug'] == 'b'
    assert fetch.calls == 2


def test_ttl_expiry_refetches(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch)
    fetch = _Fetch([[{'slug': 'a'}], [{'slug': 'b'}]])
    monkeypatch.setattr(idx, '_fetch_remote', fetch)
    idx.get()
    idx._cache['ts'] -= idx.ttl + 1
    assert idx.get()[0]['slug'] == 'b'


def test_failure_serves_last_good_under_full_ttl(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch)
    fetch = _Fetch([[{'slug': 'good'}], RuntimeError('down')])
    monkeypatch.setattr(idx, '_fetch_remote', fetch)
    idx.get()
    idx._cache['ts'] -= idx.ttl + 1
    served = idx.get()
    assert served[0]['slug'] == 'good'
    assert fetch.calls == 2
    # last-good is stamped with the full TTL — the next call must NOT retry
    idx.get()
    assert fetch.calls == 2


def test_failure_with_nothing_serves_bundled_for_error_ttl_only(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch,
                 bundled={'items': [{'slug': 'bundled-entry'}]})
    fetch = _Fetch([RuntimeError('down'), [{'slug': 'live'}]])
    monkeypatch.setattr(idx, '_fetch_remote', fetch)
    served = idx.get()
    assert served[0]['slug'] == 'bundled-entry'
    assert idx.source_label() == 'bundled'
    # inside the error_ttl window: no retry
    assert idx.get()[0]['slug'] == 'bundled-entry'
    assert fetch.calls == 1
    # after the error_ttl window (but well under the full TTL): retried
    idx._cache['ts'] -= idx.error_ttl + 1
    assert idx.get()[0]['slug'] == 'live'
    assert fetch.calls == 2


def test_bundled_normalize_uses_bundled_base_url(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch, env='',  # disabled: bundled only
                 bundled={'items': [{'slug': 's'}]})
    served = idx.get()
    assert served[0]['base'] == 'bundled://'
    assert idx.source_label() == 'bundled'


def test_env_url_resolution(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch)
    assert idx.url() == 'https://example.test/index.json'
    monkeypatch.setenv('X_INDEX_URL', 'https://override.test/i.json')
    assert idx.url() == 'https://override.test/i.json'
    monkeypatch.setenv('X_INDEX_URL', '')
    assert idx.url() == ''


def test_invalidate_clears_cache(tmp_path, monkeypatch):
    idx = _index(tmp_path, monkeypatch)
    fetch = _Fetch([[{'slug': 'a'}], [{'slug': 'b'}]])
    monkeypatch.setattr(idx, '_fetch_remote', fetch)
    idx.get()
    idx.invalidate()
    assert idx.source_label() is None
    assert idx.get()[0]['slug'] == 'b'
