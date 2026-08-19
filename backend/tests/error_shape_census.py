"""Count hand-shaped API error bodies (plan 76, B).

Milestone B's door is ``app/exceptions.py`` + the global handler: a route (or
the service under it) raises a typed error and the handler owns the JSON body,
the status code, and the ``X-Request-ID`` correlation. A hand-shaped

    return jsonify({'error': 'App not found'}), 404

answers with none of that — no ``code``, no ``request_id`` — and every one is
a place where the error contract can drift (and has: the same failure returns
400, 404, or 409 depending on which file answers it).

This population is large and its conversion is "migrate when touched"
(invariant 9 — no repo-wide rewrite). The census makes that policy
enforceable: the count may only go down. New endpoints raise typed errors.

A site is counted when a ``return`` in ``app/api`` yields an error-shaped
mapping — a dict literal whose keys include ``'error'`` — either directly or
through ``jsonify``. The door's own products are not counted: raising a typed
error, or answering through ``app.error_reporting``.

Usage (from ``backend/``)::

    python tests/error_shape_census.py            # print the count + report
    python tests/error_shape_census.py --update   # write the count as the ceiling
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
API_DIR = os.path.join(BACKEND, 'app', 'api')
CEILING_FILE = os.path.join(HERE, 'ERROR_SHAPE_CEILING')

SKIP_DIRS = {'__pycache__'}


def _rel(path):
    return os.path.relpath(path, BACKEND).replace(os.sep, '/')


def _is_error_dict(node):
    return (isinstance(node, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == 'error'
                    for k in node.keys))


def _error_shaped(value):
    """The returned expression carries a hand-built {'error': ...} body."""
    if _is_error_dict(value):
        return True
    if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id == 'jsonify' and value.args
            and _is_error_dict(value.args[0])):
        return True
    if isinstance(value, ast.Tuple) and value.elts:
        return _error_shaped(value.elts[0])
    return False


def count_file(path):
    """Return [(lineno, snippet)] of hand-shaped error returns in one file."""
    try:
        with open(path, encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []
    lines = source.split('\n')
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Return) and node.value is not None):
            continue
        if _error_shaped(node.value):
            snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ''
            found.append((node.lineno, snippet[:100]))
    return sorted(found)


def census():
    found = {}
    for dirpath, dirnames, filenames in os.walk(API_DIR):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if not name.endswith('.py'):
                continue
            path = os.path.join(dirpath, name)
            hits = count_file(path)
            if hits:
                found[_rel(path)] = hits
    return found


def total(found=None):
    if found is None:
        found = census()
    return sum(len(v) for v in found.values())


def read_ceiling():
    with open(CEILING_FILE, encoding='utf-8') as f:
        return int(f.read().strip())


def _write_ceiling(value):
    with open(CEILING_FILE, 'w', encoding='utf-8') as f:
        f.write('%d\n' % value)


if __name__ == '__main__':
    found = census()
    count = total(found)
    for rel in sorted(found, key=lambda p: (-len(found[p]), p))[:15]:
        print('%-40s %d' % (rel, len(found[rel])))
    print('\ntotal: %d' % count)
    if '--update' in sys.argv:
        _write_ceiling(count)
        print('ceiling updated to %d' % count)
    else:
        try:
            print('ceiling: %d' % read_ceiling())
        except FileNotFoundError:
            print('no ceiling file yet; run with --update')
