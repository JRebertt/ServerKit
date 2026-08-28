"""The hand-rolled-subprocess-stub ratchet (plan 82 §G1).

tests/subprocess_stub.py's own docstring notes that every hand-rolled
subprocess stub is an exec the runtime sbin guard never sees, and an
unscripted command a blanket except can turn into a fabricated success.
Adoption of the shared kit stalled about half-way, and unlike every other
convergence in this repo there was no census holding the line — this is it.
"""

from hand_rolled_subprocess_stub_census import (
    census, count_file, read_ceiling, total)


def test_the_count_is_at_or_below_the_ceiling():
    found = census()
    count = total(found)
    ceiling = read_ceiling()
    assert count <= ceiling, (
        f'{count} hand-rolled subprocess stubs in tests, ceiling is {ceiling}.\n'
        f'Use the shared fake_subprocess fixture (tests/subprocess_stub.py) '
        f'instead — it hard-fails unscripted commands and keeps the sbin-PATH '
        f'guard in force.\n'
        f'Files: ' + ', '.join(f'{p} ({len(found[p])})' for p in sorted(found))
    )


def test_the_ceiling_is_not_stale():
    """Slack of 5 is room for an in-flight branch, not a workstream."""
    count, ceiling = total(), read_ceiling()
    assert ceiling - count <= 5, (
        f'ceiling {ceiling} is {ceiling - count} above the actual {count}; '
        f'run `python tests/hand_rolled_subprocess_stub_census.py --update`'
    )


class TestTheCensusCountsTheRightThings:
    """A miscounting ratchet reads green either way."""

    def _count(self, tmp_path, source):
        path = tmp_path / 'sample.py'
        path.write_text(source, encoding='utf-8')
        return len(count_file(str(path)))

    def test_counts_monkeypatch_on_the_module_object(self, tmp_path):
        assert self._count(tmp_path, (
            'import subprocess\n'
            'def test_x(monkeypatch):\n'
            '    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)\n'
        )) == 1

    def test_counts_string_target_forms(self, tmp_path):
        assert self._count(tmp_path, (
            'from unittest.mock import patch\n'
            'def test_x(monkeypatch):\n'
            '    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)\n'
            '    with patch("subprocess.check_output"):\n'
            '        pass\n'
        )) == 2

    def test_counts_patch_object_on_subprocess(self, tmp_path):
        assert self._count(tmp_path, (
            'import subprocess\n'
            'from unittest.mock import patch\n'
            'def test_x():\n'
            '    with patch.object(subprocess, "run"):\n'
            '        pass\n'
        )) == 1

    def test_does_not_count_patching_a_service_door(self, tmp_path):
        """Stubbing run_privileged/run_checked at a module seam is the
        blessed pattern, not a violation."""
        assert self._count(tmp_path, (
            'from unittest.mock import patch\n'
            'from app.services import postfix_service as mod\n'
            'def test_x(monkeypatch):\n'
            '    monkeypatch.setattr(mod, "run_privileged", lambda *a, **k: None)\n'
            '    with patch.object(mod, "write_privileged_file"):\n'
            '        pass\n'
        )) == 0

    def test_does_not_count_the_shared_fixture(self, tmp_path):
        assert self._count(tmp_path, (
            'def test_x(fake_subprocess):\n'
            '    fake_subprocess.script(["ufw"], stdout="ok")\n'
        )) == 0


def test_the_kit_itself_is_exempt_not_invisible():
    """subprocess_stub.py must patch subprocess to exist; it is exempted by
    path, not by the counter failing to see such patterns."""
    found = census()
    assert 'tests/subprocess_stub.py' not in found
    assert 'tests/conftest.py' not in found
