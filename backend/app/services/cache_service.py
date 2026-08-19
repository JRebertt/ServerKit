import json
import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)

# In-memory cache fallback (used when Redis is not available)
_memory_cache = {}
_redis_client = None


def _get_redis():
    """Get Redis client, or None if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        import os
        url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        _redis_client = redis.from_url(url, decode_responses=True, socket_timeout=2)
        _redis_client.ping()
        logger.info('Redis cache connected')
        return _redis_client
    except Exception:
        _redis_client = None
        return None


class CacheService:
    """Caching service with Redis backend and in-memory fallback."""

    DEFAULT_TTL = 300  # 5 minutes

    @staticmethod
    def get(key):
        r = _get_redis()
        if r:
            try:
                val = r.get(f'sk:{key}')
                return json.loads(val) if val else None
            except Exception:
                pass

        entry = _memory_cache.get(key)
        if entry and entry['expires'] > time.time():
            return entry['value']
        elif entry:
            del _memory_cache[key]
        return None

    @staticmethod
    def set(key, value, ttl=None):
        ttl = ttl or CacheService.DEFAULT_TTL
        r = _get_redis()
        if r:
            try:
                r.setex(f'sk:{key}', ttl, json.dumps(value))
                return
            except Exception:
                pass

        _memory_cache[key] = {
            'value': value,
            'expires': time.time() + ttl,
        }

    @staticmethod
    def delete(key):
        r = _get_redis()
        if r:
            try:
                r.delete(f'sk:{key}')
            except Exception:
                pass
        _memory_cache.pop(key, None)

    @staticmethod
    def delete_pattern(pattern):
        r = _get_redis()
        if r:
            try:
                keys = r.keys(f'sk:{pattern}')
                if keys:
                    r.delete(*keys)
            except Exception:
                pass

        to_delete = [k for k in _memory_cache if k.startswith(pattern.replace('*', ''))]
        for k in to_delete:
            del _memory_cache[k]

    @staticmethod
    def flush():
        r = _get_redis()
        if r:
            try:
                keys = r.keys('sk:*')
                if keys:
                    r.delete(*keys)
            except Exception:
                pass
        _memory_cache.clear()

    @staticmethod
    def get_stats():
        r = _get_redis()
        if r:
            try:
                info = r.info('memory')
                return {
                    'backend': 'redis',
                    'used_memory': info.get('used_memory_human'),
                    'keys': r.dbsize(),
                }
            except Exception:
                pass

        return {
            'backend': 'memory',
            'keys': len(_memory_cache),
            'used_memory': 'N/A',
        }


def cached(key_template, ttl=300):
    """Decorator for caching function results."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = key_template.format(*args, **kwargs)
            result = CacheService.get(cache_key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            CacheService.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


def ttl_cached(ttl, key_fn=None):
    """Cache a function's return through CacheService for ``ttl`` seconds
    (plan 77 F2 — replaces hand-rolled module-level ``{'data':…,'timestamp':…}``
    TTL dicts; Redis benefits apply automatically wherever configured).

    The cached value must be JSON-serializable (the Redis path serializes).
    ``None`` returns are NOT cached, so a failed computation retries.
    ``key_fn(*args, **kwargs)`` derives the per-call cache key suffix; without
    it, the repr of the arguments is used (fine for hashable scalar args).
    The wrapped function gains ``.invalidate(*args, **kwargs)``.
    """
    def decorator(fn):
        prefix = f'ttlfn:{fn.__module__}.{fn.__qualname__}'

        def _key(args, kwargs):
            if key_fn is not None:
                return f'{prefix}:{key_fn(*args, **kwargs)}'
            if not args and not kwargs:
                return prefix
            return f'{prefix}:{repr(args)}:{repr(sorted(kwargs.items()))}'

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = _key(args, kwargs)
            hit = CacheService.get(key)
            if hit is not None:
                return hit
            value = fn(*args, **kwargs)
            if value is not None:
                CacheService.set(key, value, ttl=ttl)
            return value

        def invalidate(*args, **kwargs):
            CacheService.delete(_key(args, kwargs))

        wrapper.invalidate = invalidate
        wrapper.__wrapped__ = fn
        return wrapper
    return decorator
