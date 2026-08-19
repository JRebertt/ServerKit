"""Count API handlers that answer 500 without reporting the crash (plan 76, B).

The global 500 handler is the only thing that logs a crash and writes it to the
centralized error log behind ``/monitoring/errors``. A route that catches
``Exception`` itself answers before that handler runs, so its crash is recorded
nowhere — the errors page is empty precisely because someone "handled" it.

A handler is counted when all three hold:

  * it catches ``Exception``/``BaseException``/bare
  * it returns a response instead of re-raising (so the global handler is out)
  * that response carries HTTP 500 (it is telling the caller "this crashed")

and it does NOT go through ``app.error_reporting`` — either
``unexpected_response(exc)`` for the standard body, or ``record_unexpected(exc)``
where the route must keep its own caller-facing wording (``sso.py`` does: an
auth failure should not read as a generic crash on the login page).

Scope is ``app/api`` on purpose. A service catching an exception and returning a
value is making a domain decision, not answering an HTTP request; forcing those
through an HTTP-shaped door would be the wrong convergence. The HTTP boundary is
where "this is a crash" is decided.

NOT counted, and deliberately still open (see the plan's milestone C): the
handlers that swallow a crash and answer **200**. Those are a bigger problem —
a failure reported as success — but converging them is the response-envelope
work, not this row.

Usage (from ``backend/``)::

    python tests/unreported_crash_census.py            # print the count + report
    python tests/unreported_crash_census.py --update   # write the count as the ceiling
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
API_DIR = os.path.join(BACKEND, 'app', 'api')
CEILING_FILE = os.path.join(HERE, 'UNREPORTED_CRASH_CEILING')

REPORTERS = {'unexpected_response', 'record_unexpected'}

# One level of indirection is followed on purpose. `queue_bus.py` answered 21
# crashes through a local `_handle_error(e)` that returned 500 with str(e), and
# the first version of this census could not see the 500 because it was in the
# helper rather than the handler. A ratchet that a one-line helper defeats is
# not a ratchet.


def _rel(path):
    return os.path.relpath(path, BACKEND).replace(os.sep, '/')


def _is_blanket(handler):
    t = handler.type
    if t is None:
        return True
    if isinstance(t, ast.Name) and t.id in ('Exception', 'BaseException'):
        return True
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in ('Exception', 'BaseException')
                   for e in t.elts)
    return False


def _reports(handler):
    for n in ast.walk(handler):
        if isinstance(n, ast.Call):
            fn = n.func
            name = getattr(fn, 'attr', None) or getattr(fn, 'id', None)
            if name in REPORTERS:
                return True
    return False


def _delegates_to(handler, helper_names):
    """Returns the result of a same-module helper that itself answers 500."""
    if any(isinstance(n, ast.Raise) for n in ast.walk(handler)):
        return False
    for n in ast.walk(handler):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Call):
            fn = n.value.func
            name = getattr(fn, 'id', None) or getattr(fn, 'attr', None)
            if name in helper_names:
                return True
    return False


def _answers_500(handler):
    """Returns a response carrying 500, and does not re-raise."""
    if any(isinstance(n, ast.Raise) for n in ast.walk(handler)):
        return False
    for n in ast.walk(handler):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple) \
                and len(n.value.elts) == 2:
            status = n.value.elts[1]
            if isinstance(status, ast.Constant) and status.value == 500:
                return True
    return False


def _module_helpers_answering_500(tree):
    """Module-level functions that themselves return a 500 without reporting."""
    helpers = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _answers_500(node) and not _reports(node):
            helpers.add(node.name)
    return helpers


def count_file(path):
    """Return [(lineno, function_name)] of unreported crash answers in one file."""
    try:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
    except (SyntaxError, UnicodeDecodeError):
        return []

    via_helper = _module_helpers_answering_500(tree)

    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.ExceptHandler):
                    owner.setdefault(id(child), node.name)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_blanket(node) or _reports(node):
            continue
        answers = _answers_500(node) or _delegates_to(node, via_helper)
        if not answers:
            continue
        found.append((node.lineno, owner.get(id(node), '<module>')))
    return sorted(found)


def census():
    found = {}
    if not os.path.isdir(API_DIR):
        return found
    for name in sorted(os.listdir(API_DIR)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(API_DIR, name)
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
        hits = found[rel]
        print('%-45s %d  (%s)' % (
            rel, len(hits), ', '.join('L%d %s()' % h for h in hits[:5])))
    print('\ntotal: %d' % count)
    if '--update' in sys.argv:
        _write_ceiling(count)
        print('ceiling updated to %d' % count)
    else:
        try:
            print('ceiling: %d' % read_ceiling())
        except FileNotFoundError:
            print('no ceiling file yet; run with --update')
