"""Count routes still authenticated by bare ``@jwt_required()`` (plan 76, A).

``auth_required()`` (app/middleware/rbac.py) is milestone A's door: it accepts
a JWT *or* an ``X-API-Key``, resolving both through the same identity path.
``@jwt_required()`` accepts only the JWT.

That difference is why this census exists and why it is NOT a migration
countdown to zero. Converting a route from ``@jwt_required()`` to
``auth_required()`` **grants API-key callers access to that route** — an
expansion of the authenticated surface, not a refactor. The recorded decision
(2026-08-19, closing the plan's open question) is:

    JWT-only is the deliberate default. A route becomes API-key capable
    one at a time, when an API-key use case exists for it, in a commit
    that says so — never as a mechanical sweep.

So the ceiling is an adoption ratchet in one direction only: the population
may shrink as routes are deliberately converted, and may not grow — a NEW
route must pick a policy decorator (``auth_required()`` or a role decorator),
not bare ``@jwt_required()``. The identity-door ratchet's third assertion
(tests/test_identity_door_ratchet.py) is what makes each conversion safe: it
fails the moment a route becomes API-key capable while still resolving its
caller from the JWT.

Counting is AST-based over ``app/api``: a decorator ``jwt_required`` (called
or bare) on any function.

Usage (from ``backend/``)::

    python tests/jwt_only_census.py            # print the count + report
    python tests/jwt_only_census.py --update   # write the count as the ceiling
"""

import ast
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
API_DIR = os.path.join(BACKEND, 'app', 'api')
# Extension routes are the same authenticated surface as core routes, and were
# invisible here until 2026-08-31: the serverkit-status blueprint carried 15
# bare-@jwt_required() routes this census never saw, so the ratchet could not
# object when a review proposed converting them wholesale.
#
# They are counted from builtin-extensions/ (the SOURCE), not app/plugins/ (the
# live copy the loader imports). The two are pinned equal by
# test_builtin_extension_drift.py, so either would give the same answer on a
# clean checkout -- but app/plugins/ is mostly GITIGNORED, so counting it makes
# the number depend on which extensions a given box happens to have installed.
# That is not hypothetical: it shipped a ceiling of 611 from a dev box where CI
# measured 591.
#
# For the same reason the population is filtered to git-TRACKED files: a stale
# ignored directory left behind by an extraction (cloudflare-ops, git, localkit
# after plan 52) still sits on some working copies and would otherwise be
# counted. Without git (release tarball, Docker build) the tree has no such
# leftovers and the unfiltered walk agrees.
EXT_DIR = os.path.join(BACKEND, os.pardir, 'builtin-extensions')
SCAN_DIRS = (API_DIR, EXT_DIR)
CEILING_FILE = os.path.join(HERE, 'JWT_ONLY_CEILING')

SKIP_DIRS = {'__pycache__'}


def _rel(path):
    return os.path.relpath(path, BACKEND).replace(os.sep, '/')


def _decorator_name(dec):
    while isinstance(dec, ast.Call):
        dec = dec.func
    return getattr(dec, 'attr', getattr(dec, 'id', ''))


def count_file(path):
    """Return [(lineno, function_name)] of jwt_required-decorated functions."""
    try:
        tree = ast.parse(open(path, encoding='utf-8').read())
    except (SyntaxError, UnicodeDecodeError):
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if _decorator_name(dec) == 'jwt_required':
                found.append((node.lineno, node.name))
                break
    return sorted(found)


REPO = os.path.dirname(BACKEND)


def _repo_rel(path):
    return os.path.relpath(path, REPO).replace(os.sep, '/')


def _tracked_files():
    """Repo-relative paths git tracks, or None when git cannot answer.

    Run from the repo ROOT, not backend/: `git ls-files` only lists paths under
    its working directory, so from backend/ the builtin-extensions entries are
    absent and every extension file would be filtered out as "untracked".
    """
    try:
        proc = subprocess.run(['git', 'ls-files'], cwd=REPO,
                              capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def census():
    found = {}
    tracked = _tracked_files()
    for root in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in sorted(filenames):
                if not name.endswith('.py'):
                    continue
                path = os.path.join(dirpath, name)
                if tracked is not None and _repo_rel(path) not in tracked:
                    continue
                rel = _rel(path)
                hits = count_file(path)
                if hits:
                    found[rel] = hits
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
