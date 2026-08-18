"""Inventory architectural boundary crossings in Flask API controllers.

The scanner deliberately uses the Python AST instead of text matching so
comments and strings do not become debt. A call-site fingerprint excludes line
numbers, which keeps the baseline stable when surrounding code moves, while
still recording the controller function and normalized call expression.

Run this file with ``--write-baseline`` after intentionally removing boundary
crossings. Any newly discovered call site should first be moved behind a
service; accepting one into the baseline requires an explicit reviewed diff.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = BACKEND_ROOT / 'app' / 'api'
BASELINE_PATH = Path(__file__).with_name('api_controller_boundary_baseline.json')

SUBPROCESS_CALLS = {
    'subprocess.call',
    'subprocess.check_call',
    'subprocess.check_output',
    'subprocess.Popen',
    'subprocess.run',
}
OS_MUTATIONS = {
    'chmod', 'chown', 'lchmod', 'link', 'makedirs', 'mkdir', 'mknod',
    'remove', 'removedirs', 'rename', 'renames', 'replace', 'rmdir',
    'symlink', 'truncate', 'unlink',
}
SHUTIL_MUTATIONS = {
    'copy', 'copy2', 'copyfile', 'copymode', 'copystat', 'copytree',
    'move', 'rmtree',
}
PATH_MUTATIONS = {
    'chmod', 'hardlink_to', 'link_to', 'mkdir', 'rename', 'replace',
    'rmdir', 'symlink_to', 'touch', 'unlink', 'write_bytes', 'write_text',
}
WRITE_OPEN_MODES = {'a', 'w', 'x', '+'}


@dataclass(frozen=True)
class BoundaryCall:
    fingerprint: str
    category: str
    file: str
    function: str
    expression: str


def _dotted_name(node: ast.AST, aliases: dict[str, str] | None = None) -> str | None:
    if isinstance(node, ast.Name):
        return (aliases or {}).get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value, aliases)
        return f'{parent}.{node.attr}' if parent else None
    return None


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for imported in node.names:
                local = imported.asname or imported.name.split('.')[0]
                aliases[local] = imported.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for imported in node.names:
                if imported.name == '*':
                    continue
                local = imported.asname or imported.name
                aliases[local] = f'{node.module}.{imported.name}'
    return aliases


def _is_controller(tree: ast.Module, aliases: dict[str, str]) -> bool:
    return any(
        isinstance(node, ast.Call)
        and _dotted_name(node.func, aliases) in {'Blueprint', 'flask.Blueprint'}
        for node in ast.walk(tree)
    )


def _contains_model_query(node: ast.AST) -> bool:
    """Recognize Flask-SQLAlchemy ``Model.query*`` entry points."""
    return any(
        isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Name)
        and child.value.id[:1].isupper()
        and (child.attr == 'query' or child.attr.startswith('query_'))
        for child in ast.walk(node)
    )


def _open_writes(call: ast.Call, aliases: dict[str, str]) -> bool:
    if _dotted_name(call.func, aliases) not in {'open', 'Path.open', 'pathlib.Path.open'}:
        return False
    mode_node = call.args[1] if len(call.args) > 1 else next(
        (keyword.value for keyword in call.keywords if keyword.arg == 'mode'),
        None,
    )
    return (
        isinstance(mode_node, ast.Constant)
        and isinstance(mode_node.value, str)
        and any(marker in mode_node.value for marker in WRITE_OPEN_MODES)
    )


def _path_constructor_mutation(call: ast.Call, aliases: dict[str, str]) -> bool:
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in PATH_MUTATIONS:
        return False
    receiver = call.func.value
    return (
        isinstance(receiver, ast.Call)
        and _dotted_name(receiver.func, aliases) in {'Path', 'pathlib.Path'}
    )


def _category(call: ast.Call, aliases: dict[str, str]) -> str | None:
    dotted = _dotted_name(call.func, aliases)
    direct_session = dotted and (
        dotted.startswith('db.session.') or '.db.session.' in dotted
    )
    if direct_session or _contains_model_query(call.func):
        return 'persistence'
    if dotted in SUBPROCESS_CALLS:
        return 'subprocess'
    if dotted and (
        (dotted.startswith('os.') and dotted.rsplit('.', 1)[-1] in OS_MUTATIONS)
        or (dotted.startswith('shutil.') and dotted.rsplit('.', 1)[-1] in SHUTIL_MUTATIONS)
    ):
        return 'filesystem'
    if _path_constructor_mutation(call, aliases) or _open_writes(call, aliases):
        return 'filesystem'
    return None


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names = []
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(current.name)
        current = parents.get(current)
    return '.'.join(reversed(names)) if names else '<module>'


def _normalized_expression(call: ast.Call) -> str:
    return re.sub(r'\s+', ' ', ast.unparse(call)).strip()


def scan_source(source: str, relative_path: str = 'api/example.py') -> list[BoundaryCall]:
    """Scan one controller source string; primarily useful for detector tests."""
    tree = ast.parse(source, filename=relative_path)
    aliases = _import_aliases(tree)
    if not _is_controller(tree, aliases):
        return []

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    categorized = {
        node: category
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (category := _category(node, aliases)) is not None
    }

    def nested_in_same_call_chain(node: ast.Call, category: str) -> bool:
        current: ast.AST = node
        parent = parents.get(current)
        while parent is not None:
            follows_receiver = (
                isinstance(parent, ast.Attribute) and parent.value is current
            )
            follows_function = isinstance(parent, ast.Call) and parent.func is current
            if not (follows_receiver or follows_function):
                return False
            if isinstance(parent, ast.Call) and categorized.get(parent) == category:
                return True
            current, parent = parent, parents.get(parent)
        return False

    discovered = []
    occurrences: Counter[tuple[str, str, str]] = Counter()
    for node, category in categorized.items():
        if nested_in_same_call_chain(node, category):
            continue
        function = _enclosing_function(node, parents)
        expression = _normalized_expression(node)
        occurrence_key = (function, category, expression)
        occurrences[occurrence_key] += 1
        ordinal = occurrences[occurrence_key]
        fingerprint = (
            f'{relative_path}::{function}::{category}::{expression}::{ordinal}'
        )
        discovered.append(BoundaryCall(
            fingerprint=fingerprint,
            category=category,
            file=relative_path,
            function=function,
            expression=expression,
        ))
    return sorted(discovered, key=lambda item: item.fingerprint)


def scan_api_controllers() -> list[BoundaryCall]:
    discovered = []
    for path in sorted(API_ROOT.glob('*.py')):
        relative = path.relative_to(BACKEND_ROOT / 'app').as_posix()
        discovered.extend(scan_source(path.read_text(encoding='utf-8'), relative))
    return sorted(discovered, key=lambda item: item.fingerprint)


def _default_owner(relative_path: str) -> dict[str, str]:
    domain = Path(relative_path).stem.replace('_', ' ')
    return {
        'owner': f'ServerKit backend / {domain} domain',
        'rationale': (
            f'Legacy {domain} controllers still cross a persistence or host-operation '
            'boundary; move each call into an app.services use case before removing it.'
        ),
    }


def write_baseline(path: Path = BASELINE_PATH) -> dict:
    calls = scan_api_controllers()
    previous = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8')).get('owners', {})
    files = sorted({call.file for call in calls})
    payload = {
        'schema_version': 1,
        'policy': (
            'Exact reviewed inventory of direct persistence, subprocess, and filesystem '
            'mutation calls in Flask API controllers. New calls are forbidden; remove '
            'entries as controllers delegate to services.'
        ),
        'counts': dict(sorted(Counter(call.category for call in calls).items())),
        'owners': {
            file: previous.get(file, _default_owner(file))
            for file in files
        },
        # The fingerprint itself contains the file, controller function,
        # category, normalized expression, and duplicate ordinal. Keeping the
        # compact string makes a 600-call legacy inventory reviewable in git.
        'violations': [call.fingerprint for call in calls],
    }
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--write-baseline',
        action='store_true',
        help='replace the reviewed baseline with the current exact inventory',
    )
    args = parser.parse_args()
    if args.write_baseline:
        payload = write_baseline()
        print(f'wrote {len(payload["violations"])} calls to {BASELINE_PATH}')
        return 0
    calls = scan_api_controllers()
    print(json.dumps(dict(sorted(Counter(call.category for call in calls).items())), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
