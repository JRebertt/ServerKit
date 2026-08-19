"""Structural guard for intentional raw-thread ownership."""

import ast
from pathlib import Path

from app.jobs.thread_ownership import (
    LIFECYCLE_BOUNDED_DELIVERY,
    LIFECYCLE_BOUNDED_FANOUT,
    LIFECYCLE_DURABLE_CANDIDATE,
    LIFECYCLE_PROCESS_LOOP,
    LIFECYCLE_REQUEST_STREAM,
    THREAD_OWNERSHIP,
)


APP_ROOT = Path(__file__).resolve().parents[1] / 'app'
BACKEND_ROOT = APP_ROOT.parent


def _raw_thread_sites():
    # Tracked files only: installed extension copies under app/plugins/ exist
    # on dev boxes but not in a clean checkout, and a classification entry for
    # one reads as stale on CI (extension repos own their own threads).
    from tracked_files import is_tracked, tracked_py_files
    tracked = tracked_py_files(str(BACKEND_ROOT))
    sites = set()
    for path in APP_ROOT.rglob('*.py'):
        if not is_tracked(str(path), tracked):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            qualified = (
                isinstance(func, ast.Attribute)
                and func.attr == 'Thread'
                and isinstance(func.value, ast.Name)
                and func.value.id == 'threading'
            )
            direct = isinstance(func, ast.Name) and func.id == 'Thread'
            if not (qualified or direct):
                continue

            parent = parents.get(node)
            enclosing = '<module>'
            while parent is not None:
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    enclosing = parent.name
                    break
                parent = parents.get(parent)

            target = next(
                (ast.unparse(kw.value) for kw in node.keywords if kw.arg == 'target'),
                '?',
            )
            relative = path.relative_to(BACKEND_ROOT).as_posix()
            sites.add(f'{relative}:{enclosing}:{target}')
    return sites


def test_every_raw_thread_has_an_exact_owner_classification():
    discovered = _raw_thread_sites()
    classified = set(THREAD_OWNERSHIP)
    assert discovered == classified, (
        f'unclassified={sorted(discovered - classified)}; '
        f'stale={sorted(classified - discovered)}'
    )


def test_thread_classifications_are_actionable():
    valid_lifecycles = {
        LIFECYCLE_PROCESS_LOOP,
        LIFECYCLE_REQUEST_STREAM,
        LIFECYCLE_BOUNDED_DELIVERY,
        LIFECYCLE_BOUNDED_FANOUT,
        LIFECYCLE_DURABLE_CANDIDATE,
    }
    for site, decision in THREAD_OWNERSHIP.items():
        assert decision['owner'].strip(), site
        assert decision['lifecycle'] in valid_lifecycles, site
        assert decision['rationale'].strip(), site

