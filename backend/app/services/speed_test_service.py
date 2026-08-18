"""On-demand server speed test (download / upload / latency).

Best-effort, tiered measurement:
  1. If an Ookla ``speedtest`` or python ``speedtest-cli`` binary is available,
     shell out to it and parse its JSON output.
  2. Otherwise a pure-Python fallback: latency via timed TCP connects to a
     well-known anycast host, download via a timed GET of ~10 MB from a public
     speed endpoint, upload via a timed POST of ~2 MB of random bytes
     (upload is best-effort — if it fails the result still carries
     download + latency with ``upload_mbps=None``).

Runs asynchronously as a unified Job (kind ``monitoring.speedtest.run``); the
handler persists the last result under the ``speedtest_last_result`` setting so
the Monitoring page can show it without re-running the test.
"""
import json
import logging
import os
import socket
import subprocess

from app.utils.system import run_checked
import time
from datetime import datetime

import requests

from app.utils.system import is_command_available

logger = logging.getLogger(__name__)

SPEEDTEST_JOB_KIND = 'monitoring.speedtest.run'
LAST_RESULT_KEY = 'speedtest_last_result'

# Fallback-tier tunables.
LATENCY_HOST = '1.1.1.1'
LATENCY_PORT = 443
LATENCY_SAMPLES = 3
LATENCY_TIMEOUT = 5  # seconds per connect
DOWNLOAD_URL = 'https://speed.cloudflare.com/__down?bytes=10000000'
DOWNLOAD_BYTES = 10_000_000
UPLOAD_URL = 'https://speed.cloudflare.com/__up'
UPLOAD_BYTES = 2_000_000
HTTP_TIMEOUT = (10, 60)  # (connect, read) seconds
CLI_TIMEOUT = 120  # seconds for the speedtest binary


class SpeedTestService:

    # ------------------------------------------------------------------ #
    # Public entry points
    # ------------------------------------------------------------------ #

    @classmethod
    def run_test(cls):
        """Run a speed test and return a normalized result dict.

        Never raises — any failure returns ``{'success': False, 'error': ...}``.
        """
        try:
            cli_result = cls._run_cli_test()
            if cli_result is not None:
                return cli_result
            return cls._run_fallback_test()
        except Exception as exc:  # noqa: BLE001 — hard guarantee, see docstring
            logger.exception('Speed test failed unexpectedly')
            return {
                'success': False,
                'error': str(exc),
                'tested_at': datetime.utcnow().isoformat() + 'Z',
            }

    @classmethod
    def get_status(cls):
        """Last stored result + whether a speed test job is currently in flight."""
        from app.jobs.models import Job

        last_result = None
        try:
            from app.services.settings_service import SettingsService
            raw = SettingsService.get(LAST_RESULT_KEY)
            if raw:
                last_result = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # pragma: no cover — corrupt setting should not 500
            logger.warning('Could not parse stored speed test result', exc_info=True)

        active = Job.query.filter(
            Job.kind == SPEEDTEST_JOB_KIND,
            Job.status.in_((Job.STATUS_PENDING, Job.STATUS_RUNNING)),
        ).order_by(Job.created_at.desc()).first()

        return {
            'last_result': last_result,
            'running': active is not None,
            'job': active.to_dict() if active else None,
        }

    @classmethod
    def is_running(cls):
        from app.jobs.models import Job
        return Job.query.filter(
            Job.kind == SPEEDTEST_JOB_KIND,
            Job.status.in_((Job.STATUS_PENDING, Job.STATUS_RUNNING)),
        ).first() is not None

    # ------------------------------------------------------------------ #
    # Tier 1 — speedtest CLI
    # ------------------------------------------------------------------ #

    @classmethod
    def _run_cli_test(cls):
        """Run the system speedtest binary if present; None if unavailable."""
        if is_command_available('speedtest'):
            cmd = ['speedtest', '--format=json', '--accept-license', '--accept-gdpr']
            flavor = 'ookla'
        elif is_command_available('speedtest-cli'):
            cmd = ['speedtest-cli', '--json']
            flavor = 'python'
        else:
            return None

        try:
            proc = run_checked(cmd, timeout=CLI_TIMEOUT)
            if not proc['success']:
                logger.warning('speedtest CLI failed (%s): %s',
                               proc['returncode'], proc['error'][:500])
                return None  # fall through to the pure-Python tier
            data = json.loads(proc['output'])
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
            logger.warning('speedtest CLI failed (%s); using fallback', exc)
            return None

        if flavor == 'ookla':
            # Ookla reports bandwidth in bytes/second.
            download = (data.get('download') or {}).get('bandwidth')
            upload = (data.get('upload') or {}).get('bandwidth')
            latency = (data.get('ping') or {}).get('latency')
            download_mbps = round(download * 8 / 1e6, 2) if download else None
            upload_mbps = round(upload * 8 / 1e6, 2) if upload else None
        else:
            # speedtest-cli reports bits/second.
            download = data.get('download')
            upload = data.get('upload')
            latency = data.get('ping')
            download_mbps = round(download / 1e6, 2) if download else None
            upload_mbps = round(upload / 1e6, 2) if upload else None

        if download_mbps is None and latency is None:
            return None  # useless output — try the fallback tier

        return {
            'success': True,
            'method': 'cli',
            'download_mbps': download_mbps,
            'upload_mbps': upload_mbps,
            'latency_ms': round(latency, 2) if latency is not None else None,
            'tested_at': datetime.utcnow().isoformat() + 'Z',
        }

    # ------------------------------------------------------------------ #
    # Tier 2 — pure-Python fallback
    # ------------------------------------------------------------------ #

    @classmethod
    def _measure_latency(cls):
        """Median-ish latency: best of N timed TCP connects, in ms."""
        samples = []
        for _ in range(LATENCY_SAMPLES):
            try:
                start = time.perf_counter()
                sock = socket.create_connection(
                    (LATENCY_HOST, LATENCY_PORT), timeout=LATENCY_TIMEOUT
                )
                samples.append((time.perf_counter() - start) * 1000.0)
                sock.close()
            except OSError:
                continue
        if not samples:
            return None
        return round(min(samples), 2)

    @classmethod
    def _measure_download(cls):
        """Timed GET of ~10 MB; returns Mbps or None."""
        try:
            start = time.perf_counter()
            resp = requests.get(DOWNLOAD_URL, timeout=HTTP_TIMEOUT, stream=True)
            resp.raise_for_status()
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
            elapsed = time.perf_counter() - start
            if total <= 0 or elapsed <= 0:
                return None
            return round(total * 8 / elapsed / 1e6, 2)
        except requests.RequestException:
            logger.warning('Fallback download measurement failed', exc_info=True)
            return None

    @classmethod
    def _measure_upload(cls):
        """Timed POST of ~2 MB random bytes; best-effort, returns Mbps or None."""
        try:
            payload = os.urandom(UPLOAD_BYTES)
            start = time.perf_counter()
            resp = requests.post(UPLOAD_URL, data=payload, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            elapsed = time.perf_counter() - start
            if elapsed <= 0:
                return None
            return round(len(payload) * 8 / elapsed / 1e6, 2)
        except requests.RequestException:
            logger.info('Fallback upload measurement failed (best-effort)')
            return None

    @classmethod
    def _run_fallback_test(cls):
        latency_ms = cls._measure_latency()
        download_mbps = cls._measure_download()
        upload_mbps = cls._measure_upload()

        if download_mbps is None and latency_ms is None:
            return {
                'success': False,
                'error': 'Speed test failed: could not reach any measurement endpoint.',
                'tested_at': datetime.utcnow().isoformat() + 'Z',
            }

        return {
            'success': True,
            'method': 'fallback',
            'download_mbps': download_mbps,
            'upload_mbps': upload_mbps,
            'latency_ms': latency_ms,
            'tested_at': datetime.utcnow().isoformat() + 'Z',
        }

    # ------------------------------------------------------------------ #
    # Job plumbing
    # ------------------------------------------------------------------ #

    @classmethod
    def run_speed_test_job(cls, job):
        """Job handler for ``monitoring.speedtest.run``."""
        result = cls.run_test()
        from app.services.settings_service import SettingsService
        SettingsService.set(LAST_RESULT_KEY, json.dumps(result))
        return result

    @classmethod
    def register_jobs(cls):
        """Register the speed test handler with the job registry.
        Called once at app startup (see app/__init__.py)."""
        from app.jobs import registry
        registry.register(SPEEDTEST_JOB_KIND, cls.run_speed_test_job, replace=True)
