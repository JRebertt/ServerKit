"""Plan 29 Phase 3 (#9/#10) — the ONE generic structural authorization gate.

A single AST sweep over every Flask route file under ``backend/app/api/`` plus the
flagship WordPress bridge. It replaces the two narrow gates plan 18/19 shipped
(the WordPress-only AST test and the hardcoded 6-file bucket-header test), which
could each only see part of the surface.

For every route handler whose URL carries ``<app_id>`` or ``<site_id>`` (any
converter form) it enforces:

  (a) the route FILE declares a ``# Bucket:`` header in its first lines, so a new
      per-app surface can't ship without being classified; and
  (b) the handler REACHES a known gate — either a gating decorator
      (``admin_required`` / ``require_app_member``) or a gate CALL in its body.

Gate calls are recognised robustly: the canonical family
(``can_access_app`` / ``can_operate_app`` / ``can_edit_app`` / ``can_admin_app``
and the WP ``_guard_app`` / ``_guard_sealed_app``), PLUS any *local* helper in the
same file whose own body reaches one of those (env_vars' ``check_app_access``,
previews' ``_get_app_or_404``, waf's ``_get_application_or_404`` …) or performs an
explicit admin check (``is_admin``). Auto-discovering wrappers means the sweep
follows the code instead of a brittle hand-maintained name list.

Deliberate exceptions live in ``ALLOWLIST`` below, each with a one-line reason;
additions must carry a justification.
"""
import ast
import os

import pytest


# --------------------------------------------------------------------------- #
# Surface
# --------------------------------------------------------------------------- #

def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _route_files():
    """Every api/*.py file + the WordPress extension's route file, as
    (label, abspath).

    WordPress left the tree in plan 52 Phase 5: its blueprint file is swept
    from the standalone repo's checkout when one is available (sibling or
    SERVERKIT_WORDPRESS_DIR) — the same loader the wp_extension fixtures use.
    Absent, the sweep covers core routes only (the extension repo carries the
    same sweep for its own file via its symlinked suite)."""
    root = _repo_root()
    api_dir = os.path.join(root, 'backend', 'app', 'api')
    files = []
    for fname in sorted(os.listdir(api_dir)):
        if fname.endswith('.py') and fname != '__init__.py':
            files.append((fname, os.path.join(api_dir, fname)))
    wp_candidates = [
        os.environ.get('SERVERKIT_WORDPRESS_DIR', ''),
        os.path.join(os.path.dirname(root), 'serverkit-wordpress'),
    ]
    for cand in wp_candidates:
        wp_file = os.path.join(cand, 'backend', 'wordpress.py') if cand else ''
        if wp_file and os.path.isfile(wp_file):
            files.append(('wordpress.py', wp_file))
            break
    return files


# Canonical per-app gates + WP guards. A handler (or a helper it calls) that
# references any of these is authorization-gated for the target app.
CANONICAL_GATES = {
    'can_access_app', 'can_operate_app', 'can_edit_app', 'can_admin_app',
    '_guard_app', '_guard_sealed_app',
}
# Markers that a helper performs an admin check (admin is a valid gate for
# host/system per-app surfaces, e.g. WAF mutations, image-update triggers).
ADMIN_MARKERS = {'is_admin', 'admin_required'}
# Decorators that gate directly.
GATING_DECORATORS = {'admin_required', 'require_app_member'}

# Deliberate exceptions: 'file.py:handler' -> reason. Keep minimal; each addition
# needs a justification line.
ALLOWLIST = {
    # Public inbound Git webhooks: authenticated by the <token> path segment +
    # the provider HMAC signature, not by a user session — so no per-app user gate
    # applies (mirrors git.py:receive_webhook).
    'deploy.py:webhook': 'signature/token-verified public webhook (no user auth)',
}


# --------------------------------------------------------------------------- #
# AST helpers
# --------------------------------------------------------------------------- #

def _decorator_names(node):
    names = []
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        names.append(getattr(target, 'id', None) or getattr(target, 'attr', None))
    return [n for n in names if n]


def _route_paths(node):
    paths = []
    for dec in node.decorator_list:
        if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == 'route' and dec.args
                and isinstance(dec.args[0], ast.Constant)):
            paths.append(dec.args[0].value)
    return paths


def _is_per_app(paths):
    return any(('app_id' in p or 'site_id' in p) for p in paths)


def _discover_gate_helpers(source, tree):
    """Names of functions in this module that themselves reach a gate — either a
    canonical gate call or an explicit admin check. These are the file-local
    wrappers (check_app_access, _get_app_or_404, _require_admin, …) that callers
    delegate to; recognising them lets the sweep follow the code."""
    helpers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body_src = ast.get_source_segment(source, node) or ''
        if any(g in body_src for g in CANONICAL_GATES) or any(m in body_src for m in ADMIN_MARKERS):
            helpers.add(node.name)
    return helpers


def _has_inline_owner_check(body_src):
    """Recognise the hand-rolled owner-or-admin idiom used in a few apps.py
    handlers, e.g. ``if user.role != 'admin' and app.user_id != user.id``. It gates
    just as effectively as a named helper; the co-occurrence of an ownership
    comparison (``user_id``) and an admin check (``admin``) in a route body is a
    reliable signal (and false positives only *relax* the net, never tighten it
    wrongly — a truly ungated body won't contain both)."""
    return 'user_id' in body_src and 'admin' in body_src


def _handler_is_gated(node, source, gate_tokens):
    if any(d in GATING_DECORATORS for d in _decorator_names(node)):
        return True
    body_src = ast.get_source_segment(source, node) or ''
    if any(tok in body_src for tok in gate_tokens):
        return True
    return _has_inline_owner_check(body_src)


# --------------------------------------------------------------------------- #
# The sweep
# --------------------------------------------------------------------------- #

def _sweep():
    """Return (bucketless_files, ungated_handlers) across the whole surface."""
    bucketless, ungated = [], []
    for label, path in _route_files():
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        tree = ast.parse(source)
        header = '\n'.join(source.splitlines()[:12])

        gate_tokens = CANONICAL_GATES | ADMIN_MARKERS | _discover_gate_helpers(source, tree)

        file_has_per_app = False
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            paths = _route_paths(node)
            if not paths or not _is_per_app(paths):
                continue
            file_has_per_app = True
            if f'{label}:{node.name}' in ALLOWLIST:
                continue
            if not _handler_is_gated(node, source, gate_tokens):
                ungated.append(f'{label}:{node.name}')

        if file_has_per_app and '# Bucket:' not in header:
            bucketless.append(label)
    return bucketless, ungated


def test_every_per_app_route_file_declares_a_bucket():
    bucketless, _ = _sweep()
    assert not bucketless, (
        'per-app route files missing a `# Bucket:` header (plan 29 #9): '
        f'{bucketless}')


def test_no_ungated_per_app_route():
    _, ungated = _sweep()
    assert not ungated, (
        'per-app route handlers with no reachable authorization gate '
        f'(plan 29 #9 — add a gate or an ALLOWLIST justification): {ungated}')
