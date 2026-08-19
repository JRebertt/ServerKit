"""One door for call-time environment access (plan 77 F4).

Boolean env parsing existed in three incompatible variants across the app —
`('1', 'true', 'yes', 'on')` in config.py, `('1', 'true', 'yes')` in
plugin_service (where `SERVERKIT_ALLOW_PRIVATE_DOWNLOADS=on` silently read
false), and ad-hoc copies elsewhere. This module owns the parsers; config.py
imports them back. Deliberately dependency-free (os only) so config.py can
import it before the app package finishes initializing.
"""
import os

#: The one set of truthy spellings for env vars.
TRUTHY = ('1', 'true', 'yes', 'on')


def env_str(name, default=None):
    """Raw env string, ``default`` when unset."""
    value = os.environ.get(name)
    return default if value is None else value


def env_bool(name, default=False):
    """Parse a boolean env var. Accepts the usual truthy spellings; anything
    else (including unset) falls back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY


def env_int(name, default):
    """Parse an int env var, falling back to ``default`` on unset/garbage."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
