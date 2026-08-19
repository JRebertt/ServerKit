"""Shared deployment plan runner.

Executes the same deployment plan against the local server or a connected agent.
"""

import base64
import os
import time
from datetime import datetime
from typing import Any, Dict

from app import db
from app.models.deployment_job import DeploymentJob
from app.services.remote_command_dispatcher import dispatch_agent_command
from app.services.docker_service import DockerService
from app.services.run_log_service import RunLogStream
from app.services.telemetry_service import TelemetryService, generate_correlation_id


class DeploymentStepError(Exception):
    """Raised when a deployment step fails."""


class DeploymentPlanRunner:
    """Run deployment steps and persist job status/logs."""

    def __init__(self, job: DeploymentJob):
        self.job = job
        self.correlation_id = job.correlation_id or generate_correlation_id()
        if not job.correlation_id:
            job.correlation_id = self.correlation_id
        # All log/step/close writes funnel through the one batched, crash-proof
        # seam (plan 51 D4). runner.log() stays a thin wrapper for call-site
        # compatibility with the 98ad048 code.
        self.stream = RunLogStream.for_job(job)

    @property
    def is_remote(self) -> bool:
        return bool(self.job.target_server_id)

    def run(self) -> Dict[str, Any]:
        plan = self.job.get_plan()
        steps = plan.get('steps', [])
        results = []

        # Everything — including the very first status write and log line — runs
        # inside the try so ANY failure (schema bugs, telemetry errors, DB hiccups)
        # marks the job failed with a visible error instead of leaving it stuck
        # at "running 0%" with no logs forever.
        try:
            self.job.mark_running()
            self.job.total_steps = len(steps)
            db.session.commit()

            self.log('info', f"Deployment started on {self.job.target_server_name}")
            TelemetryService.emit(
                source='deployment',
                event_type='deployment.started',
                message=f'Deployment started: {self.job.kind}',
                severity='info',
                resource_type='deployment_job',
                resource_id=self.job.id,
                correlation_id=self.correlation_id,
                payload={
                    'job_id': self.job.id,
                    'kind': self.job.kind,
                    'target_server_id': self.job.target_server_id,
                    'total_steps': len(steps),
                },
                commit=False,
            )

            for index, step in enumerate(steps, start=1):
                name = step.get('name') or step.get('type') or f"Step {index}"
                # set_step flushes prior lines, updates the job row, records the
                # previous step's duration, and emits a live status (D4).
                self.stream.set_step(index, name)

                self.log('info', name, step_index=index)
                TelemetryService.emit(
                    source='deployment',
                    event_type='deployment.step_started',
                    message=f'Deployment step {index} started: {name}',
                    severity='info',
                    resource_type='deployment_job',
                    resource_id=self.job.id,
                    correlation_id=self.correlation_id,
                    payload={'job_id': self.job.id, 'step_index': index, 'step_name': name},
                    commit=False,
                )
                result = self._execute_step(step)
                results.append({'step': index, 'name': name, 'result': result})

            self.job.mark_succeeded()
            self.job.current_step_name = None
            self.job.set_result({'steps': results})
            db.session.commit()

            self.log('info', 'Deployment completed')
            TelemetryService.emit(
                source='deployment',
                event_type='deployment.completed',
                message=f'Deployment completed: {self.job.kind}',
                severity='info',
                resource_type='deployment_job',
                resource_id=self.job.id,
                correlation_id=self.correlation_id,
                payload={'job_id': self.job.id, 'kind': self.job.kind, 'total_steps': len(steps)},
                commit=False,
            )
            # Final flush + persist step timings; terminal status emit.
            self.stream.close('succeeded')
            return {'success': True, 'steps': results}

        except Exception as exc:
            # The session may be wedged (e.g. a failed flush rolled everything
            # back) — start clean, then mark the job failed. Never let the
            # failure-handling itself raise: a stuck "running" job is worse
            # than a missing log line.
            try:
                db.session.rollback()
                self.job.mark_failed(str(exc))
                self.job.set_result({'steps': results})
                db.session.commit()
            except Exception:
                db.session.rollback()

            self.log('error', str(exc), step_index=self.job.current_step)
            try:
                TelemetryService.emit(
                    source='deployment',
                    event_type='deployment.failed',
                    message=f'Deployment failed: {self.job.kind}',
                    severity='error',
                    resource_type='deployment_job',
                    resource_id=self.job.id,
                    correlation_id=self.correlation_id,
                    payload={
                        'job_id': self.job.id,
                        'kind': self.job.kind,
                        'error': str(exc),
                        'failed_step': self.job.current_step,
                    },
                    commit=False,
                )
            except Exception:
                pass
            # Final flush + persist failure tail / hint / step timings; terminal
            # status emit. Marking-failed above never depends on this (D10).
            self.stream.close('failed', error_message=str(exc))
            return {'success': False, 'error': str(exc), 'steps': results}

    def log(self, level: str, message: str, data: Any = None, step_index: int = None):
        """Thin wrapper over the batched RunLogStream (kept for call-site
        compatibility with the 98ad048 runner). Never raises."""
        self.stream.log(level, message, step_index=step_index, data=data)

    def _execute_step(self, step: Dict[str, Any]) -> Any:
        step_type = step.get('type')

        if step_type == 'log':
            self.log(step.get('level', 'info'), step.get('message', ''), step.get('data'))
            return {'success': True}

        if step_type == 'sleep':
            seconds = min(float(step.get('seconds', 1)), 30)
            time.sleep(seconds)
            return {'success': True, 'seconds': seconds}

        if step_type == 'file.write':
            return self._file_write(step)

        if step_type == 'docker.compose.up':
            return self._compose_up(step)

        if step_type == 'docker.compose.ps':
            return self._compose_ps(step)

        if step_type == 'docker.compose.logs':
            return self._compose_logs(step)

        raise DeploymentStepError(f"Unknown deployment step type: {step_type}")

    def _file_write(self, step: Dict[str, Any]) -> Dict[str, Any]:
        path = step.get('path')
        content = step.get('content', '')
        mode = int(step.get('mode', 0o644))

        if not path:
            raise DeploymentStepError('file.write step requires path')

        if self.is_remote:
            encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
            data = self._send_agent_command(
                'file:write',
                {
                    'path': path,
                    'content': encoded,
                    'mode': mode,
                    'create_dirs': step.get('create_dirs', True),
                },
                timeout=step.get('timeout', 30),
            )
            self.log('debug', f"Wrote remote file {path}", data)
            return data

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as handle:
            handle.write(content)
        os.chmod(path, mode)
        result = {'success': True, 'path': path, 'size': len(content)}
        self.log('debug', f"Wrote local file {path}", result)
        return result

    def _compose_up(self, step: Dict[str, Any]) -> Dict[str, Any]:
        detach = step.get('detach', True)
        build = step.get('build', False)

        if self.is_remote:
            compose_file = step.get('compose_file') or step.get('project_path')
            if not compose_file:
                raise DeploymentStepError('docker.compose.up step requires compose_file for remote targets')
            data = self._send_agent_command(
                'docker:compose:up',
                {'project_path': compose_file, 'detach': detach, 'build': build},
                timeout=step.get('timeout', 300),
            )
            self.log('debug', 'Remote compose up finished', data)
            return data

        project_dir = step.get('project_dir') or step.get('project_path')
        if not project_dir:
            raise DeploymentStepError('docker.compose.up step requires project_dir for local targets')
        # Stream the real pull/build/start transcript into the run log so the
        # Deploy Console shows it live and a failure persists a meaningful tail
        # (plan 51 D5). The line callback rides the batched stream.
        current_step = self.job.current_step
        result = DockerService.compose_up_streaming(
            project_dir,
            on_line=lambda line: self.stream.log('info', line, step_index=current_step),
            detach=detach,
            build=build,
        )
        if not result.get('success'):
            raise DeploymentStepError(
                result.get('error')
                or f"docker compose up failed (exit code {result.get('exit_code')})"
            )
        self.log('debug', 'Local compose up finished')
        return result

    def _compose_ps(self, step: Dict[str, Any]) -> Dict[str, Any]:
        if self.is_remote:
            compose_file = step.get('compose_file') or step.get('project_path')
            data = self._send_agent_command(
                'docker:compose:ps',
                {'project_path': compose_file},
                timeout=step.get('timeout', 30),
            )
            self.log('debug', 'Remote compose ps finished', data)
            return {'containers': data}

        project_dir = step.get('project_dir') or step.get('project_path')
        containers = DockerService.compose_ps(project_dir)
        result = {'containers': containers}
        self.log('debug', 'Local compose ps finished', result)
        return result

    def _compose_logs(self, step: Dict[str, Any]) -> Dict[str, Any]:
        service = step.get('service')
        tail = int(step.get('tail', 100))

        if self.is_remote:
            compose_file = step.get('compose_file') or step.get('project_path')
            data = self._send_agent_command(
                'docker:compose:logs',
                {'project_path': compose_file, 'service': service or '', 'tail': tail},
                timeout=step.get('timeout', 30),
            )
            self.log('debug', 'Remote compose logs fetched', data)
            return data

        project_dir = step.get('project_dir') or step.get('project_path')
        result = DockerService.compose_logs(project_dir, service=service, tail=tail)
        if not result.get('success'):
            raise DeploymentStepError(result.get('error') or 'docker compose logs failed')
        return result

    def _send_agent_command(self, action: str, params: Dict[str, Any], timeout: float = 30.0) -> Any:
        result = dispatch_agent_command(
            server_id=self.job.target_server_id,
            action=action,
            params=params,
            timeout=float(timeout),
            user_id=self.job.requested_by,
        )

        if not result.get('success'):
            raise DeploymentStepError(result.get('error') or f'Agent command failed: {action}')

        data = result.get('data')
        if isinstance(data, dict) and data.get('success') is False:
            raise DeploymentStepError(data.get('error') or f'Agent command failed: {action}')

        return data if data is not None else {'success': True}
