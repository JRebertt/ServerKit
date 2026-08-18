"""Count identity lookups that bypass ``rbac.get_current_user()`` (plan 76, A).

``app/middleware/rbac.get_current_user()`` is the one door that knows about
both authentication mechanisms: it returns ``g.api_key_user`` when the request
carried an ``X-API-Key``, and falls back to the JWT otherwise. Anything that
reaches for the JWT directly to answer "who is calling" is wrong for API-key
requests, and wrong in a way that does not look like a bug at the call site::

    user = User.query.get(get_jwt_identity())   # RuntimeError under an API key

``auth_required()`` deliberately skips ``verify_jwt_in_request()`` once the API
key middleware has authenticated, so there is no JWT context to read and
``get_jwt_identity()`` *raises*. Behind a policy decorator that raise surfaces
as a 500; inside the blanket ``try/except`` that service helpers wrap it in, it
silently degrades to ``user_id=None`` and the audit trail loses the actor.

Two shapes are counted, because fixing only the first just moves the bug:

    direct    User.query.get(get_jwt_identity())
    indirect  uid = get_jwt_identity()  ...  User.query.get(uid)

Deliberately NOT counted:

  * ``app/middleware/rbac.py`` itself — it is the door.
  * ``get_jwt_identity()`` used as a token/identity value rather than to load a
    user (issuing a token, comparing ids, logging). Those are not identity
    *lookups* and converging them is a different question.
  * ``app/api/auth.py`` — the token endpoints are JWT-only by construction; an
    API key cannot mint or refresh a JWT session. They are listed as a checked
    exception below so that a NEW bypass there still shows up.

Usage (from ``backend/``)::

    python tests/identity_door_census.py            # print the count + report
    python tests/identity_door_census.py --update   # write the count as the ceiling
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
APP_DIR = os.path.join(BACKEND, 'app')
CEILING_FILE = os.path.join(HERE, 'IDENTITY_DOOR_CEILING')

SKIP_DIRS = {'__pycache__', 'node_modules', '.venv', 'venv'}

# The door itself, and the JWT-only token endpoints it cannot serve.
EXEMPT = {
    'app/middleware/rbac.py',
    'app/api/auth.py',
}

# Model classes whose `.query.get(...)` means "load the calling user".
USER_MODELS = {'User'}


def _rel(path):
    return os.path.relpath(path, BACKEND).replace(os.sep, '/')


def _iter_py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith('.py'):
                yield os.path.join(dirpath, name)


def _is_jwt_identity_call(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'get_jwt_identity')


def _is_user_query_get(node):
    """Match ``<UserModel>.query.get(...)`` and return the Call node."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr != 'get':
        return False
    query = node.func.value
    if not (isinstance(query, ast.Attribute) and query.attr == 'query'):
        return False
    model = query.value
    return isinstance(model, ast.Name) and model.id in USER_MODELS


def count_file(path):
    """Return a list of (lineno, shape) bypasses in one file."""
    try:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
    except (SyntaxError, UnicodeDecodeError):
        return []

    found = []

    # Names bound to get_jwt_identity() anywhere in the module. Scoping this
    # per-function would be more precise, but a name that holds the JWT
    # identity in one function and something else in another is a trap of its
    # own; treating the whole module as one namespace errs toward reporting.
    jwt_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_jwt_identity_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    jwt_names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if _is_jwt_identity_call(node.value) and isinstance(node.target, ast.Name):
                jwt_names.add(node.target.id)

    for node in ast.walk(tree):
        if not _is_user_query_get(node) or not node.args:
            continue
        arg = node.args[0]
        if _is_jwt_identity_call(arg):
            found.append((node.lineno, 'direct'))
        elif isinstance(arg, ast.Name) and arg.id in jwt_names:
            found.append((node.lineno, 'indirect'))
        elif (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                and arg.func.id in ('int', 'str') and arg.args
                and (_is_jwt_identity_call(arg.args[0])
                     or (isinstance(arg.args[0], ast.Name) and arg.args[0].id in jwt_names))):
            found.append((node.lineno, 'indirect'))

    return sorted(found)


def census():
    """Return {relative_path: [(lineno, shape), ...]} for non-exempt files."""
    found = {}
    for path in _iter_py_files(APP_DIR):
        rel = _rel(path)
        if rel in EXEMPT:
            continue
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
    for rel in sorted(found, key=lambda p: (-len(found[p]), p)):
        shapes = found[rel]
        print('%-55s %d  (%s)' % (
            rel, len(shapes), ', '.join('L%d %s' % (l, s) for l, s in shapes[:6])))
    print('\ntotal: %d' % count)
    if '--update' in sys.argv:
        _write_ceiling(count)
        print('ceiling updated to %d' % count)
    else:
        try:
            print('ceiling: %d' % read_ceiling())
        except FileNotFoundError:
            print('no ceiling file yet; run with --update')
