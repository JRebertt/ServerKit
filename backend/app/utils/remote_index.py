"""CachedRemoteIndex — the one remote-catalog engine (plan 77 F1).

The fetch → TTL cache → last-good fallback → bundled-file fallback pipeline
was re-implemented per catalog (extension registry, theme registry, …) and
has drifted in production before (bundled-index and proxy-rewrite
incidents). This class owns the hardened behavior once; services stay thin
normalizers and future catalogs get it free.

Semantics (the superset that theme_registry had already hardened to):

- Success: entries cached for ``ttl`` seconds, ``source='remote'``.
- Env override: unset ⇒ ``default_url``; set-but-EMPTY ⇒ explicitly disabled
  (bundled copy only — also how the test suite stays offline).
- Fetch failure with a last-good copy: serve it and stamp the clock so the
  TTL applies (every call retrying a dead upstream would stall each request
  behind the fetch timeout).
- Fetch failure with nothing cached: serve the bundled file, but hold it
  only ``error_ttl`` seconds before retrying upstream — the panel recovers
  quickly when the registry comes back, without hammering it.
- ``normalize_fn(payload, base_url)`` turns the raw JSON payload into the
  entry list; relative asset paths resolve against the URL actually fetched.
"""
import json
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)


class CachedRemoteIndex:
    def __init__(self, name, env_var, default_url, normalize_fn,
                 bundled_path=None, bundled_base_url=None,
                 ttl=3600, ttl_env_var=None, error_ttl=60,
                 timeout=15, user_agent=None):
        self.name = name
        self.env_var = env_var
        self.default_url = default_url
        self.normalize_fn = normalize_fn
        self.bundled_path = bundled_path
        self.bundled_base_url = bundled_base_url
        self.error_ttl = error_ttl
        self.timeout = timeout
        self.user_agent = user_agent or f'ServerKit-{name}/1.0'
        self.ttl = ttl
        if ttl_env_var:
            try:
                self.ttl = int(os.environ.get(ttl_env_var, str(ttl)))
            except ValueError:
                self.ttl = ttl
        # Kept as a plain dict (not attributes) so a service module can alias
        # it (`_cache = _index._cache`) for tests that inspect/twiddle it.
        self._cache = {'ts': 0.0, 'entries': None, 'source': None}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ url
    def url(self):
        """Live index URL, resolved per call so env changes apply without a
        restart. Unset ⇒ default; set-but-empty ⇒ disabled (empty string)."""
        value = os.environ.get(self.env_var)
        if value is None:
            return self.default_url
        return value.strip()

    # ------------------------------------------------------------------ get
    def get(self, force=False):
        """Return the entries, refreshing when stale. Never raises."""
        now = time.time()
        with self._lock:
            if (not force and self._cache['entries'] is not None
                    and (now - self._cache['ts']) < self.ttl):
                return self._cache['entries']

        entries = None
        source = None
        failed = False
        try:
            entries = self._fetch_remote()
            if entries is not None:
                source = 'remote'
        except Exception as exc:
            failed = True
            logger.warning('%s index fetch failed (%s): %s',
                           self.name, self.url(), exc)

        with self._lock:
            if entries is None:
                if self._cache['entries'] is not None:
                    # Serve last-good; stamp the clock so the TTL applies.
                    self._cache['ts'] = now
                    return self._cache['entries']
                entries = self._load_bundled()
                source = 'bundled'
            ts = now - (self.ttl - self.error_ttl) if failed else now
            self._cache.update({'entries': entries, 'ts': ts, 'source': source})
            return entries

    def invalidate(self):
        with self._lock:
            self._cache.update({'ts': 0.0, 'entries': None, 'source': None})

    def source_label(self):
        return self._cache.get('source')

    # -------------------------------------------------------------- internals
    def _fetch_remote(self):
        url = self.url()
        if not url:
            return None
        resp = requests.get(url, timeout=self.timeout, headers={
            'Accept': 'application/json',
            'User-Agent': self.user_agent,
        })
        resp.raise_for_status()
        return self.normalize_fn(resp.json(), url)

    def _load_bundled(self):
        if not self.bundled_path:
            return []
        try:
            with open(self.bundled_path, 'r', encoding='utf-8') as f:
                return self.normalize_fn(json.load(f), self.bundled_base_url)
        except Exception as exc:
            logger.warning('Could not read bundled %s index: %s', self.name, exc)
            return []
