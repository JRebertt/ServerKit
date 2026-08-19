"""Count HTTP statuses chosen by pattern-matching an error message (plan 76, C).

    status = 403 if 'denied' in result.get('error', '').lower() else 400

This is what a service returning ``{'success': False, 'error': '<prose>'}``
forces on its callers: the service knows perfectly well that the failure was a
denial, throws that away, and the route reconstructs it by searching the
sentence. The status code is then coupled to the *wording*. Rephrasing "Access
denied: path not in allowed directories" to "You do not have access to this
path" silently turns a 403 into a 400, and nothing fails — not a test, not a
type checker, not a lint rule.

The fix is milestone C's: services raise typed errors from ``app.exceptions``
and routes return data, so nobody re-derives what the service already knew.
The migration is COMPLETE (2026-08-19): all 23 baseline sites across 8 files
were converted domain by domain, and the ceiling is 0. (The 'eight callers'
blocker recorded here earlier was a substring-grep artifact — ``file_service``
had exactly one consumer.)

The ratchet now holds an invariant, not a countdown: any new site that chooses
a status by inspecting message text — or by probing for an 'error' key, the
same coupling one step removed — fails this census.

A site is counted when a conditional expression chooses between two HTTP status
codes, and its test inspects string content — ``in``, ``.lower()``,
``.startswith()``, ``.endswith()``. Choosing a status from a real signal (a
typed exception, an enum, a boolean field) is not counted, because that is the
thing this is asking for.

Usage (from ``backend/``)::

    python tests/status_sniffing_census.py            # print the count + report
    python tests/status_sniffing_census.py --update   # write the count as the ceiling
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
APP_DIR = os.path.join(BACKEND, 'app')
CEILING_FILE = os.path.join(HERE, 'STATUS_SNIFFING_CEILING')

SKIP_DIRS = {'__pycache__', 'node_modules', '.venv', 'venv'}
STRING_TESTS = {'lower', 'upper', 'startswith', 'endswith', 'strip', 'casefold'}


def _rel(path):
    return os.path.relpath(path, BACKEND).replace(os.sep, '/')


def _is_status(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and 100 <= node.value <= 599)


def _test_inspects_a_string(test):
    """True when the branch is decided by looking inside some text."""
    for n in ast.walk(test):
        if isinstance(n, ast.Compare):
            for op in n.ops:
                if isinstance(op, (ast.In, ast.NotIn)):
                    return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in STRING_TESTS:
            return True
    return False


def count_file(path):
    """Return [(lineno, snippet)] of sniffed statuses in one file."""
    try:
        with open(path, encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    lines = source.split('\n')
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.IfExp):
            continue
        if not (_is_status(node.body) and _is_status(node.orelse)):
            continue
        if not _test_inspects_a_string(node.test):
            continue
        snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ''
        found.append((node.lineno, snippet[:100]))
    return sorted(found)


def census():
    found = {}
    for dirpath, dirnames, filenames in os.walk(APP_DIR):
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
    for rel in sorted(found, key=lambda p: (-len(found[p]), p)):
        print('%-40s %d' % (rel, len(found[rel])))
        for lineno, snippet in found[rel][:3]:
            print('    L%-5d %s' % (lineno, snippet))
    print('\ntotal: %d' % count)
    if '--update' in sys.argv:
        _write_ceiling(count)
        print('ceiling updated to %d' % count)
    else:
        try:
            print('ceiling: %d' % read_ceiling())
        except FileNotFoundError:
            print('no ceiling file yet; run with --update')
