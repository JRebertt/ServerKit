"""The committed API surface must match the served one (plan 82 §G.2).

OpenAPIService.generate_spec() existed but nothing snapshotted it, so a
breaking route change (rename, removal, method change) shipped invisibly to
API-key consumers, the CLI, and agents. This pins the sorted
``METHOD /path`` inventory of the spec against ``docs/API_SURFACE.md`` —
the same regenerate-and-review contract as docs/MIGRATION_INVENTORY.md:
an intentional surface change regenerates the doc in the same commit, so
every add/remove/method change is a visible reviewed diff::

    SERVERKIT_UPDATE_API_SURFACE=1 pytest tests/test_api_surface_inventory.py

Deliberately method+path only: summaries and schemas churn without breaking
anyone; the surface is what consumers dial.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                   'docs', 'API_SURFACE.md')

HEADER = (
    '# ServerKit API surface\n'
    '\n'
    'Generated from OpenAPIService.generate_spec() — do not edit by hand.\n'
    'Regenerate (backend/):\n'
    '`SERVERKIT_UPDATE_API_SURFACE=1 pytest tests/test_api_surface_inventory.py`\n'
    '\n'
)


def _measured_surface(app):
    from app.services.openapi_service import OpenAPIService
    with app.app_context(), app.test_request_context():
        spec = OpenAPIService.generate_spec()
    lines = []
    for path, ops in spec.get('paths', {}).items():
        for method in ops:
            if method.upper() in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE',
                                  'HEAD', 'OPTIONS'):
                lines.append(f'{method.upper()} {path}')
    return sorted(set(lines))


def test_committed_surface_matches_served_surface(app):
    measured = _measured_surface(app)
    assert len(measured) > 300, (
        f'only {len(measured)} operations measured — generate_spec() or the '
        f'extraction broke; fix that before trusting this gate')
    rendered = HEADER + '\n'.join(f'- `{line}`' for line in measured) + '\n'

    if os.environ.get('SERVERKIT_UPDATE_API_SURFACE') == '1':
        with open(DOC, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(rendered)

    assert os.path.exists(DOC), (
        'docs/API_SURFACE.md missing — generate it with '
        'SERVERKIT_UPDATE_API_SURFACE=1 pytest '
        'tests/test_api_surface_inventory.py')
    with open(DOC, encoding='utf-8') as fh:
        committed = fh.read()

    committed_lines = {line[3:-1] for line in committed.splitlines()
                       if line.startswith('- `') and line.endswith('`')}
    measured_lines = set(measured)

    added = sorted(measured_lines - committed_lines)
    removed = sorted(committed_lines - measured_lines)
    assert not added and not removed, (
        'API surface changed but docs/API_SURFACE.md was not regenerated.\n'
        + (f'  new operations: {added[:20]}\n' if added else '')
        + (f'  gone operations: {removed[:20]}\n' if removed else '')
        + 'If intentional, regenerate in this commit: '
          'SERVERKIT_UPDATE_API_SURFACE=1 pytest '
          'tests/test_api_surface_inventory.py — the diff is the review.')
