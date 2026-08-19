"""RunLogStream — the single write seam for all deploy-path logging.

Every deployment/install log line (template installs, repo/app deploys, later
WordPress creates) flows through one ``RunLogStream`` per job. It batches writes
(one DB commit + one socket emit per flush instead of a commit-per-line), keeps a
truthful in-memory tail of the last output for failure reporting, records per-step
timings, sanitizes ANSI/`\\r` noise, caps the persisted row count, and matches a
plain-language hint against the failure output.

Design contract (plan 51, D4/D5/D6/D10):

- ``stream.log(level, message, step_index=None, data=None)`` — NEVER raises.
- ``stream.set_step(index, name)`` — flush, update the job row, emit a status.
- ``stream.close(status, error_message=None)`` — final flush; persist
  ``step_timings`` (always) and, on failure, ``failure_tail`` + ``hint`` into the
  job's existing ``result`` JSON (no schema migration); emit a terminal status.

Flush triggers: 50 buffered lines, 300 ms elapsed, a step change, or close.
Row cap: 5000 persisted rows per job — past the cap we stop persisting detail
(one ``warn`` marker row is written once) but keep maintaining the in-memory tail
so the failure tail always reflects the true end of output.

Socket emits go through injected callables (defaulting to lazy lookups of
``app.sockets.emit_deploy_log`` / ``emit_deploy_status``) so this module stays
import-light and fully testable with the emitter mocked. A failing/absent emitter
never breaks logging.
"""

import json
import re
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, List, Optional

from app import db
from app.models.deployment_job import DeploymentJob, DeploymentJobLog


# ---------------------------------------------------------------------------
# Sanitation (D5): strip ANSI escapes, resolve `\r` progress overwrites. We keep
# clean text with level colors in the UI — we do NOT emulate an ANSI terminal.
# ---------------------------------------------------------------------------
_ANSI_RE = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[ -/]*[@-~]'        # CSI ... final byte
    r'|\].*?(?:\x07|\x1b\\)'         # OSC ... BEL / ST
    r'|[@-Z\\-_]'                    # two-char escapes (e.g. ESC c)
    r')'
)


def sanitize(text: str) -> str:
    """Strip ANSI escape sequences and resolve carriage-return overwrites.

    A ``\\r`` in build output means "redraw this line" (progress bars); we keep
    only the final segment so the stored/rendered text reads like the finished
    line, not a smear of overwrites.
    """
    if text is None:
        return ''
    if not isinstance(text, str):
        text = str(text)
    text = _ANSI_RE.sub('', text)
    if '\r' in text:
        # Preserve a trailing newline, but collapse the overwrites before it.
        trailing_nl = text.endswith('\n')
        segment = text.rstrip('\n').split('\r')[-1]
        text = segment + ('\n' if trailing_nl else '')
    return text.rstrip('\n')


# ---------------------------------------------------------------------------
# Failure hints (D6 / §5.3): first match wins, evaluated against the failure tail
# at close time. One sentence, action-first, never jokey.
# ---------------------------------------------------------------------------
HINTS: List = [
    (re.compile(r'port is already allocated|address already in use', re.I),
     'Another service is already using this port — change the port mapping and retry.'),
    (re.compile(r'pull access denied|unauthorized.*(pull|repository)|manifest unknown', re.I),
     "The image couldn't be pulled — check the image name/tag, or add registry credentials."),
    (re.compile(r'npm ERR!', re.I),
     'The Node build failed — the lines above show the failing package or script.'),
    (re.compile(r'EBADENGINE', re.I),
     'The app needs a different Node version than the build image provides.'),
    (re.compile(r'No matching distribution found|ResolutionImpossible', re.I),
     "A Python dependency couldn't be resolved — check the requirements pins above."),
    (re.compile(r'exited? with code 137|\bKilled\b|OOMKilled', re.I),
     'The build ran out of memory (OOM) — raise the server or app memory limit and retry.'),
    (re.compile(r'no space left on device', re.I),
     "The server's disk is full — free some space and retry."),
    (re.compile(r'is invalid.*compose|yaml.*(parse|scan)|error converting YAML', re.I),
     'The compose file is invalid — the parser error above points at the line.'),
    (re.compile(r'env file .* not found|variable is not set|required variable', re.I),
     'A required environment variable or file is missing — set it in the service settings and retry.'),
]


def match_hint(tail_text: str) -> Optional[str]:
    """Return the first hint whose pattern matches the failure tail, else None."""
    if not tail_text:
        return None
    for pattern, hint in HINTS:
        if pattern.search(tail_text):
            return hint
    return None


def _make_default_emit_log(run_kind: str) -> Callable:
    """Lazy default emitter — resolves the socket helper at call time so this
    module never imports sockets eagerly and stays safe when sockets aren't
    wired (tests, CLI). Emits the generalized run envelope; the deploy kind
    dual-emits the legacy deploy_log inside emit_run_log."""
    def _emit(run_id, lines: List[dict]) -> None:
        try:
            from app.sockets import emit_run_log
            emit_run_log(run_kind, run_id, lines)
        except Exception:
            pass
    return _emit


def _make_default_emit_status(run_kind: str) -> Callable:
    def _emit(run_id, status: dict) -> None:
        try:
            from app.sockets import emit_run_status
            emit_run_status(run_kind, run_id, status)
        except Exception:
            pass
    return _emit


class RunLogStream:
    """Batched, crash-proof log writer for one run.

    Generalized (plan 77 E1) over any model implementing the small RunLike
    protocol: an ``id``, a ``__run_kind__`` class attribute, a ``to_dict()``
    for status emits, and — optionally — ``get_result``/``set_result`` (for
    close-time enrichment) and ``current_step``/``current_step_name`` (for
    step tracking). DeploymentJob keeps its dedicated log table; every other
    kind persists to the generic ``run_log_entries`` table under the same
    ``(run_kind, run_id)`` key the socket room and the REST resync twin use.
    """

    FLUSH_LINES = 50
    FLUSH_INTERVAL = 0.3      # seconds
    ROW_CAP = 5000
    TAIL_SIZE = 80

    def __init__(
        self,
        job: DeploymentJob,
        emit_log: Optional[Callable] = None,
        emit_status: Optional[Callable] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.job = job
        self.run_kind = getattr(job, '__run_kind__', 'deploy')
        self._is_deploy = isinstance(job, DeploymentJob)
        self._buffer: List[dict] = []
        self._clock = clock
        self._last_flush = clock()
        self._tail = deque(maxlen=self.TAIL_SIZE)
        self._cap_hit = False
        self._emit_log = emit_log or _make_default_emit_log(self.run_kind)
        self._emit_status = emit_status or _make_default_emit_status(self.run_kind)

        # Per-step timing: index -> {'name', 'started'}; finalized into a list.
        self._step_started_at: Optional[float] = None
        self._step_started_index: Optional[int] = None
        self._step_started_name: Optional[str] = None
        self._step_timings: List[dict] = []

        # How many rows already exist for this run (retries make fresh runs, but
        # a reconciled/resumed one could carry rows) — the cap is per run.
        try:
            self._rows_written = self._row_query().count()
        except Exception:
            self._rows_written = 0

    @classmethod
    def for_job(cls, job, **kwargs) -> 'RunLogStream':
        return cls(job, **kwargs)

    # ------------------------------------------------------------- storage
    def _row_query(self):
        if self._is_deploy:
            return DeploymentJobLog.query.filter_by(job_id=self.job.id)
        from app.models.run_log import RunLogEntry
        return RunLogEntry.query.filter_by(
            run_kind=self.run_kind, run_id=str(self.job.id))

    def _new_row(self, row: dict):
        if self._is_deploy:
            return DeploymentJobLog(
                job_id=self.job.id,
                step_index=row['step_index'],
                level=row['level'],
                message=row['message'],
                data=row['data'],
            )
        from app.models.run_log import RunLogEntry
        return RunLogEntry(
            run_kind=self.run_kind,
            run_id=str(self.job.id),
            step_index=row['step_index'],
            level=row['level'],
            message=row['message'],
            data=row['data'],
        )

    # ------------------------------------------------------------------ log
    def log(self, level: str, message: str, step_index: Optional[int] = None,
            data: Any = None) -> None:
        """Buffer a log line. NEVER raises (D10)."""
        try:
            clean = sanitize(message)
            payload = None
            if data is not None:
                try:
                    payload = json.dumps(_trim_data(data), default=str)
                except TypeError:
                    payload = json.dumps(str(data))

            # The tail is always maintained, even past the row cap, so the
            # failure tail reflects the true end of output.
            self._tail.append(clean)

            if self._cap_hit:
                return

            if self._rows_written + len(self._buffer) >= self.ROW_CAP:
                # Write a single marker, drop the rest of the buffer, stop
                # persisting detail. Tail keeps flowing above.
                self._buffer.append({
                    'step_index': step_index,
                    'level': 'warn',
                    'message': (
                        f'Log truncated at {self.ROW_CAP} lines — later output is '
                        'not persisted, but the failure tail still reflects the end.'
                    ),
                    'data': None,
                })
                self._cap_hit = True
                self._flush()
                return

            self._buffer.append({
                'step_index': step_index,
                'level': level,
                'message': clean,
                'data': payload,
            })

            if (len(self._buffer) >= self.FLUSH_LINES
                    or (self._clock() - self._last_flush) >= self.FLUSH_INTERVAL):
                self._flush()
        except Exception:
            # Logging must never kill a deployment.
            try:
                db.session.rollback()
            except Exception:
                pass

    # ------------------------------------------------------------------ step
    def set_step(self, index: int, name: Optional[str]) -> None:
        """Persist the step boundary: flush prior lines, update the job row,
        record timing for the previous step, emit a status. Non-raising."""
        try:
            self._flush()
            # Finalize the previous step's duration.
            self._finalize_current_step()
            self._step_started_at = self._clock()
            self._step_started_index = index
            self._step_started_name = name

            if hasattr(self.job, 'current_step'):
                self.job.current_step = index
                self.job.current_step_name = name
            db.session.commit()
            self._emit_status_safe()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    # ----------------------------------------------------------------- close
    def close(self, status: str, error_message: Optional[str] = None) -> None:
        """Final flush + persist timings/tail/hint into job.result; emit a
        terminal status. Non-raising; job status is set by the caller — close()
        only enriches the result and flushes."""
        try:
            self._flush()
            self._finalize_current_step()

            if hasattr(self.job, 'get_result') and hasattr(self.job, 'set_result'):
                result = self.job.get_result() or {}
                if self._step_timings:
                    result['step_timings'] = self._step_timings
                if status == 'failed':
                    tail = list(self._tail)
                    result['failure_tail'] = tail
                    hint = match_hint('\n'.join(tail))
                    if hint:
                        result['hint'] = hint
                self.job.set_result(result)
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        # Emit the terminal status regardless of the persistence outcome.
        self._emit_status_safe()

    # --------------------------------------------------------------- flush
    def _flush(self) -> None:
        """Write buffered rows in ONE commit and emit ONE deploy_log batch."""
        if not self._buffer:
            self._last_flush = self._clock()
            return
        pending = self._buffer
        self._buffer = []
        try:
            entries = [self._new_row(row) for row in pending]
            db.session.add_all(entries)
            db.session.commit()
            self._rows_written += len(entries)
            self._last_flush = self._clock()

            lines = [{
                'id': e.id,
                'step_index': e.step_index,
                'level': e.level,
                'message': e.message,
                'ts': e.created_at.isoformat() if e.created_at else None,
            } for e in entries]
            try:
                self._emit_log(self.job.id, lines)
            except Exception:
                pass
        except Exception:
            # Buffered-drop on flush failure (D10): one telemetry event, then
            # continue. A stuck deployment is worse than a missing log line.
            try:
                db.session.rollback()
            except Exception:
                pass
            self._last_flush = self._clock()
            try:
                from app.services.telemetry_service import TelemetryService
                TelemetryService.emit(
                    source='deployment' if self._is_deploy else 'runs',
                    event_type='deployment.log_flush_failed',
                    message='Deploy log flush failed; dropped a buffered batch',
                    severity='warning',
                    resource_type='deployment_job',
                    resource_id=self.job.id,
                    correlation_id=getattr(self.job, 'correlation_id', None),
                    payload={'job_id': self.job.id, 'dropped': len(pending)},
                    commit=True,
                )
            except Exception:
                pass

    def flush(self) -> None:
        """Public flush for one-off writes (fire-and-forget annotations)."""
        try:
            self._flush()
        except Exception:
            pass

    # --------------------------------------------------------------- helpers
    def _finalize_current_step(self) -> None:
        if self._step_started_index is not None and self._step_started_at is not None:
            duration = max(0.0, self._clock() - self._step_started_at)
            self._step_timings.append({
                'index': self._step_started_index,
                'name': self._step_started_name,
                'seconds': round(duration, 3),
            })
            self._step_started_index = None
            self._step_started_at = None
            self._step_started_name = None

    def emit_status(self) -> None:
        """Public status emit for transitions that happen outside close()
        (e.g. the job consumer announcing 'running')."""
        self._emit_status_safe()

    def _emit_status_safe(self) -> None:
        try:
            self._emit_status(self.job.id, self.job.to_dict())
        except Exception:
            pass


def _trim_data(data: Any) -> Any:
    """Bound the size of structured `data` payloads (parity with the old
    runner._trim_data), so a chatty step can't write a multi-MB row."""
    if isinstance(data, str):
        return data[:6000]
    if isinstance(data, dict):
        return {key: _trim_data(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_trim_data(item) for item in data[:50]]
    return data


_STREAM_ATTR = '_run_log_stream'


def stream_for(job) -> RunLogStream:
    """Return the one stream for *job*, creating it on first use.

    Used where the logging and the terminal ``close()`` sit in different places:
    a plugin handler logs through ``plugins_sdk.deploys`` while the runner
    around it owns the close. Two independent streams would mean two buffers,
    and the step timings recorded by the handler's would be dropped by the
    runner's close. The instance is cached on the job object, so the sharing
    scope is exactly the session that is running it.
    """
    stream = getattr(job, _STREAM_ATTR, None)
    if stream is None:
        stream = RunLogStream.for_job(job)
        try:
            setattr(job, _STREAM_ATTR, stream)
        except Exception:
            pass
    return stream


def append_log(job, level: str, message: str, data: Any = None,
               step_index: Optional[int] = None) -> None:
    """Immediate, persisted single log line for fire-and-forget annotations
    (e.g. post-install notes) where no long-lived stream is open. Flushes at
    once so the line is never left buffered. Non-raising."""
    stream = RunLogStream.for_job(job)
    stream.log(level, message, step_index=step_index, data=data)
    stream.flush()


def list_run_logs(run_kind: str, run_id, after_id: Optional[int] = None,
                  limit: int = 2000) -> List[dict]:
    """Persisted run-envelope lines for (run_kind, run_id), id-ordered.

    The service half of the ``GET /api/v1/runs/<kind>/<id>/logs?after_id``
    resync twin — the API layer never touches the model directly.
    """
    from app.models.run_log import RunLogEntry
    query = RunLogEntry.query.filter_by(run_kind=run_kind, run_id=str(run_id))
    if after_id:
        query = query.filter(RunLogEntry.id > after_id)
    return [row.to_dict() for row in query.order_by(RunLogEntry.id.asc()).limit(limit).all()]
