"""Cron round trip against the REAL crontab binary (plan 82 §E).

test_cron_crontab_join.py proves the #117 join against an in-memory crontab
store; this file is the same cycle with the stubs removed — the panel's
generated crontab text goes through `crontab -` and comes back through
`crontab -l`, so a syntax the real parser rejects, or a normalization it
applies that breaks the marker join, fails HERE instead of on a user's box.

State safety: mutates the invoking user's crontab, with the pre-test crontab
captured and restored by the fixture — which is why these tests need the
explicit SERVERKIT_REAL_BINARIES=1 opt-in on top of the marker. Run with:

    SERVERKIT_REAL_BINARIES=1 pytest tests -m real_binaries
"""
import os
import platform
import shutil
import subprocess

import pytest

from app.services.cron_service import CronService


pytestmark = [
    pytest.mark.real_binaries,
    pytest.mark.skipif(platform.system() != 'Linux',
                       reason='real crontab needs Linux'),
    pytest.mark.skipif(shutil.which('crontab') is None,
                       reason='crontab binary not installed'),
    pytest.mark.skipif(os.environ.get('SERVERKIT_REAL_BINARIES') != '1',
                       reason='mutates the real user crontab; opt in with '
                              'SERVERKIT_REAL_BINARIES=1'),
]


@pytest.fixture
def real_crontab(tmp_path, monkeypatch):
    """Metadata redirected to tmp; the crontab is REAL, saved and restored."""
    import app.services.cron_service as mod
    monkeypatch.setattr(mod, 'JOBS_FILE', str(tmp_path / 'cron_jobs.json'))

    saved = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    original = saved.stdout if saved.returncode == 0 else None
    yield
    if original is None:
        subprocess.run(['crontab', '-r'], capture_output=True)
    else:
        subprocess.run(['crontab', '-'], input=original,
                       capture_output=True, text=True)


CMD = '/usr/local/bin/real-backup.sh --full'


def _job_named(name):
    jobs = CronService.list_jobs()['jobs']
    matches = [j for j in jobs if j.get('name') == name]
    assert matches, f'{name!r} not in {[j.get("name") for j in jobs]}'
    return matches[0]


def test_add_list_toggle_remove_against_real_crontab(real_crontab):
    added = CronService.add_job('*/5 * * * *', CMD, name='Real Backup')
    assert added['success'], added

    # The real crontab now holds the marker + line the panel wrote.
    live = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    assert '# ServerKit Job:' in live.stdout
    assert CMD in live.stdout

    # list joins the re-parsed line back to its metadata (#117's cycle).
    job = _job_named('Real Backup')
    job_id = job['id']
    assert not job_id.startswith('cron_'), 'synthetic id — metadata join lost'

    # Mutations must find the job by that id, through the real binary.
    toggled = CronService.toggle_job(job_id, enabled=False)
    assert toggled['success'], toggled
    assert _job_named('Real Backup').get('enabled') is False

    toggled = CronService.toggle_job(job_id, enabled=True)
    assert toggled['success'], toggled
    live = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    active = [l for l in live.stdout.splitlines()
              if CMD in l and not l.lstrip().startswith('#')]
    assert active, 're-enabled job line is not active in the real crontab'

    removed = CronService.remove_job(job_id)
    assert removed['success'], removed
    live = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    assert CMD not in (live.stdout or '')
    assert all(j.get('name') != 'Real Backup'
               for j in CronService.list_jobs()['jobs'])


def test_panel_jobs_coexist_with_operator_lines(real_crontab):
    # An operator-authored line the panel must list but never destroy.
    operator_line = '17 3 * * * /opt/operator/rotate-logs.sh'
    subprocess.run(['crontab', '-'], input=operator_line + '\n',
                   capture_output=True, text=True)

    added = CronService.add_job('0 * * * *', CMD, name='Hourly')
    assert added['success'], added
    removed = CronService.remove_job(_job_named('Hourly')['id'])
    assert removed['success'], removed

    live = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    assert operator_line in live.stdout
    assert CMD not in live.stdout


def test_name_with_whitespace_cannot_break_the_real_crontab(real_crontab):
    added = CronService.add_job('*/10 * * * *', CMD,
                                name='evil\n* * * * * /tmp/injected.sh')
    assert added['success'], added

    live = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    assert '/tmp/injected.sh' not in [
        l.split(None, 5)[-1] if len(l.split(None, 5)) == 6 else ''
        for l in live.stdout.splitlines()
        if l.strip() and not l.strip().startswith('#')
    ], 'newline in a job name injected a live crontab line'
