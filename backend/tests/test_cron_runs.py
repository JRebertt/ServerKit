"""Cron run tracking: the shim, ingest endpoint, and edge-triggered alerts.

Plan 21 Phase 4 (#13–#17). The crontab-rewrite half is Linux-only; these cover
the OS-agnostic parts — shim exit-code/output round-trip, run recording +
status-transition logic, ingest auth, and the failure/recovery notification.
"""
import sys

import pytest

from app.services.cron_service import CronService
from app.services.cron_run_service import CronRunService
from app.models.cron_run import OUTPUT_TAIL_LIMIT


@pytest.fixture
def cron_store(tmp_path, monkeypatch):
    import app.services.cron_service as mod
    monkeypatch.setattr(mod, 'JOBS_FILE', str(tmp_path / 'cron_jobs.json'))
    monkeypatch.setattr(CronService, 'is_linux', classmethod(lambda cls: False))
    return mod


# --------------------------------------------------------------------------- #
# The shim (app/cron_runner.py)
# --------------------------------------------------------------------------- #

def test_shim_passes_through_exit_code(monkeypatch):
    import app.cron_runner as runner
    captured = {}
    monkeypatch.setattr(runner, '_report',
                        lambda *a, **k: captured.update(args=a))
    code = runner.main(['job_1', '--', sys.executable, '-c', 'import sys; sys.exit(3)'])
    assert code == 3
    # _report(job_id, started, finished, exit_code, tail)
    assert captured['args'][0] == 'job_1'
    assert captured['args'][3] == 3


def test_shim_captures_output_tail(monkeypatch, capsys):
    import app.cron_runner as runner
    captured = {}
    monkeypatch.setattr(runner, '_report',
                        lambda *a, **k: captured.update(tail=a[4]))
    code = runner.main(['j', '--', sys.executable, '-c', 'print("hello-from-job")'])
    assert code == 0
    assert 'hello-from-job' in captured['tail']
    # Output is passed through to real stdout too (cron MAILTO stays intact).
    assert 'hello-from-job' in capsys.readouterr().out


def test_shim_usage_error_without_separator(monkeypatch):
    import app.cron_runner as runner
    assert runner.main(['job_1', 'echo', 'hi']) == 2


# --------------------------------------------------------------------------- #
# record_run + status-transition logic
# --------------------------------------------------------------------------- #

def test_record_run_first_failure_is_a_transition(app):
    _, transition = CronRunService.record_run('jobA', exit_code=1)
    assert transition == 'failure'


def test_record_run_repeat_failure_not_a_transition(app):
    CronRunService.record_run('jobB', exit_code=1)
    _, transition = CronRunService.record_run('jobB', exit_code=1)
    assert transition is None


def test_record_run_recovery_transition(app):
    CronRunService.record_run('jobC', exit_code=1)
    _, transition = CronRunService.record_run('jobC', exit_code=0)
    assert transition == 'recovery'


def test_record_run_first_success_no_transition(app):
    _, transition = CronRunService.record_run('jobD', exit_code=0)
    assert transition is None


def test_record_run_caps_output_tail(app):
    big = 'x' * (OUTPUT_TAIL_LIMIT + 5000)
    run, _ = CronRunService.record_run('jobE', exit_code=0, output_tail=big)
    assert len(run.output_tail) == OUTPUT_TAIL_LIMIT


def test_stats_success_rate(app):
    for code in (0, 0, 1, 0):
        CronRunService.record_run('jobF', exit_code=code)
    stats = CronRunService.stats('jobF')
    assert stats['total'] == 4
    assert stats['success'] == 3
    assert stats['success_rate'] == 0.75
    assert stats['last_status'] == 'success'


# --------------------------------------------------------------------------- #
# ingest endpoint (localhost + admin token)
# --------------------------------------------------------------------------- #

def test_ingest_records_run(client, auth_headers):
    resp = client.post('/api/v1/cron/runs/ingest', headers=auth_headers, json={
        'job_id': 'job_ingest', 'exit_code': 0, 'output_tail': 'ok',
    })
    assert resp.status_code == 201
    assert resp.get_json()['status'] == 'success'


def test_ingest_rejects_non_localhost(client, auth_headers):
    resp = client.post('/api/v1/cron/runs/ingest', headers=auth_headers,
                       environ_base={'REMOTE_ADDR': '10.1.2.3'},
                       json={'job_id': 'x', 'exit_code': 0})
    assert resp.status_code == 403


def test_ingest_requires_job_id(client, auth_headers):
    resp = client.post('/api/v1/cron/runs/ingest', headers=auth_headers,
                       json={'exit_code': 0})
    assert resp.status_code == 400


def test_ingest_requires_auth(client):
    resp = client.post('/api/v1/cron/runs/ingest', json={'job_id': 'x', 'exit_code': 0})
    assert resp.status_code in (401, 403, 422)


# --------------------------------------------------------------------------- #
# edge-triggered notification via ingest
# --------------------------------------------------------------------------- #

def test_ingest_notifies_on_failure_transition(client, auth_headers, cron_store, monkeypatch):
    sent = []
    from app.plugins_sdk import notify
    monkeypatch.setattr(notify, 'send',
                        lambda event, **kw: sent.append((event, kw.get('data'))))

    jid = CronService.add_job('0 0 * * *', '/bin/false', name='Failing Job')['job_id']

    # First failure -> one alert.
    client.post('/api/v1/cron/runs/ingest', headers=auth_headers,
                json={'job_id': jid, 'exit_code': 1})
    # Second failure -> NO new alert (edge-triggered, not per-occurrence).
    client.post('/api/v1/cron/runs/ingest', headers=auth_headers,
                json={'job_id': jid, 'exit_code': 1})

    failed = [s for s in sent if s[0] == 'cron.job_failed']
    assert len(failed) == 1
    assert failed[0][1]['name'] == 'Failing Job'

    # Recovery -> one recovery alert.
    client.post('/api/v1/cron/runs/ingest', headers=auth_headers,
                json={'job_id': jid, 'exit_code': 0})
    assert any(s[0] == 'cron.job_recovered' for s in sent)


def test_ingest_respects_alert_opt_out(client, auth_headers, cron_store, monkeypatch):
    sent = []
    from app.plugins_sdk import notify
    monkeypatch.setattr(notify, 'send', lambda event, **kw: sent.append(event))

    jid = CronService.add_job('0 0 * * *', '/bin/false', name='Quiet Job')['job_id']
    meta = CronService._load_jobs_metadata()
    meta['jobs'][jid]['alert_on_failure'] = False
    CronService._save_jobs_metadata(meta)

    client.post('/api/v1/cron/runs/ingest', headers=auth_headers,
                json={'job_id': jid, 'exit_code': 1})
    assert 'cron.job_failed' not in sent


# --------------------------------------------------------------------------- #
# tracking toggle + wrapper construction
# --------------------------------------------------------------------------- #

def test_wrapper_command_shape():
    wrapped = CronService._crontab_command('/usr/bin/task.sh', True, 'job_9')
    assert 'serverkit_cron_run.py' in wrapped
    assert 'job_9 -- /usr/bin/task.sh' in wrapped
    # Untracked is byte-identical to the bare command.
    assert CronService._crontab_command('/usr/bin/task.sh', False, 'job_9') == '/usr/bin/task.sh'


def test_set_tracking_updates_metadata(cron_store):
    jid = CronService.add_job('0 0 * * *', '/usr/bin/task.sh', name='T')['job_id']
    assert CronService.set_tracking(jid, True)['tracked'] is True
    assert CronService.get_job(jid)['tracked'] is True
    assert CronService.set_tracking(jid, False)['tracked'] is False
    assert CronService.get_job(jid)['tracked'] is False


# --------------------------------------------------------------------------- #
# "Run now" records a CronRun too (#18)
# --------------------------------------------------------------------------- #

def test_run_now_records_history(app, cron_store, monkeypatch):
    import subprocess

    jid = CronService.add_job('0 0 * * *', '/bin/true', name='M')['job_id']

    class _Result:
        returncode = 0
        stdout = 'done'
        stderr = ''

    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _Result())
    res = CronService.run_job_now(jid)
    assert res['success']

    runs = CronRunService.recent_runs(jid)
    assert len(runs) == 1
    assert runs[0]['status'] == 'success'


# --------------------------------------------------------------------------- #
# list_jobs() enrichment — the admin /cron table renders Last run / Next run /
# Status straight off these keys, so the list has to carry the same joins
# jobs_for_application() does. Before this, only the for-app surface had them.
# --------------------------------------------------------------------------- #

def test_list_jobs_carries_schedule_and_next_run(app, cron_store):
    CronService.add_job('0 0 * * *', '/usr/bin/task.sh', name='Nightly')

    job = CronService.list_jobs()['jobs'][0]

    assert job['schedule_human']
    assert job['next_run']            # croniter resolves a concrete next fire
    assert job['tracked'] is False


def test_list_jobs_carries_last_run_join(app, cron_store, monkeypatch):
    import subprocess

    jid = CronService.add_job('0 0 * * *', '/bin/false', name='Flaky')['job_id']

    class _Result:
        returncode = 1
        stdout = ''
        stderr = 'boom'

    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _Result())
    CronService.run_job_now(jid)

    job = next(j for j in CronService.list_jobs()['jobs'] if str(j['id']) == str(jid))

    assert job['last_status'] == 'failure'
    assert job['last_run']
    assert job['success_rate'] == 0.0


def test_list_jobs_without_history_has_null_run_fields(app, cron_store):
    CronService.add_job('*/5 * * * *', '/usr/bin/task.sh', name='Fresh')

    job = CronService.list_jobs()['jobs'][0]

    assert job['last_run'] is None
    assert job['last_status'] is None
