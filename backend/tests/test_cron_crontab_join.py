"""Crontab ↔ metadata join (#117).

Creating a named cron job on Linux wrote the display name into the marker
comment and re-listed jobs under synthetic `cron_<index>` ids, so the metadata
(name, description) never joined back and every mutation route answered "Job
not found". These tests drive the full Linux path against an in-memory
crontab: create → list → edit → run-id stability → delete, plus the rescue
path for jobs created before the marker carried the id.
"""
import pytest

from app.services.cron_service import CronService, SHIM_PATH


@pytest.fixture
def linux_cron(tmp_path, monkeypatch):
    """CronService wired to a fake Linux host: in-memory crontab, tmp metadata."""
    import app.services.cron_service as mod
    monkeypatch.setattr(mod, 'JOBS_FILE', str(tmp_path / 'cron_jobs.json'))
    monkeypatch.setattr(CronService, 'is_linux', classmethod(lambda cls: True))

    store = {'crontab': ''}
    monkeypatch.setattr(CronService, '_read_crontab',
                        classmethod(lambda cls: store['crontab']))

    def _install(cls, content):
        store['crontab'] = content
        return None

    monkeypatch.setattr(CronService, '_install_crontab',
                        classmethod(_install))
    return store


CMD = '/usr/local/bin/backup.sh --full'
SCHEDULE = '0 3 * * *'


def _add(name='Nightly Backup'):
    result = CronService.add_job(SCHEDULE, CMD, name=name)
    assert result['success']
    return result['job_id']


def test_marker_comment_carries_job_id(linux_cron):
    job_id = _add()
    assert f"# ServerKit Job: {job_id} (Nightly Backup)" in linux_cron['crontab']
    assert f"{SCHEDULE} {CMD}" in linux_cron['crontab']


def test_marker_name_cannot_inject_crontab_lines(linux_cron):
    _add(name='evil\n* * * * * /bin/rm -rf /')
    comment_lines = [l for l in linux_cron['crontab'].split('\n')
                     if l.startswith('# ServerKit Job:')]
    assert len(comment_lines) == 1
    assert '\n* * * * *' not in comment_lines[0]
    assert '/bin/rm' not in linux_cron['crontab'].replace(comment_lines[0], '')


def test_list_joins_name_via_marker_id(linux_cron):
    """The #117 repro: a freshly created named job must list under its real id
    with its name, not as an unnamed cron_<index> row."""
    job_id = _add()
    jobs = CronService.list_jobs()['jobs']
    assert len(jobs) == 1
    assert jobs[0]['id'] == job_id
    assert jobs[0]['name'] == 'Nightly Backup'
    assert jobs[0]['source'] == 'serverkit'


def test_listed_id_reaches_update_and_delete(linux_cron):
    _add()
    listed_id = CronService.list_jobs()['jobs'][0]['id']

    assert CronService.update_job(listed_id, name='Renamed')['success']
    assert CronService.get_job(listed_id)['name'] == 'Renamed'

    assert CronService.remove_job(listed_id)['success']
    assert CMD not in linux_cron['crontab']
    assert '# ServerKit Job:' not in linux_cron['crontab']
    assert CronService.list_jobs()['jobs'] == []


def test_legacy_named_marker_rescued_by_schedule_command_match(linux_cron):
    """Jobs written before the fix carry the NAME in the marker comment; the
    schedule+command fallback must still join them to their metadata."""
    job_id = _add()
    # Rewrite the crontab the way the pre-fix code did.
    linux_cron['crontab'] = (f"# ServerKit Job: Nightly Backup\n"
                             f"{SCHEDULE} {CMD}\n")

    jobs = CronService.list_jobs()['jobs']
    assert len(jobs) == 1
    assert jobs[0]['id'] == job_id
    assert jobs[0]['name'] == 'Nightly Backup'


def test_legacy_remove_drops_orphan_marker_comment(linux_cron):
    job_id = _add()
    linux_cron['crontab'] = (f"# ServerKit Job: Nightly Backup\n"
                             f"{SCHEDULE} {CMD}\n")

    assert CronService.remove_job(job_id)['success']
    assert CMD not in linux_cron['crontab']
    assert '# ServerKit Job:' not in linux_cron['crontab']


def test_disabled_job_stays_listed(linux_cron):
    """toggle_job comments the line out; the job must not vanish from the
    admin list (it comes back from metadata, disabled)."""
    job_id = _add()
    assert CronService.toggle_job(job_id, False)['success']
    assert f"# {SCHEDULE} {CMD}" in linux_cron['crontab']

    jobs = CronService.list_jobs()['jobs']
    assert len(jobs) == 1
    assert jobs[0]['id'] == job_id
    assert jobs[0]['enabled'] is False

    assert CronService.toggle_job(job_id, True)['success']
    lines = linux_cron['crontab'].split('\n')
    assert f"{SCHEDULE} {CMD}" in lines


def test_tracked_shim_line_matches_toggle_and_remove(linux_cron):
    job_id = _add()
    assert CronService.set_tracking(job_id, True)['success']
    assert f"{SHIM_PATH} {job_id} -- {CMD}" in linux_cron['crontab']

    # The wrapped line still joins back to its metadata id on list.
    jobs = CronService.list_jobs()['jobs']
    assert len(jobs) == 1
    assert jobs[0]['id'] == job_id
    assert jobs[0]['command'] == CMD  # metadata's bare command, not the shim

    assert CronService.toggle_job(job_id, False)['success']
    active = [l for l in linux_cron['crontab'].split('\n')
              if l.strip() and not l.strip().startswith('#')]
    assert active == []

    assert CronService.remove_job(job_id)['success']
    assert CMD not in linux_cron['crontab']


def test_toggle_matches_exact_command_not_command_prefix(linux_cron):
    job_id = _add()
    extended_command = f'{CMD} --different-job'
    linux_cron['crontab'] += f'{SCHEDULE} {extended_command}\n'

    assert CronService.toggle_job(job_id, False)['success']

    lines = linux_cron['crontab'].splitlines()
    assert f'# {SCHEDULE} {CMD}' in lines
    assert f'{SCHEDULE} {extended_command}' in lines


def test_tracked_toggle_matches_exact_wrapped_command(linux_cron):
    job_id = _add()
    assert CronService.set_tracking(job_id, True)['success']
    wrapped = CronService._crontab_command(CMD, True, job_id)
    extended_command = f'{wrapped} --different-job'
    linux_cron['crontab'] += f'{SCHEDULE} {extended_command}\n'

    assert CronService.toggle_job(job_id, False)['success']

    lines = linux_cron['crontab'].splitlines()
    assert f'# {SCHEDULE} {wrapped}' in lines
    assert f'{SCHEDULE} {extended_command}' in lines


def test_foreign_crontab_lines_left_untouched(linux_cron):
    linux_cron['crontab'] = "MAILTO=root\n15 2 * * * /opt/other/task.sh\n"
    job_id = _add()

    jobs = CronService.list_jobs()['jobs']
    by_id = {j['id']: j for j in jobs}
    assert job_id in by_id
    foreign = [j for j in jobs if j['id'] != job_id]
    assert len(foreign) == 1
    assert foreign[0]['command'] == '/opt/other/task.sh'

    assert CronService.remove_job(job_id)['success']
    assert '15 2 * * * /opt/other/task.sh' in linux_cron['crontab']
    assert 'MAILTO=root' in linux_cron['crontab']
