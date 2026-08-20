"""Supported UI languages (plan 79 B2).

The **canonical** list is the frontend manifest,
``frontend/src/i18n/languages.json`` — that is what the browser actually loads
bundles for, and shipping a language means putting a JSON file next to it.

This module exists because the API has to validate what it stores: a user row
carrying a code the panel cannot render is a preference that silently does
nothing. Rather than have the backend fetch or parse the frontend at runtime,
the list is restated here and ``tests/test_i18n_language_manifest.py`` fails
the build if the two ever disagree. Two lists with a parity test beats one list
the backend cannot see, and beats validating nothing at all.
"""

import re

# Keep in sync with frontend/src/i18n/languages.json (enforced by test).
SUPPORTED_LANGUAGES = ('en', 'es')

DEFAULT_LANGUAGE = 'en'

# Shape gate applied before the allowlist so a malformed value is rejected for
# being malformed, not for being unknown.
_LANGUAGE_TAG = re.compile(r'^[a-z]{2,3}(-[a-z0-9]{2,8})*$')


def normalize_language(value):
    """Return a supported language code for ``value``, or ``None``.

    Matches language-only, so ``es-MX`` and ``ES`` both resolve to ``es`` —
    the panel ships no region-specific bundles, and rejecting a region tag
    would reject most real browser values.
    """
    if not isinstance(value, str):
        return None
    # Case-fold first: browsers send `es-MX`, `ES`, and `es-mx` for the same
    # thing, and a case-sensitive shape gate would reject two of the three.
    tag = value.strip().replace('_', '-').lower()
    if not tag or len(tag) > 10 or not _LANGUAGE_TAG.match(tag):
        return None
    if tag in SUPPORTED_LANGUAGES:
        return tag
    base = tag.split('-')[0]
    return base if base in SUPPORTED_LANGUAGES else None
