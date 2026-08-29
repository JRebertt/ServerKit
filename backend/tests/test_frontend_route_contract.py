"""Frontend ↔ backend HTTP route contract (plan 82 §C).

Every URL the frontend API layer (frontend/src/services/api/*.js) passes to
``this.request(...)`` must resolve to a rule in the backend url map — a
backend route rename/removal otherwise surfaces as a dead button and a prod
404 found by a user. Mirror-image of test_socket_contract.py, which pins the
socket event names the same way (Python statically reading the JS source).

Scope and honesty:
- Only string/template literals passed directly to ``this.request`` are
  checked; paths built through variables are invisible to the scan (the
  extraction-count floor below keeps the regex from rotting silently).
- Matching is existence-only, not method-aware: a frontend ``${param}``
  segment matches any converter or literal segment, so the assertion is
  "some backend rule can receive this path", the rename/removal class.
"""
import re
from pathlib import Path


FRONTEND_API_DIR = (Path(__file__).resolve().parents[2]
                    / 'frontend' / 'src' / 'services' / 'api')

CALL_RE = re.compile(
    r"""this\.request\(\s*(?:'([^']*)'|"([^"]*)"|`([^`]*)`)""")

TEMPLATE_EXPR_RE = re.compile(r'\$\{[^{}]*\}')

# The scan has found ~1200 call sites; a hard floor makes a silent regex or
# layout break fail loud instead of passing vacuously.
MIN_EXTRACTED_PATHS = 400

# file-basename -> paths that legitimately do not resolve in the session
# app's url map. Keep every entry justified; an empty set is the goal.
ALLOWLIST = {
    # Registered by the external serverkit-inference extension (plan 65);
    # Sidebar only calls it when a plugin nav item declares
    # requiresCondition === 'gpuAvailable', i.e. when that extension is
    # installed and providing the route.
    'containerOps.js': {'/gpu/'},
    # Standalone-WP install route provided by the external WordPress
    # extension; Sidebar calls it only when a plugin nav item declares
    # requiresCondition === 'wpInstalled', and 404 falls back to
    # "not installed".
    'wordpress.js': {'/wordpress/standalone/status'},
}

BUILTIN_EXTENSIONS_DIR = (Path(__file__).resolve().parents[2]
                          / 'builtin-extensions')

# Prefixes owned by EXTRACTED (standalone-repo) extensions that core clients
# still probe fail-soft — the plan 52 cutover deleted their builtin dirs, so
# their plugin.json can no longer vouch for them. Kept explicit and minimal:
# each entry names the extension serving the prefix when installed. The
# core callers behind them degrade to "not installed" on 404 by design
# (Settings relay tile, the app-creation repo pickers).
EXTRACTED_EXTENSION_PREFIXES = {
    '/git': 'serverkit-git',
    '/email': 'serverkit-email',
    '/cloudflare': 'serverkit-cloudflare-ops',
}


def _extension_prefixes():
    """/api/v1-relative url_prefix of every builtin extension.

    Paths under these prefixes are owned by extensions the session app may
    not have loaded, so an unresolved path there is excused — but only
    while a plugin.json still declares the prefix, so a removed extension
    turns its frontend calls back into failures. Extracted extensions keep
    their prefixes excused via EXTRACTED_EXTENSION_PREFIXES above."""
    import json
    prefixes = dict(EXTRACTED_EXTENSION_PREFIXES)
    for manifest in sorted(BUILTIN_EXTENSIONS_DIR.glob('*/plugin.json')):
        prefix = json.loads(manifest.read_text(encoding='utf-8')).get('url_prefix', '')
        if prefix.startswith('/api/v1/'):
            prefixes[prefix[len('/api/v1'):]] = manifest.parent.name
    return prefixes


def _extract_frontend_paths():
    """(file, raw_literal, normalized_segments) for every request() literal."""
    assert FRONTEND_API_DIR.is_dir(), f'missing {FRONTEND_API_DIR}'
    seen = {}
    for js in sorted(FRONTEND_API_DIR.glob('*.js')):
        text = js.read_text(encoding='utf-8')
        for match in CALL_RE.finditer(text):
            raw = next(g for g in match.groups() if g is not None)
            path = raw.split('?', 1)[0]
            path = TEMPLATE_EXPR_RE.sub('\x00', path)
            if '$' in path or not path.startswith('/'):
                # Interpolation the regex can't flatten (nested braces) or a
                # relative/absolute-host path — out of scope for this scan.
                continue
            if path.startswith('/api/v1'):
                path = path[len('/api/v1'):] or '/'
            segments = tuple(
                '*' if '\x00' in seg else seg
                for seg in path.split('/') if seg)
            seen.setdefault((js.name, raw), segments)
    return [(f, raw, segs) for (f, raw), segs in sorted(seen.items())]


def _rule_to_pattern(rule):
    """Flask rule -> segment pattern. '<path:x>' spans 1+ segments ('**'),
    any other converter matches one ('*')."""
    pattern = []
    for seg in rule.split('/'):
        if not seg:
            continue
        if seg.startswith('<') and seg.endswith('>'):
            converter = seg[1:-1].split(':', 1)[0] if ':' in seg else ''
            pattern.append('**' if converter == 'path' else '*')
        elif '<' in seg:
            pattern.append('*')
        else:
            pattern.append(seg)
    return tuple(pattern)


def _matches(pattern, segments):
    if not pattern:
        return not segments
    head, rest = pattern[0], pattern[1:]
    if head == '**':
        return any(_matches(rest, segments[i:])
                   for i in range(1, len(segments) + 1))
    if not segments:
        return False
    if head == '*' or segments[0] == '*' or head == segments[0]:
        return _matches(rest, segments[1:])
    return False


def test_every_frontend_api_path_resolves(route_rules):
    api_patterns = [
        _rule_to_pattern(rule[len('/api/v1'):])
        for rule in route_rules if rule.startswith('/api/v1/')
    ]
    extracted = _extract_frontend_paths()
    assert len(extracted) >= MIN_EXTRACTED_PATHS, (
        f'only {len(extracted)} paths extracted — the scan regex or the '
        f'frontend api/ layout changed; fix the extractor, do not lower '
        f'the floor blindly')

    ext_prefixes = _extension_prefixes()
    missing = []
    for filename, raw, segments in extracted:
        if raw in ALLOWLIST.get(filename, ()):
            continue
        if not any(_matches(p, segments) for p in api_patterns):
            first = '/' + segments[0] if segments else '/'
            if first in ext_prefixes:
                # Extension-owned prefix; the session app didn't load that
                # extension. Excused while its plugin.json declares it.
                continue
            missing.append(f'  {filename}: {raw}')

    assert not missing, (
        'frontend api/ calls these paths but no /api/v1 rule can receive '
        'them (renamed or removed backend route, or a typo on the frontend '
        'side):\n' + '\n'.join(missing))


def test_allowlist_entries_still_needed(route_rules):
    """An allowlisted path that starts resolving must be un-allowlisted, or
    the list rots into a bypass."""
    api_patterns = [
        _rule_to_pattern(rule[len('/api/v1'):])
        for rule in route_rules if rule.startswith('/api/v1/')
    ]
    by_key = {(f, raw): segs for f, raw, segs in _extract_frontend_paths()}
    stale = []
    for filename, raws in ALLOWLIST.items():
        for raw in raws:
            segs = by_key.get((filename, raw))
            if segs is None:
                stale.append(f'  {filename}: {raw} (no longer in source)')
            elif any(_matches(p, segs) for p in api_patterns):
                stale.append(f'  {filename}: {raw} (now resolves)')
    assert not stale, 'stale ALLOWLIST entries:\n' + '\n'.join(stale)
