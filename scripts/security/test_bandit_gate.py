"""The security gate must reject new findings even in an excepted function."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    'bandit_gate', Path(__file__).resolve().parents[1] / 'check-bandit-report.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class BanditGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.file = self.root / 'example.py'
        self.file.write_text('def legacy():\n    return unsafe()\n')
        function, sha = gate.function_fingerprint(self.root, 'example.py', 2)
        self.exceptions = [{
            'path': 'example.py', 'test_id': 'B321', 'function': function,
            'sha256': sha, 'count': 1, 'reason': 'Synthetic reviewed fixture',
        }]
        self.issue = {
            'filename': './example.py', 'test_id': 'B321', 'line_number': 2,
            'issue_severity': 'HIGH', 'issue_confidence': 'HIGH',
            'issue_text': 'synthetic finding',
        }

    def check(self, results=None, errors=None):
        return gate.check_report(
            {'results': [self.issue] if results is None else results, 'errors': errors or []},
            self.exceptions, self.root, {'example.py'})

    def test_exact_accepted_finding_passes(self):
        self.assertEqual(self.check(), [])

    def test_duplicate_finding_in_accepted_function_fails(self):
        self.assertTrue(self.check([self.issue, copy.deepcopy(self.issue)]))

    def test_changed_function_requires_review(self):
        self.file.write_text('def legacy():\n    return unsafe(other_secret)\n')
        self.assertTrue(self.check())

    def test_new_finding_in_same_file_is_not_accepted(self):
        self.file.write_text(self.file.read_text() + '\ndef additional():\n    return unsafe()\n')
        issue = dict(self.issue, line_number=5)
        self.assertTrue(self.check([self.issue, issue]))

    def test_unused_exception_must_be_removed(self):
        self.assertTrue(self.check([]))

    def test_scanner_errors_fail_closed(self):
        self.assertTrue(self.check(errors=[{'filename': './example.py', 'reason': 'syntax error'}]))

    def test_runtime_plugin_copies_are_not_baselined(self):
        copied = dict(self.issue, filename='backend/app/plugins/local-copy.py')
        self.assertEqual(self.check([self.issue, copied]), [])


if __name__ == '__main__':
    unittest.main()
