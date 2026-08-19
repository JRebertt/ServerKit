"""serverkit-cron-run — wrap a panel cron command to record its run.

A tracked crontab line invokes this as:

    <python> <backend>/serverkit_cron_run.py <job_id> -- <command...>

It runs the command, passes its stdout/stderr straight through (so cron's own
mail keeps working), captures a tail of the combined output plus timing and the
exit code, reports the run to the local panel's ingest endpoint (localhost +
short-mint break-glass token, mirroring cli_api_client), and re-exits with the
command's own code so cron behaves identically. Reporting is best-effort: a
failure to record must never change the job's outcome.
"""
import os

from app.utils.system import run_checked
import sys
from datetime import datetime, timezone

OUTPUT_TAIL_BYTES = 8 * 1024


def _report(job_id, started, finished, exit_code, output_tail):
    try:
        from app.services.cli_api_client import mint_breakglass_token, ApiClient
        token, _ = mint_breakglass_token()
        ApiClient(token=token).post('/cron/runs/ingest', {
            'job_id': job_id,
            'started_at': started.isoformat(),
            'finished_at': finished.isoformat(),
            'exit_code': exit_code,
            'output_tail': output_tail,
        })
    except Exception as exc:  # noqa: BLE001 - never affect the job's exit
        sys.stderr.write(f'serverkit-cron-run: could not record run: {exc}\n')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--' not in argv:
        sys.stderr.write('usage: serverkit-cron-run <job_id> -- <command...>\n')
        return 2
    sep = argv.index('--')
    job_id = argv[0] if sep >= 1 else ''
    command = argv[sep + 1:]
    if not job_id or not command:
        sys.stderr.write('usage: serverkit-cron-run <job_id> -- <command...>\n')
        return 2

    started = datetime.now(timezone.utc)
    stdout, stderr, exit_code = '', '', 127
    try:
        proc = run_checked(command, timeout=None)
        stdout, stderr = proc['output'], proc['stderr']
        # 127 (the shell's "command not found") stays the sentinel for a job
        # that never ran, so a launch failure is not recorded as exit 0.
        exit_code = proc['returncode'] if proc['returncode'] is not None else 127
        if proc['returncode'] is None:
            stderr = stderr or f"serverkit-cron-run: {proc['error']}\n"
    except Exception as exc:  # noqa: BLE001 - record the failure to launch
        stderr = f'serverkit-cron-run: failed to execute: {exc}\n'
    finished = datetime.now(timezone.utc)

    # Pass output through so cron's MAILTO behavior is unchanged.
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)

    tail = (stdout + stderr)[-OUTPUT_TAIL_BYTES:]
    _report(job_id, started, finished, exit_code, tail)
    return exit_code


if __name__ == '__main__':  # pragma: no cover - exercised via serverkit_cron_run.py
    sys.exit(main())
