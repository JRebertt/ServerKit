"""Validation and storage for declarative walkthrough definitions.

Walkthroughs are intentionally data-only.  They may point at routes and stable
``data-walkthrough`` targets, listen for named UI signals, or use a host-owned
status check.  They may never embed JavaScript, selectors outside the
walkthrough namespace, commands, or arbitrary API requests.
"""

import json
import re
from copy import deepcopy
from typing import Any, Dict, List

from app import db
from app.models.system_settings import SystemSettings


MAX_WALKTHROUGHS = 32
MAX_STEPS = 32
MAX_DOCUMENT_BYTES = 128 * 1024
COMPLETION_TYPES = frozenset({'manual', 'route', 'signal', 'check', 'target'})

_CUSTOM_KEY = 'walkthroughs.custom.definitions'
_ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,79}$')
_TOKEN_RE = re.compile(r'^[a-z0-9][a-z0-9._:-]{0,119}$')
_TARGET_RE = re.compile(r'^[a-z0-9][a-z0-9._:-]{0,79}$')
_LEVELS = {'read', 'write', 'admin'}
_GUIDE_FIELDS = {
    '$schema', 'id', 'title', 'title_key', 'description', 'description_key',
    'duration', 'duration_key', 'icon', 'tone', 'secondary', 'permissions', 'steps',
}
_STEP_FIELDS = {
    'id', 'title', 'title_key', 'description', 'description_key', 'action',
    'action_key', 'path', 'target', 'completion',
}
_COMPLETION_FIELDS = {'type', 'path', 'signal', 'check'}


class WalkthroughDefinitionError(ValueError):
    """Raised when a declarative walkthrough document is invalid."""


def _bounded_string(value: Any, *, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= maximum


def validate_walkthrough_definitions(raw: Any, *, field: str = 'walkthroughs') -> List[str]:
    """Return precise validation problems for a walkthrough definition list."""
    if not isinstance(raw, list):
        return [f'{field} must be a list']
    if len(raw) > MAX_WALKTHROUGHS:
        return [f'{field} may contain at most {MAX_WALKTHROUGHS} walkthroughs']

    problems = []
    seen_guides = set()
    for guide_index, guide in enumerate(raw):
        base = f'{field}[{guide_index}]'
        if not isinstance(guide, dict):
            problems.append(f'{base} must be an object')
            continue

        unknown_guide_fields = sorted(set(guide) - _GUIDE_FIELDS)
        if unknown_guide_fields:
            problems.append(f'{base} contains unsupported fields: {", ".join(unknown_guide_fields)}')

        guide_id = guide.get('id')
        if not isinstance(guide_id, str) or not _ID_RE.fullmatch(guide_id):
            problems.append(f'{base}.id must match {_ID_RE.pattern}')
        elif guide_id in seen_guides:
            problems.append(f'{base}.id duplicates {guide_id!r}')
        else:
            seen_guides.add(guide_id)

        for name, maximum in (
                ('title', 120), ('description', 320), ('duration', 80)):
            if name in guide and not _bounded_string(guide[name], maximum=maximum):
                problems.append(f'{base}.{name} must be a non-empty string up to {maximum} characters')
        if not _bounded_string(guide.get('title'), maximum=120):
            problems.append(f'{base}.title is required')
        if not _bounded_string(guide.get('description'), maximum=320):
            problems.append(f'{base}.description is required')

        for name in ('title_key', 'description_key', 'duration_key', 'icon', 'tone'):
            if name in guide and not _bounded_string(guide[name], maximum=120):
                problems.append(f'{base}.{name} must be a non-empty string up to 120 characters')
        if 'secondary' in guide and not isinstance(guide['secondary'], bool):
            problems.append(f'{base}.secondary must be a boolean')

        permissions = guide.get('permissions', [])
        if not isinstance(permissions, list) or len(permissions) > 16:
            problems.append(f'{base}.permissions must be a list with at most 16 entries')
        else:
            for permission_index, permission in enumerate(permissions):
                pbase = f'{base}.permissions[{permission_index}]'
                if not isinstance(permission, dict):
                    problems.append(f'{pbase} must be an object')
                    continue
                if not _bounded_string(permission.get('feature'), maximum=80):
                    problems.append(f'{pbase}.feature is required')
                if permission.get('level') not in _LEVELS:
                    problems.append(f'{pbase}.level must be read, write, or admin')

        steps = guide.get('steps')
        if not isinstance(steps, list) or not steps:
            problems.append(f'{base}.steps must be a non-empty list')
            continue
        if len(steps) > MAX_STEPS:
            problems.append(f'{base}.steps may contain at most {MAX_STEPS} steps')
            continue

        seen_steps = set()
        for step_index, step in enumerate(steps):
            sbase = f'{base}.steps[{step_index}]'
            if not isinstance(step, dict):
                problems.append(f'{sbase} must be an object')
                continue
            unknown_step_fields = sorted(set(step) - _STEP_FIELDS)
            if unknown_step_fields:
                problems.append(f'{sbase} contains unsupported fields: {", ".join(unknown_step_fields)}')
            step_id = step.get('id')
            if not isinstance(step_id, str) or not _ID_RE.fullmatch(step_id):
                problems.append(f'{sbase}.id must match {_ID_RE.pattern}')
            elif step_id in seen_steps:
                problems.append(f'{sbase}.id duplicates {step_id!r}')
            else:
                seen_steps.add(step_id)

            if not _bounded_string(step.get('title'), maximum=120):
                problems.append(f'{sbase}.title is required')
            if not _bounded_string(step.get('description'), maximum=500):
                problems.append(f'{sbase}.description is required')
            for name, maximum in (
                    ('action', 80), ('title_key', 120),
                    ('description_key', 120), ('action_key', 120)):
                if name in step and not _bounded_string(step[name], maximum=maximum):
                    problems.append(f'{sbase}.{name} must be a non-empty string up to {maximum} characters')

            path = step.get('path')
            if path is not None and (not _bounded_string(path, maximum=500) or not path.startswith('/')):
                problems.append(f'{sbase}.path must begin with / and contain at most 500 characters')
            target = step.get('target')
            if target is not None and (not isinstance(target, str) or not _TARGET_RE.fullmatch(target)):
                problems.append(f'{sbase}.target must be a stable data-walkthrough token')

            completion = step.get('completion', {'type': 'manual'})
            if not isinstance(completion, dict):
                problems.append(f'{sbase}.completion must be an object')
                continue
            unknown_completion_fields = sorted(set(completion) - _COMPLETION_FIELDS)
            if unknown_completion_fields:
                problems.append(
                    f'{sbase}.completion contains unsupported fields: '
                    f'{", ".join(unknown_completion_fields)}')
            completion_type = completion.get('type', 'manual')
            if completion_type not in COMPLETION_TYPES:
                problems.append(
                    f'{sbase}.completion.type must be one of {", ".join(sorted(COMPLETION_TYPES))}')
            elif completion_type == 'route':
                route = completion.get('path') or path
                if not isinstance(route, str) or not route.startswith('/') or len(route) > 500:
                    problems.append(f'{sbase}.completion.path must be a route beginning with /')
            elif completion_type == 'signal':
                signal = completion.get('signal')
                if not isinstance(signal, str) or not _TOKEN_RE.fullmatch(signal):
                    problems.append(f'{sbase}.completion.signal must be a stable event token')
            elif completion_type == 'check':
                check = completion.get('check')
                if not isinstance(check, str) or not _TOKEN_RE.fullmatch(check):
                    problems.append(f'{sbase}.completion.check must be a named host check')
            elif completion_type == 'target' and target is None:
                problems.append(f'{sbase}.completion target requires step.target')

    try:
        encoded_size = len(json.dumps(raw, ensure_ascii=False).encode('utf-8'))
        if encoded_size > MAX_DOCUMENT_BYTES:
            problems.append(f'{field} exceeds the {MAX_DOCUMENT_BYTES}-byte limit')
    except (TypeError, ValueError):
        problems.append(f'{field} must contain JSON-compatible values')

    return problems


class WalkthroughDefinitionService:
    """Panel-wide custom walkthrough library managed by administrators."""

    @staticmethod
    def get_definitions() -> List[Dict[str, Any]]:
        raw = SystemSettings.get(_CUSTOM_KEY, [])
        if validate_walkthrough_definitions(raw, field='definitions'):
            return []
        return deepcopy(raw)

    @staticmethod
    def save_definitions(raw: Any) -> List[Dict[str, Any]]:
        problems = validate_walkthrough_definitions(raw, field='definitions')
        if problems:
            raise WalkthroughDefinitionError('; '.join(problems))
        definitions = deepcopy(raw)
        SystemSettings.set(
            key=_CUSTOM_KEY,
            value=definitions,
            value_type='json',
            description='Panel-wide custom guided walkthrough definitions',
        )
        db.session.commit()
        return definitions
