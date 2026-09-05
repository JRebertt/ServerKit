"""Gate HIGH/HIGH Bandit findings with explicit, function-scoped exceptions.

Run from the repository root after producing a Bandit JSON report. Only
git-tracked sources are evaluated, excluding locally installed plugin copies.
An exception binds to a path, rule, function AST and occurrence count: adding
another unsafe call or changing its guard requires reviewing the exception.
"""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def normalized_path(filename):
    return filename.replace('\\', '/').removeprefix('./')


def function_fingerprint(root, filename, line):
    tree = ast.parse((root / filename).read_text(encoding='utf-8-sig'))
    matches = []

    def visit(node, scope=''):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = f'{scope}.{node.name}'.lstrip('.')
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= line <= node.end_lineno:
                    matches.append((node.end_lineno - node.lineno, scope, node))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree)
    if not matches:
        return '<module>', hashlib.sha256(ast.dump(tree).encode()).hexdigest()
    _, scope, node = min(matches, key=lambda match: match[0])
    return scope, hashlib.sha256(ast.dump(node).encode()).hexdigest()


def check_report(report, exceptions, root, tracked):
    failures, accepted = [], Counter()
    expected = {}
    for entry in exceptions:
        key = (entry['path'], entry['test_id'], entry['function'], entry['sha256'])
        if key in expected or not entry.get('reason') or entry.get('count') != 1:
            raise ValueError('Each exception must be unique, documented and accept exactly one finding')
        expected[key] = entry['count']

    for error in report.get('errors', []):
        if normalized_path(error['filename']) in tracked:
            failures.append(f"Scan error: {error['filename']}: {error['reason']}")

    for issue in report['results']:
        filename = normalized_path(issue['filename'])
        if filename not in tracked:
            continue
        if (issue['issue_severity'], issue['issue_confidence']) != ('HIGH', 'HIGH'):
            continue
        function, fingerprint = function_fingerprint(root, filename, issue['line_number'])
        key = (filename, issue['test_id'], function, fingerprint)
        accepted[key] += 1
        if accepted[key] > expected.get(key, 0):
            failures.append(f"{filename}:{issue['line_number']} {issue['test_id']}: {issue['issue_text']}")

    for key, count in expected.items():
        if accepted[key] < count:
            failures.append(f'Stale or changed exception: {key[0]} {key[1]} {key[2]}; review or remove it')
    return failures


def main():
    root = Path(__file__).resolve().parents[1]
    report = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    exceptions = json.loads((root / 'scripts/security/bandit-exceptions.json').read_text())['exceptions']
    tracked = set(subprocess.check_output(
        ['git', 'ls-files', '-z'], cwd=root, text=True).split('\0'))
    failures = check_report(report, exceptions, root, tracked)
    for failure in failures:
        print(failure)
    if failures:
        print(f'Bandit gate failed: {len(failures)} issue(s).')
        return 1
    print(f'Bandit HIGH/HIGH gate passed; {len(exceptions)} explicit findings accepted.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
