"""Count hand-rolled subprocess stubs in the test suite (plan 82 §G1).

tests/subprocess_stub.py is the shared stubbing kit: scripted commands,
hard-failing UnscriptedCommand, sudo/basename normalization, and the
popen_guard hook so a stubbed exec still obeys the sbin-PATH rule. A test
that instead monkeypatches ``subprocess.run``/``Popen``/... by hand gets
none of that — its execs are invisible to the runtime guard and an
unscripted command can fabricate returncode=0.

Every other convergence in this repo has a census + ceiling; this one did
not, so adoption stalled roughly half-way. Same contract as the others:
the count may only go down. New tests use the ``fake_subprocess`` fixture.

Counted: patches whose target is the ``subprocess`` module itself —
``monkeypatch.setattr(subprocess, 'run', ...)``,
``monkeypatch.setattr('subprocess.run', ...)``, ``patch('subprocess.run')``,
``patch.object(subprocess, 'run')``. Patching a service door
(``patch.object(mod, 'run_privileged')``) is fine and not counted.

Usage (from ``backend/``)::

    python tests/hand_rolled_subprocess_stub_census.py            # report
    python tests/hand_rolled_subprocess_stub_census.py --update   # set ceiling
"""

import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
CEILING_FILE = os.path.join(HERE, 'STUB_ADOPTION_CEILING')

# The kit itself, its own tests, and this census's harness are exempt: they
# must touch subprocess directly to do their jobs.
EXEMPT = {
    'tests/subprocess_stub.py',
    'tests/test_subprocess_stub.py',
    'tests/popen_guard.py',
    'tests/test_popen_guard.py',
    'tests/conftest.py',
    'tests/hand_rolled_subprocess_stub_census.py',
    'tests/test_stub_adoption_ratchet.py',
}


def _is_subprocess_target(node):
    """Does this patch-target argument point at the subprocess module?"""
    if isinstance(node, ast.Name) and node.id == 'subprocess':
        return True
    if isinstance(node, ast.Attribute):
        # e.g. some_module.subprocess
        return node.attr == 'subprocess'
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
        return value == 'subprocess' or value.startswith('subprocess.')
    return False


def count_file(path):
    """[(lineno, description), ...] for every hand-rolled subprocess patch."""
    try:
        tree = ast.parse(open(path, encoding='utf-8').read(), filename=path)
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        # monkeypatch.setattr(...) / patch(...) / mock.patch(...) /
        # patch.object(...) / mock.patch.object(...)
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name not in ('setattr', 'patch', 'object'):
            continue
        if name == 'object':
            # only patch.object / mock.patch.object, not any .object(...)
            base = func.value if isinstance(func, ast.Attribute) else None
            base_name = (base.attr if isinstance(base, ast.Attribute)
                         else base.id if isinstance(base, ast.Name) else '')
            if base_name != 'patch':
                continue
        if _is_subprocess_target(node.args[0]):
            hits.append((node.lineno, f'{name}({ast.unparse(node.args[0])}, ...)'))
    return hits


def census():
    """{relative path: [(lineno, desc), ...]} over tracked test files."""
    from tracked_files import is_tracked, tracked_py_files
    tracked = tracked_py_files(BACKEND)
    found = {}
    for name in sorted(os.listdir(HERE)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(HERE, name)
        rel = os.path.relpath(path, BACKEND).replace(os.sep, '/')
        if rel in EXEMPT or not is_tracked(path, tracked):
            continue
        hits = count_file(path)
        if hits:
            found[rel] = hits
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
        print(f'STUB_ADOPTION_CEILING set to {count}')
        return 0

    ceiling = read_ceiling()
    print(f'hand-rolled subprocess stubs in tests: {count} (ceiling {ceiling})')
    for path in sorted(found, key=lambda p: -len(found[p])):
        print(f'  {len(found[path]):3d}  {path}')
    if count > ceiling:
        print(f'\nFAIL: {count - ceiling} new hand-rolled subprocess stub(s).')
        print('Use the shared fake_subprocess fixture (tests/subprocess_stub.py) '
              'instead — it hard-fails unscripted commands and keeps the '
              'sbin-PATH guard in force.')
        return 1
    if count < ceiling:
        print(f'\n{ceiling - count} fewer than the ceiling — run with --update '
              'to lock the improvement in.')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv[1:]))
