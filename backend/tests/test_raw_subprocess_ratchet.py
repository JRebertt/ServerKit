"""The raw-subprocess ratchet (plan 75 §G1).

The existing CI audit greps eight hand-listed files for three specific bad
patterns. That catches a regression in a file someone remembered to list; it
says nothing about the other 250 raw calls, and nothing at all about a new
file. This is the other half: a census with a checked-in ceiling that may only
go down.

It is a test rather than a shell step so it runs on a dev box before CI, and
so the counting is AST-based — a grep for `subprocess.run` also matches a
comment, a docstring, and `except subprocess.SubprocessError`.
"""

from raw_subprocess_census import census, count_file, read_ceiling, total


def test_the_count_is_at_or_below_the_ceiling():
    found = census()
    count = total(found)
    ceiling = read_ceiling()
    worst = sorted(found, key=lambda p: -len(found[p]))[:5]
    assert count <= ceiling, (
        f'{count} raw subprocess call sites, ceiling is {ceiling}.\n'
        f'Route new calls through app/utils/system.py (run_checked, '
        f'run_privileged, write_privileged_file) or DockerService.run.\n'
        f'If a raw call is genuinely right, raise '
        f'tests/RAW_SUBPROCESS_CEILING in the same commit and say why.\n'
        f'Heaviest files: ' + ', '.join(f'{p} ({len(found[p])})' for p in worst)
    )


def test_the_ceiling_is_not_stale():
    """A ceiling far above reality stops being a ratchet.

    Left un-updated after a migration it silently re-authorises every call the
    migration removed, so the next regression lands under it unnoticed. Slack
    of 10 is room for one in-flight branch, not for a whole workstream.
    """
    count, ceiling = total(), read_ceiling()
    assert ceiling - count <= 10, (
        f'ceiling {ceiling} is {ceiling - count} above the actual {count}; '
        f'run `python tests/raw_subprocess_census.py --update`'
    )


class TestTheCensusCountsTheRightThings:
    """A miscounting ratchet is worse than none: it reads green either way."""

    def _count(self, tmp_path, source):
        path = tmp_path / 'sample.py'
        path.write_text(source, encoding='utf-8')
        return len(count_file(str(path)))

    def test_counts_every_spawning_entry_point(self, tmp_path):
        assert self._count(tmp_path, (
            'import subprocess\n'
            'subprocess.run(["a"])\n'
            'subprocess.Popen(["b"])\n'
            'subprocess.check_output(["c"])\n'
            'subprocess.call(["d"])\n'
            'subprocess.check_call(["e"])\n'
        )) == 5

    def test_does_not_count_exception_handling(self, tmp_path):
        assert self._count(tmp_path, (
            'import subprocess\n'
            'try:\n'
            '    pass\n'
            'except subprocess.TimeoutExpired:\n'
            '    pass\n'
            'except subprocess.SubprocessError:\n'
            '    pass\n'
        )) == 0

    def test_does_not_count_constants(self, tmp_path):
        assert self._count(tmp_path, (
            'import subprocess\n'
            'kw = {"stdin": subprocess.PIPE, "stderr": subprocess.DEVNULL}\n'
        )) == 0

    def test_does_not_count_a_wrapper_call(self, tmp_path):
        """run_checked(['ufw']) is the migration, not a violation of it."""
        assert self._count(tmp_path, (
            'from app.utils.system import run_checked\n'
            'run_checked(["ufw", "status"])\n'
        )) == 0

    def test_counts_a_call_inside_a_function_body(self, tmp_path):
        assert self._count(tmp_path, (
            'import subprocess\n'
            'def f():\n'
            '    if True:\n'
            '        return subprocess.run(["a"])\n'
        )) == 1

    def test_a_file_that_does_not_parse_is_skipped_not_crashed(self, tmp_path):
        path = tmp_path / 'broken.py'
        path.write_text('def (:\n', encoding='utf-8')
        assert count_file(str(path)) == []


def test_the_doors_are_where_the_raw_calls_are_allowed_to_be():
    """app/utils/system.py and docker_service.py are supposed to hold raw
    calls — they are the doors. This pins that the census sees them, so a
    change that accidentally stopped scanning app/ would not read as a win."""
    found = census()
    assert found.get('app/utils/system.py'), 'census stopped seeing the helpers'


def test_untracked_files_are_not_counted():
    """The census measures what ships, not what this machine has installed.

    A dev box's app/plugins/ also holds installed extension copies that git
    does not track; counting their call sites once gave the ceiling four
    sites of invisible slack on CI's clean checkout (28 here, 24 there).
    """
    import os
    from raw_subprocess_census import APP_DIR, census

    probe = os.path.join(APP_DIR, '_untracked_census_probe.py')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write("import subprocess\nsubprocess.run(['true'])\n")
    try:
        assert 'app/_untracked_census_probe.py' not in census()
    finally:
        os.remove(probe)
