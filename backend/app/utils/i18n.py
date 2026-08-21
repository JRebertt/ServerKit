"""Supported UI languages (plan 79 B2).

The **canonical** list is the frontend manifest,
``frontend/src/i18n/languages.json`` — that is what the browser actually loads
bundles for, and shipping a language means putting a JSON file next to it.

This module exists because the API has to validate what it stores: a user row
carrying a code the panel cannot render is a preference that silently does
nothing. Rather than have the backend fetch or parse the frontend at runtime,
the list is restated here and ``tests/test_user_language_preference.py`` fails
the build if the two ever disagree. Two lists with a parity test beats one list
the backend cannot see, and beats validating nothing at all.
"""

import re

# Keep in sync with frontend/src/i18n/languages.json (enforced by test).
SUPPORTED_LANGUAGES = (
    'en', 'es', 'zh-Hans', 'de', 'pt', 'ru', 'ko', 'id', 'zh-Hant', 'vi',
    'tr', 'fr',
)

DEFAULT_LANGUAGE = 'en'

# Shape gate applied before the allowlist so a malformed value is rejected for
# being malformed, not for being unknown.
_LANGUAGE_TAG = re.compile(r'^[a-z]{2,3}(-[a-z0-9]{2,8})*$')


def normalize_language(value):
    """Return a supported language code for ``value``, or ``None``.

    Most languages match language-only, so ``es-MX`` and ``ES`` both resolve
    to ``es``. Chinese is script-aware: regions and explicit script subtags
    resolve to ``zh-Hans`` or ``zh-Hant``.
    """
    if not isinstance(value, str):
        return None
    # Case-fold first: browsers send `es-MX`, `ES`, and `es-mx` for the same
    # thing, and a case-sensitive shape gate would reject two of the three.
    tag = value.strip().replace('_', '-').lower()
    if not tag or len(tag) > 10 or not _LANGUAGE_TAG.match(tag):
        return None
    canonical = {code.lower(): code for code in SUPPORTED_LANGUAGES}
    if tag in canonical:
        return canonical[tag]

    parts = tag.split('-')
    base = parts[0]
    if base == 'zh':
        traditional = (
            'hant' in parts
            or any(part in ('tw', 'hk', 'mo') for part in parts)
        )
        script = 'zh-hant' if traditional else 'zh-hans'
        if script in canonical:
            return canonical[script]

    return canonical.get(base)
