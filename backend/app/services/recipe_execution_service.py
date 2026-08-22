"""Resumable Recipe execution on the existing deployment run envelope.

A Recipe is a normalized ``serverkit.yaml`` manifest with ``requires``,
``configure`` and ``verify`` blocks. The manifest plan and Recipe steps share
one DeploymentJob, one log stream, and one persisted progress record. Unknown
``type:kind`` capabilities are refused before any mutation.

Human handoffs pause the run in ``waiting``. Submitted values are stored in the
existing encrypted Secret Vault, never in the job plan/result/logs, and are
deleted when the run completes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from app import db
from app.models.application_manifest import STATUS_APPLIED, STATUS_ERROR
from app.models.deployment_job import DeploymentJob
from app.models.environment import Environment
from app.models.project import Project
from app.models.secret_vault import Secret, SecretVault
from app.services.manifest_apply_service import ManifestApplyService
from app.services.run_log_service import stream_for
from app.services.secret_vault_service import SecretService
from app.utils.sensitive_data_filter import mask_payload


RECIPE_JOB_KIND = 'recipe.run'
RECIPE_WAITING = 'waiting'
HANDOFF_VAULT_SLUG = 'recipe-runs'


@dataclass
class RecipeStepContext:
    job: DeploymentJob
    project: Project
    environment: Optional[Environment]
    step: Dict[str, Any]
    completed: Dict[str, Any]

    def input(self, key: str) -> Optional[str]:
        """Return one encrypted-at-rest handoff value by declared input key."""
        for plan_step in (self.job.get_plan() or {}).get('steps', []):
            recipe_step = plan_step.get('recipe_step') or {}
            input_spec = recipe_step.get('input') or {}
            if input_spec.get('key') == key:
                secret = RecipeExecutionService._handoff_secret(
                    self.job.id, recipe_step.get('id'))
                if secret and not secret.is_expired:
                    return secret.value
        return None


class RecipeStepRegistry:
    """Closed runtime vocabulary for data-only Recipe steps."""

    _handlers: Dict[str, Dict[str, Optional[Callable]]] = {}

    @classmethod
    def register(cls, step_type: str, kind: str, handler: Callable,
                 check: Optional[Callable] = None, replace: bool = False) -> None:
        capability = f'{step_type}:{kind}'
        if not callable(handler):
            raise ValueError('Recipe step handler must be callable')
        if capability in cls._handlers and not replace:
            raise ValueError(f'Recipe capability already registered: {capability}')
        cls._handlers[capability] = {'handler': handler, 'check': check}

    @classmethod
    def supports(cls, capability: str) -> bool:
        # Handoffs are an engine primitive; their ``kind`` only describes the
        # input presentation (token, acknowledgement, credential, ...).
        return capability.startswith('handoff:') or capability in cls._handlers

    @classmethod
    def execute(cls, context: RecipeStepContext) -> Dict[str, Any]:
        capability = context.step['capability']
        entry = cls._handlers.get(capability)
        if not entry:
            raise RuntimeError(f'Unsupported Recipe capability: {capability}')
        check = entry.get('check')
        if callable(check) and check(context):
            return {'already_complete': True}
        outcome = entry['handler'](context)
        return outcome if isinstance(outcome, dict) else {'result': outcome}

    @classmethod
    def clear(cls) -> None:
        """Test helper; production registrations are restored at app startup."""
        cls._handlers.clear()


class RecipeExecutionService:

    @classmethod
    def register_jobs(cls) -> None:
        from app.services import deploy_kind_registry
        deploy_kind_registry.register(RECIPE_JOB_KIND, cls.run, replace=True)

    @staticmethod
    def unsupported_capabilities(normalized: Dict[str, Any]) -> list[str]:
        """Return unknown capabilities without creating or changing any rows."""
        recipe_steps = list(normalized.get('configure') or []) + list(
            normalized.get('verify') or [])
        return sorted({
            step['capability'] for step in recipe_steps
            if not RecipeStepRegistry.supports(step['capability'])
        })

    @classmethod
    def start(cls, project: Project, normalized: Dict[str, Any], *,
              user_id: Optional[int], slug: Optional[str] = None,
              title: Optional[str] = None, manifest_row=None,
              wait: bool = False) -> Dict[str, Any]:
        """Create one Recipe run after capability and manifest preflight."""
        recipe_steps = list(normalized.get('configure') or []) + list(
            normalized.get('verify') or [])
        if not recipe_steps:
            return {'success': False, 'error': 'Manifest does not contain Recipe steps'}

        unsupported = cls.unsupported_capabilities(normalized)
        if unsupported:
            return {
                'success': False,
                'error': 'This panel does not support every Recipe capability',
                'unsupported_capabilities': unsupported,
            }

        environment = ManifestApplyService._default_environment(project)
        manifest_plan = ManifestApplyService.plan(project, normalized, environment)
        if manifest_plan.get('blockers'):
            return {
                'success': False,
                'refused': True,
                'error': manifest_plan['blockers'][0]['message'],
                'blockers': manifest_plan['blockers'],
                'issues': manifest_plan.get('issues', []),
            }

        steps = []
        for idx, step in enumerate(manifest_plan.get('steps') or []):
            steps.append({
                'name': step['description'],
                'phase': 'manifest',
                'step_id': f'manifest-{idx + 1}-{step["type"]}',
                'manifest_step': step,
            })
        for step in normalized.get('configure') or []:
            steps.append({
                'name': step['title'], 'phase': 'configure',
                'step_id': step['id'], 'recipe_step': step,
            })
        for step in normalized.get('verify') or []:
            steps.append({
                'name': step['title'], 'phase': 'verify',
                'step_id': step['id'], 'recipe_step': step,
            })

        cls.register_jobs()
        from app.services.deployment_job_service import DeploymentJobService
        return DeploymentJobService.start_registered(
            RECIPE_JOB_KIND,
            steps=steps,
            user_id=user_id,
            trigger='recipe',
            wait=wait,
            plan={
                'recipe': {
                    'slug': slug or normalized.get('project') or 'inline',
                    'title': title or normalized.get('project') or 'Guided outcome',
                    'requirements': normalized.get('requires') or {},
                    'capabilities': normalized.get('capabilities') or [],
                },
                'project_id': project.id,
                'environment_id': environment.id if environment else None,
                'manifest_row_id': getattr(manifest_row, 'id', None),
                'issues': manifest_plan.get('issues', []),
            },
        )

    @classmethod
    def run(cls, job: DeploymentJob) -> Dict[str, Any]:
        """Run from the first incomplete step, pausing only at a handoff."""
        plan = job.get_plan() or {}
        try:
            return cls._run_steps(job, plan)
        except Exception:
            cls._mark_manifest(plan.get('manifest_row_id'), success=False)
            db.session.commit()
            raise

    @classmethod
    def _run_steps(cls, job: DeploymentJob, plan: Dict[str, Any]) -> Dict[str, Any]:
        project = Project.query.get(plan.get('project_id'))
        if not project:
            raise RuntimeError('Recipe project no longer exists')
        environment = (Environment.query.get(plan.get('environment_id'))
                       if plan.get('environment_id') else None)
        state = job.get_result() or {}
        completed = dict(state.get('completed_steps') or {})
        stream = stream_for(job)

        for index, plan_step in enumerate(plan.get('steps') or []):
            step_id = plan_step.get('step_id') or f'step-{index + 1}'
            if step_id in completed:
                continue

            name = plan_step.get('name') or step_id
            stream.set_step(index + 1, name)
            if plan_step.get('phase') == 'manifest':
                outcome = ManifestApplyService._execute_step(
                    project, environment, plan_step['manifest_step'], job.requested_by)
            else:
                step = plan_step.get('recipe_step') or {}
                dependencies = step.get('depends_on') or []
                missing = [dep for dep in dependencies if dep not in completed]
                if missing:
                    raise RuntimeError(
                        f'Recipe step {step_id} is missing dependencies: {", ".join(missing)}')
                if step.get('type') == 'handoff':
                    secret = cls._handoff_secret(job.id, step_id)
                    if secret and secret.is_expired:
                        db.session.delete(secret)
                        db.session.commit()
                        secret = None
                    if not secret:
                        return cls._pause_for_handoff(job, state, completed, step, stream)
                    outcome = {'accepted': True, 'input_key': step['input']['key']}
                else:
                    context = RecipeStepContext(
                        job=job, project=project, environment=environment,
                        step=step, completed=completed)
                    outcome = RecipeStepRegistry.execute(context)

            completed[step_id] = {
                'status': 'ok',
                'completed_at': datetime.utcnow().isoformat(),
                'result': mask_payload(outcome or {}),
            }
            state['completed_steps'] = completed
            state['handoff'] = None
            job.set_result(state)
            job.current_step = index + 1
            db.session.commit()
            stream.log('info', f'Completed: {name}', step_index=index + 1)

        cls._delete_handoff_secrets(job.id)
        state['completed_steps'] = completed
        state['handoff'] = None
        state['verified'] = bool(normalized_verify_count(plan))
        job.set_result(state)
        cls._mark_manifest(plan.get('manifest_row_id'), success=True)
        db.session.commit()
        return {
            'success': True,
            'completed': len(completed),
            'verified': state['verified'],
        }

    @classmethod
    def submit_handoff(cls, job: DeploymentJob, *, step_id: str, value: str,
                       user_id: Optional[int], wait: bool = False) -> Dict[str, Any]:
        """Encrypt a waiting handoff value and resume the same run."""
        state = job.get_result() or {}
        handoff = state.get('handoff') or {}
        if job.kind != RECIPE_JOB_KIND or job.status != RECIPE_WAITING:
            return {'success': False, 'error': 'Recipe run is not waiting for input'}
        if handoff.get('step_id') != step_id:
            return {'success': False, 'error': 'Recipe run is waiting on a different step'}
        if not isinstance(value, str) or not value.strip():
            return {'success': False, 'error': 'A handoff value is required'}
        if len(value) > 8192:
            return {'success': False, 'error': 'Handoff value is too large'}

        plan_step = next((entry for entry in (job.get_plan() or {}).get('steps', [])
                          if entry.get('step_id') == step_id), None)
        step = (plan_step or {}).get('recipe_step') or {}
        ttl = step.get('ttl_seconds')
        cls._store_handoff_secret(
            job, step_id, value.strip(), user_id=user_id,
            expires_at=(datetime.utcnow() + timedelta(seconds=ttl)) if ttl else None)

        state['handoff'] = {**handoff, 'received': True}
        job.set_result(state)
        job.status = 'pending'
        job.completed_at = None
        db.session.commit()

        from app.services.deployment_job_service import DeploymentJobService
        if wait:
            result = DeploymentJobService.run_job(job.id)
        else:
            try:
                DeploymentJobService._enqueue_registered(job)
                result = {'success': True, 'queued': True}
            except Exception as exc:
                db.session.rollback()
                job.status = RECIPE_WAITING
                db.session.commit()
                return {'success': False, 'error': f'Failed to resume Recipe: {exc}'}
        return {**result, 'job_id': job.id, 'job': job.to_dict()}

    @classmethod
    def _pause_for_handoff(cls, job, state, completed, step, stream):
        input_spec = step.get('input') or {}
        state['completed_steps'] = completed
        state['handoff'] = {
            'step_id': step['id'],
            'title': step['title'],
            'description': step.get('description') or '',
            'input': input_spec,
            'ttl_seconds': step.get('ttl_seconds'),
            'received': False,
        }
        job.set_result(state)
        job.status = RECIPE_WAITING
        job.completed_at = None
        db.session.commit()
        stream.log('warn', f'Waiting for operator input: {step["title"]}')
        stream.flush()
        stream.emit_status()
        return {'success': True, 'paused': True, 'handoff': state['handoff']}

    @staticmethod
    def _handoff_secret_name(job_id: str, step_id: str) -> str:
        return f'{job_id}:{step_id}'[:200]

    @classmethod
    def _handoff_secret(cls, job_id: str, step_id: str) -> Optional[Secret]:
        vault = SecretVault.query.filter_by(slug=HANDOFF_VAULT_SLUG).first()
        if not vault:
            return None
        return Secret.query.filter_by(
            vault_id=vault.id, name=cls._handoff_secret_name(job_id, step_id)).first()

    @classmethod
    def _store_handoff_secret(cls, job, step_id, value, *, user_id, expires_at):
        plan = job.get_plan() or {}
        project = Project.query.get(plan.get('project_id'))
        vault = SecretVault.query.filter_by(slug=HANDOFF_VAULT_SLUG).first()
        if not vault:
            vault = SecretVault(
                name='Recipe run inputs', slug=HANDOFF_VAULT_SLUG,
                description='Short-lived encrypted values supplied to Recipe handoffs',
                created_by=user_id,
                workspace_id=getattr(project, 'workspace_id', None),
            )
            db.session.add(vault)
            db.session.flush()
        name = cls._handoff_secret_name(job.id, step_id)
        secret = SecretService.upsert_internal_secret(
            vault.id, name, value,
            description='Encrypted Recipe handoff input; deleted after run completion',
            expires_at=expires_at,
        )
        return secret

    @classmethod
    def _delete_handoff_secrets(cls, job_id: str) -> None:
        vault = SecretVault.query.filter_by(slug=HANDOFF_VAULT_SLUG).first()
        if not vault:
            return
        prefix = f'{job_id}:%'
        Secret.query.filter(Secret.vault_id == vault.id, Secret.name.like(prefix)).delete(
            synchronize_session=False)
        db.session.commit()

    @staticmethod
    def _mark_manifest(row_id, *, success: bool) -> None:
        if not row_id:
            return
        from app.models.application_manifest import ApplicationManifest
        row = ApplicationManifest.query.get(row_id)
        if not row:
            return
        row.status = STATUS_APPLIED if success else STATUS_ERROR
        if success:
            row.applied_at = datetime.utcnow()
            row.last_error = None


def normalized_verify_count(plan: Dict[str, Any]) -> int:
    return sum(1 for step in plan.get('steps') or [] if step.get('phase') == 'verify')
