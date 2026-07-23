"""Simulated deployments — scripted DeploymentJobs for the Deploy Console.

Plan 51.5: lets a developer exercise the full console (StepRail, live log
stream, ErrorCard + hints, SuccessBanner, retry) on any dev machine with no
Docker, shell, or network access. The "runner" is a script that drives the
REAL ``RunLogStream``, so DB rows, socket batches, poll fallback, failure
tails, hints, row cap, and step timings behave exactly as they do for real
deploys — what you test locally is what production renders.

Gated by ``DEMO_DEPLOYS_ENABLED`` (on in development/testing config, off in
production; env override ``SERVERKIT_DEMO_DEPLOYS``). Demo jobs run on the
local panel only — never against remote/agent servers.
"""

import time
import uuid
from datetime import datetime
from typing import Dict, Optional

from app import db
from app.models.deployment_job import DeploymentJob
from app.services.run_log_service import RunLogStream
from app.services.telemetry_service import generate_correlation_id

DEMO_KIND = 'demo_deploy'

# Per-line pacing by requested speed. 'instant' exists for tests.
SPEED_DELAYS = {'instant': 0.0, 'fast': 0.02, 'realtime': 0.3}


class _DemoFailure(Exception):
    """A scripted (intentional) failure inside a demo scenario."""


def _step(name, lines, fail=None):
    step = {'name': name, 'lines': lines}
    if fail:
        step['fail'] = fail
    return step


def _success_steps():
    return [
        _step('Validate configuration', [
            ('info', 'Reading service manifest'),
            ('debug', 'Manifest OK — 1 service, 2 volumes, 1 network'),
            ('info', 'Checking port availability for 8080'),
            ('info', 'Port 8080 is free'),
        ]),
        _step('Pull base image', [
            ('info', 'Pulling node:20-alpine'),
            ('info', '20-alpine: pulling from library/node'),
            ('debug', 'Layer a1b2c3d4 already exists'),
            ('info', 'Status: image is up to date for node:20-alpine'),
        ]),
        _step('Build application', [
            ('info', 'Step 1/6 : FROM node:20-alpine'),
            ('info', 'Step 2/6 : WORKDIR /app'),
            ('info', 'Step 3/6 : COPY package*.json ./'),
            ('info', 'Step 4/6 : RUN npm ci --omit=dev'),
            ('info', 'added 214 packages in 6s'),
            ('info', 'Step 5/6 : COPY . .'),
            ('info', 'Step 6/6 : CMD ["node", "server.js"]'),
            ('info', 'Successfully built 3f1c2a9d41bb'),
        ]),
        _step('Configure routing', [
            ('info', 'Writing vhost configuration for demo-app'),
            ('info', 'Testing web server configuration'),
            ('info', 'Configuration test passed'),
            ('info', 'Web server reloaded'),
        ]),
        _step('Start containers', [
            ('info', 'Creating network demo-app_default'),
            ('info', 'Creating container demo-app-web-1'),
            ('info', 'Container demo-app-web-1 started'),
        ]),
        _step('Health check', [
            ('info', 'Waiting for http://127.0.0.1:8080/healthz'),
            ('debug', 'Attempt 1: 503 (still starting)'),
            ('info', 'Attempt 2: 200 OK'),
            ('info', 'Service is healthy'),
        ]),
    ]


def _fail_build_steps():
    return [
        _step('Validate configuration', [
            ('info', 'Reading service manifest'),
            ('info', 'Checking port availability for 8080'),
            ('info', 'Port 8080 is free'),
        ]),
        _step('Pull base image', [
            ('info', 'Pulling node:20-alpine'),
            ('info', 'Status: image is up to date for node:20-alpine'),
        ]),
        _step('Build application', [
            ('info', 'Step 4/6 : RUN npm run build'),
            ('info', '> demo-app@1.4.2 build'),
            ('info', '> vite build'),
            ('error', "src/pages/Dashboard.jsx: Rollup failed to resolve import 'chart.js'"),
            ('error', 'npm ERR! code ELIFECYCLE'),
            ('error', 'npm ERR! errno 1'),
            ('error', 'npm ERR! demo-app@1.4.2 build: `vite build`'),
            ('error', 'npm ERR! Failed at the demo-app@1.4.2 build script.'),
        ], fail='Build failed: npm run build exited with code 1'),
        # Present in the plan so the StepRail shows a pending step past the
        # failure; the script raises before reaching it.
        _step('Start containers', []),
    ]


def _long_steps():
    bulk = [('info', f'line {i:05d}: synthetic build output for row-cap testing')
            for i in range(1, 6001)]
    return [
        _step('Prepare', [
            ('info', 'Generating a very chatty build (~6,000 lines)'),
            ('info', 'The persisted log caps at 5,000 rows with a truncation marker'),
        ]),
        _step('Generate output', bulk),
        _step('Finish', [
            ('info', 'Output generation complete (this line lands past the cap)'),
        ]),
    ]


def _ansi_steps():
    return [
        _step('Raw output torture test', [
            ('info', '\x1b[1;32m✔\x1b[0m Compiled successfully in 3.2s'),
            ('info', 'Progress: [====>     ] 42%\rProgress: [========> ] 78%\rProgress: [==========] 100%'),
            ('warn', '\x1b[33mwarning\x1b[0m Deprecated API used in src/legacy.js'),
            ('info', '\x1b]0;build\x07Title-setting sequences are stripped too'),
            ('info', 'Plain line for contrast'),
        ]),
        _step('Verify', [
            ('info', 'If the lines above read cleanly, the sanitizer works'),
        ]),
    ]


def _slow_steps():
    return [
        _step('Queue wait demo', [
            ('info', 'This scenario idled in "pending" first — that was the queued strip'),
        ]),
        _step('Slow step one', [
            ('info', f'Working... ({i}/6)') for i in range(1, 7)
        ]),
        _step('Slow step two', [
            ('info', f'Still working... ({i}/6)') for i in range(1, 7)
        ]),
        _step('Wrap up', [
            ('info', 'Done taking our time'),
        ]),
    ]


# Ordered catalog; dict order is the order the UI lists them in.
SCENARIOS = {
    'success': {
        'name': 'Successful deploy',
        'description': 'Six realistic steps ending in success — step timings and a published URL.',
        'build': _success_steps,
        'result': {'auto_domain': {'success': True, 'url': 'http://demo-app.lvh.me', 'demo': True}},
    },
    'fail-build': {
        'name': 'Failing build',
        'description': 'Fails mid-build with a realistic tail — exercises the error card, hint, and retry.',
        'build': _fail_build_steps,
    },
    'long': {
        'name': 'Very long output',
        'description': '~6,000 lines — proves the 5,000-row cap, truncation marker, and log-pane performance.',
        'build': _long_steps,
    },
    'ansi': {
        'name': 'ANSI / carriage-return noise',
        'description': 'Color codes and \\r progress rewrites — proves the output sanitizer.',
        'build': _ansi_steps,
    },
    'slow': {
        'name': 'Slow deploy',
        'description': 'Sits queued first, then streams slowly — exercises the live timer and follow mode.',
        'build': _slow_steps,
        'pending_delay': 3.0,
        'line_delay_factor': 12.0,
    },
}


class DemoDeployService:
    """Creates and runs simulated (scripted) deployment jobs."""

    @classmethod
    def list_scenarios(cls):
        return [
            {'id': key, 'name': spec['name'], 'description': spec['description']}
            for key, spec in SCENARIOS.items()
        ]

    @classmethod
    def create(cls, scenario: str, speed: str = 'fast',
               user_id: Optional[int] = None, wait: bool = False) -> Dict:
        """Create a demo DeploymentJob and queue it (or run it when wait=True).

        Mirrors DeploymentJobService.install_template's shape so callers and
        the console treat demo jobs like any other deployment.
        """
        spec = SCENARIOS.get(scenario)
        if not spec:
            return {'success': False,
                    'error': f'Unknown scenario "{scenario}". Valid: {", ".join(SCENARIOS)}'}
        if speed not in SPEED_DELAYS:
            return {'success': False,
                    'error': f'Unknown speed "{speed}". Valid: {", ".join(SPEED_DELAYS)}'}

        job = DeploymentJob(
            id=str(uuid.uuid4()),
            kind=DEMO_KIND,
            status='pending',
            target_server_id=None,  # demo jobs are local-panel only
            requested_by=user_id,
            trigger='demo',
            correlation_id=generate_correlation_id(),
        )
        job.set_plan({
            'demo': True,
            'scenario': scenario,
            'speed': speed,
            'steps': [{'name': step['name']} for step in spec['build']()],
        })
        db.session.add(job)
        db.session.commit()

        from app.services.deployment_job_service import DeploymentJobService
        if wait:
            DeploymentJobService.run_job(job.id)
        else:
            try:
                DeploymentJobService._enqueue_demo(job)
            except Exception as exc:
                # Same guard as install_template: never leave a runner-less
                # 'pending' row behind.
                db.session.rollback()
                job.status = 'failed'
                job.error_message = f'Failed to queue demo deployment: {exc}'
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return {'success': False, 'error': job.error_message, 'job_id': job.id}

        return {
            'success': True,
            'job_id': job.id,
            'job': job.to_dict(include_logs=True),
        }

    @classmethod
    def run(cls, job: DeploymentJob) -> Dict:
        """Play the job's scenario through a real RunLogStream."""
        plan = job.get_plan()
        scenario = plan.get('scenario')
        spec = SCENARIOS.get(scenario)
        stream = RunLogStream.for_job(job)
        if not spec:
            return cls._fail(job, stream, f'Unknown demo scenario: {scenario}')

        delay = SPEED_DELAYS.get(plan.get('speed') or 'fast', SPEED_DELAYS['fast'])
        line_delay = min(0.8, delay * spec.get('line_delay_factor', 1.0))

        try:
            if delay and spec.get('pending_delay'):
                # Stay 'pending' for a bit so the console's queued strip shows.
                time.sleep(spec['pending_delay'])

            job.status = 'running'
            job.started_at = datetime.utcnow()
            db.session.commit()

            for index, step in enumerate(spec['build'](), start=1):
                stream.set_step(index, step['name'])
                lines = step['lines']
                bulk = len(lines) > 200
                for i, (level, message) in enumerate(lines):
                    stream.log(level, message, step_index=index)
                    # Bulk steps only pace every 100th line so 'long' stays
                    # snappy while normal steps stream visibly.
                    if line_delay and (not bulk or i % 100 == 0):
                        time.sleep(line_delay)
                if step.get('fail'):
                    raise _DemoFailure(step['fail'])

            job.status = 'succeeded'
            job.completed_at = datetime.utcnow()
            job.current_step_name = None
            job.set_result({**job.get_result(), 'demo': True, 'scenario': scenario,
                            **spec.get('result', {})})
            db.session.commit()
            stream.log('info', 'Simulated deployment finished — no real resources were created.')
            stream.close('succeeded')
            return {'success': True, 'job': job.to_dict(include_logs=True)}
        except _DemoFailure as exc:
            return cls._fail(job, stream, str(exc))
        except Exception as exc:
            # Same crash guard as the real runners: never leave 'running'.
            return cls._fail(job, stream, f'Demo deployment crashed: {exc}')

    @classmethod
    def _fail(cls, job: DeploymentJob, stream: RunLogStream, message: str) -> Dict:
        try:
            db.session.rollback()
            job.status = 'failed'
            job.error_message = message
            job.completed_at = datetime.utcnow()
            result = job.get_result()
            result['demo'] = True
            result.setdefault('scenario', (job.get_plan() or {}).get('scenario'))
            job.set_result(result)
            db.session.commit()
            stream.log('error', message)
        except Exception:
            db.session.rollback()
        stream.close('failed', error_message=message)
        return {'success': False, 'error': message, 'job': job.to_dict(include_logs=True)}
