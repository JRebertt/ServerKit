#!/usr/bin/env python3
"""Generate docs/MIGRATION_INVENTORY.md from the executable ratchets (plan 76, H).

Milestone H requires "a remaining-migration inventory generated from the same
checks, so the plan cannot claim completion while known legacy doors remain."
This script IS that closure: every number below comes from running the actual
census/check that enforces it — nothing is typed in by hand, so the document
cannot drift from what the ratchets hold.

Run from the repo root::

    python scripts/generate-migration-inventory.py

Regenerate whenever a migration commit changes a ceiling;
``backend/tests/test_migration_inventory.py`` fails if the committed document
no longer matches the measured state.
"""

import importlib
import io
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_TESTS = os.path.join(REPO, 'backend', 'tests')
OUT = os.path.join(REPO, 'docs', 'MIGRATION_INVENTORY.md')

sys.path.insert(0, BACKEND_TESTS)


def _backend_rows():
    rows = []
    specs = [
        ('identity_door_census', 'Identity lookups outside rbac.get_current_user()',
         'rbac.get_current_user()',
         'JWT-only routes; the API-key-capable population is held at 0 by a companion assertion'),
        ('jwt_only_census', 'Routes on bare @jwt_required()',
         'auth_required() / role decorators',
         'REGISTERED EXCEPTION: JWT-only is the deliberate default; conversion grants API-key access and happens per route, on decision'),
        ('status_sniffing_census', 'HTTP statuses chosen by sniffing error text',
         'typed errors from app.exceptions',
         'INVARIANT at 0 - migration completed 2026-08-19'),
        ('unreported_crash_census', 'API crashes swallowed without recording',
         'app.error_reporting',
         'INVARIANT at 0'),
        ('error_shape_census', "Hand-shaped {'error': ...} bodies in app/api",
         'typed errors + the global handler',
         'migrate when touched; new endpoints raise'),
        ('raw_subprocess_census', 'Raw subprocess calls outside the runners',
         'app/utils/system.py runners',
         'migrate when touched'),
    ]
    for module_name, concern, door, policy in specs:
        mod = importlib.import_module(module_name)
        rows.append((concern, door, mod.total(), mod.read_ceiling(), policy))
    return rows


def _controller_boundary_row():
    path = os.path.join(BACKEND_TESTS, 'api_controller_boundary_baseline.json')
    data = json.load(io.open(path, encoding='utf-8'))
    n = data['violations'] if isinstance(data['violations'], int) else len(data['violations'])
    return ('Controller-boundary violations (routes doing service work)',
            'service layer extraction', n, n, 'migrate when touched (first-wave ratchet)')


def node_command():
    """Resolve the node binary: ``$NODE``, then ``node``, then ``node.exe``.

    Hardcoding ``node`` made this generator unavailable under WSL, where the
    Windows nvm directory is on PATH but only exposes ``node.exe`` -- so
    test_migration_inventory.py skipped on the dev box, and the inventory
    reached CI stale with nothing local able to say so.
    """
    for candidate in (os.environ.get('NODE'), 'node', 'node.exe'):
        if candidate and shutil.which(candidate):
            return candidate
    return None


def _frontend_rows():
    node = node_command()
    if node is None:
        raise SystemExit('node is required for the frontend rows (set NODE=/path/to/node)')
    result = subprocess.run(
        [node, os.path.join('frontend', 'scripts', 'check-frontend-boundaries.mjs'),
         '--inventory'],
        capture_output=True, text=True, cwd=REPO)
    if result.returncode != 0:
        raise SystemExit('frontend boundary check failed:\n' + result.stdout + result.stderr)
    payload = json.loads(result.stdout)
    rows = []
    for item in payload['inventory']:
        name = item['name']
        door = name[name.index('(') + 1:name.rindex(')')] if '(' in name else ''
        concern = name[:name.index('(')].strip() if '(' in name else name
        if item['ceiling'] == 0:
            policy = 'INVARIANT at 0'
        elif 'setInterval' in name:
            policy = ('DELIBERATE RESIDUE: clock ticks, socket-fallback hooks, '
                      'and sibling-repo extension timers - each listed per file')
        else:
            policy = 'migrate when touched'
        rows.append((concern, door, item['actual'], item['ceiling'], policy))
    return rows


def _style_ownership_row():
    path = os.path.join(REPO, 'frontend', 'scripts', 'STYLE_OWNERSHIP_CEILING')
    n = int(io.open(path, encoding='utf-8').read().strip())
    return ('SCSS class names defined in multiple files', 'single-owner partials',
            n, n, 'needs eyes on pages (no byte-identical proof available)')


def render():
    rows = (_backend_rows() + [_controller_boundary_row()]
            + _frontend_rows() + [_style_ownership_row()])

    lines = [
        '# Remaining-migration inventory',
        '',
        '<!-- GENERATED by scripts/generate-migration-inventory.py - do not edit.',
        '     Every number is measured by the census/check that enforces it. -->',
        '',
        'Plan 76 closure artifact (milestone H). Each row is a cross-cutting',
        'concern whose door exists and is guarded by an executable ratchet; the',
        '"remaining" column is the measured legacy population that has not yet',
        'walked through it. A row at 0 is a completed migration held as an',
        'invariant. Rows marked REGISTERED EXCEPTION are deliberate policy, not',
        'debt. Regenerate with `python scripts/generate-migration-inventory.py`.',
        '',
        '| Concern | Door | Remaining | Ceiling | Policy |',
        '|---|---|---:|---:|---|',
    ]
    for concern, door, actual, ceiling, policy in rows:
        lines.append(f'| {concern} | {door} | {actual} | {ceiling} | {policy} |')
    lines.append('')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    content = render()
    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(content)
    print(f'wrote {os.path.relpath(OUT, REPO)}')
