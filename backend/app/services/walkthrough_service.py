"""Per-user progress storage for guided UI walkthroughs.

Walkthrough definitions live in the frontend so they can point at real routes
and controls without turning the backend into a second navigation registry.
Only the small, non-sensitive progress ledger is persisted here.  The existing
``system_settings`` JSON store keeps this additive and migration-free while a
user-id-qualified key preserves strict self-scoping.
"""

import re
from typing import Any, Dict

from app import db
from app.models.system_settings import SystemSettings


WALKTHROUGH_STATE_VERSION = 1
_KEY_PREFIX = 'walkthroughs.user.'
_ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,79}$')
_STATUSES = {'active', 'completed', 'dismissed'}


class WalkthroughStateError(ValueError):
    """Raised when a client submits an invalid progress ledger."""


class WalkthroughService:

    @staticmethod
    def _key(user_id: int) -> str:
        return f'{_KEY_PREFIX}{int(user_id)}'

    @classmethod
    def get_state(cls, user_id: int) -> Dict[str, Any]:
        raw = SystemSettings.get(cls._key(user_id), {})
        if not isinstance(raw, dict):
            return cls.empty_state()
        try:
            return cls.normalize_state(raw)
        except WalkthroughStateError:
            return cls.empty_state()

    @classmethod
    def save_state(cls, user_id: int, raw: Any) -> Dict[str, Any]:
        state = cls.normalize_state(raw)
        SystemSettings.set(
            key=cls._key(user_id),
            value=state,
            value_type='json',
            description='Per-user guided walkthrough progress',
            user_id=user_id,
        )
        db.session.commit()
        return state

    @staticmethod
    def empty_state() -> Dict[str, Any]:
        return {'version': WALKTHROUGH_STATE_VERSION, 'active_id': None, 'progress': {}}

    @classmethod
    def normalize_state(cls, raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise WalkthroughStateError('state must be an object')

        active_id = raw.get('active_id')
        if active_id is not None and not cls._valid_id(active_id):
            raise WalkthroughStateError('active_id is invalid')

        progress = raw.get('progress', {})
        if not isinstance(progress, dict):
            raise WalkthroughStateError('progress must be an object')
        if len(progress) > 64:
            raise WalkthroughStateError('too many walkthrough progress entries')

        normalized = {}
        for walkthrough_id, entry in progress.items():
            if not cls._valid_id(walkthrough_id):
                raise WalkthroughStateError('walkthrough id is invalid')
            if not isinstance(entry, dict):
                raise WalkthroughStateError(f'{walkthrough_id} progress must be an object')

            status = entry.get('status', 'active')
            if status not in _STATUSES:
                raise WalkthroughStateError(f'{walkthrough_id} status is invalid')
            completed_steps = entry.get('completed_steps', [])
            if not isinstance(completed_steps, list) or len(completed_steps) > 64:
                raise WalkthroughStateError(
                    f'{walkthrough_id} completed_steps must be a bounded array')

            clean_steps = []
            for step_id in completed_steps:
                if not cls._valid_id(step_id):
                    raise WalkthroughStateError(
                        f'{walkthrough_id} contains an invalid step id')
                if step_id not in clean_steps:
                    clean_steps.append(step_id)

            normalized[walkthrough_id] = {
                'status': status,
                'completed_steps': clean_steps,
                'started_at': cls._timestamp(entry.get('started_at')),
                'updated_at': cls._timestamp(entry.get('updated_at')),
                'completed_at': cls._timestamp(entry.get('completed_at')),
            }

        if active_id and active_id not in normalized:
            raise WalkthroughStateError('active_id has no matching progress entry')
        if active_id and normalized[active_id]['status'] != 'active':
            active_id = None

        return {
            'version': WALKTHROUGH_STATE_VERSION,
            'active_id': active_id,
            'progress': normalized,
        }

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, str) and bool(_ID_RE.fullmatch(value))

    @staticmethod
    def _timestamp(value: Any):
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 40:
            raise WalkthroughStateError('timestamps must be ISO strings')
        return value
