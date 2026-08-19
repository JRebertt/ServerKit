"""Count raw ``subprocess.*`` call sites under ``backend/app`` (plan 75 §G1).

The existing CI audit greps a hand-maintained list of eight files for three
specific bad patterns. That catches a regression in a file someone remembered
to list; it says nothing about the other 250 raw calls, and nothing at all
about a *new* file. This is the other half: a census with a checked-in ceiling
that may only go down.

A "raw call" is any ``subprocess.<fn>(...)`` where ``<fn>`` actually spawns a
process. Building an argv list, catching ``subprocess.TimeoutExpired``, or
referencing ``subprocess.PIPE`` is not a call site and is not counted.

Usage (from ``backend/``)::

    python tests/raw_subprocess_census.py            # print the count + report
    python tests/raw_subprocess_census.py --update   # write the current count as the ceiling
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
APP_DIR = os.path.join(BACKEND, 'app')
CEILING_FILE = os.path.join(HERE, 'RAW_SUBPROCESS_CEILING')

# The functions that actually spawn. `Popen` included: it is the primitive the
# others funnel through, and a migration that "removes" a subprocess.run by
# hand-rolling a Popen has not removed anything.
SPAWNING = {'run', 'call', 'check_call', 'check_output', 'getoutput',
            'getstatusoutput', 'Popen'}

# Vendored/third-party trees under app/ that are not ours to migrate.
SKIP_DIRS = {'__pycache__', 'node_modules', '.venv', 'venv'}


def _iter_py_files(root):
    # Only git-tracked files: a dev box's app/plugins/ also carries installed
    # extension copies a clean checkout never sees, and counting those gives
    # the ceiling invisible slack on CI (28 measured here vs 24 there).
    from tracked_files import is_tracked, tracked_py_files
    tracked = tracked_py_files(BACKEND)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith('.py') and is_tracked(os.path.join(dirpath, name), tracked):
                yield os.path.join(dirpath, name)


def count_file(path):
    """[(lineno, 'subprocess.run'), ...] for every spawning call in *path*."""
    try:
        tree = ast.parse(open(path, encoding='utf-8').read(), filename=path)
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in SPAWNING:
            continue
        target = func.value
        if isinstance(target, ast.Name) and target.id == 'subprocess':
            hits.append((node.lineno, f'subprocess.{func.attr}'))
    return hits


def census(root=APP_DIR):
    """{relative path: [(lineno, call), ...]} for every file with a raw call."""
    found = {}
    for path in _iter_py_files(root):
        hits = count_file(path)
        if hits:
            found[os.path.relpath(path, BACKEND).replace(os.sep, '/')] = hits
    return found


def total(found=None):
    found = census() if found is None else found
    return sum(len(v) for v in found.values())


def read_ceiling():
    with open(CEILING_FILE, encoding='utf-8') as fh:
        return int(fh.read().strip())


def write_ceiling(value):
    with open(CEILING_FILE, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(f'{value}\n')


def main(argv):
    found = census()
    count = total(found)
    if '--update' in argv:
        write_ceiling(count)
        print(f'RAW_SUBPROCESS_CEILING set to {count}')
        return 0

    ceiling = read_ceiling()
    print(f'raw subprocess call sites: {count} (ceiling {ceiling})')
    for path in sorted(found, key=lambda p: -len(found[p]))[:15]:
        print(f'  {len(found[path]):3d}  {path}')
    if count > ceiling:
        print(f'\nFAIL: {count - ceiling} new raw subprocess call site(s).')
        print('Route them through app/utils/system.py (run_checked / '
              'run_privileged / write_privileged_file), or, if a raw call is '
              'genuinely right here, raise the ceiling in the same commit and '
              'say why.')
        return 1
    if count < ceiling:
        print(f'\n{ceiling - count} fewer than the ceiling — run with --update '
              'to lock the improvement in.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
