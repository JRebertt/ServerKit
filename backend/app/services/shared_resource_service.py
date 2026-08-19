"""Service layer for polymorphic shared resources (tags + variable groups).

A thin, stateless facade over the models in
``app.models.shared_resource``. It is purely additive: nothing here reads or
writes the existing per-resource env-var tables. Resources are addressed by
``(resource_type, resource_id)`` where ``resource_id`` is coerced to a string so
both int-keyed (apps, servers) and string-keyed (container names) resources work.

Override / merge rule for :meth:`resolve_variables`
---------------------------------------------------
A resource may have several groups attached. The effective variable set is built
by iterating the attached groups **in attachment order** (oldest attachment
first) and writing each group's variables into a dict keyed by variable key.
Because a later write overwrites an earlier one, **the most recently attached
group wins** on key collisions ("last attachment wins"). Each resolved entry
records the ``group_id``/``group_name`` it came from so callers can show
provenance.
"""
import re

from app import db
from app.models.shared_resource import (
    ResourceTag,
    SharedVariable,
    SharedVariableGroup,
    SharedVariableGroupAttachment,
)

# Sentinel: distinguish "leave target_service unchanged" from "clear to all (None)".
_UNSET = object()


def _audit(action, **kwargs):
    """Best-effort audit log for a shared-resource mutation.

    Audit logging must never break the underlying write, so any failure here
    (missing request context, telemetry hiccup, etc.) is swallowed. We reuse
    the generic ``resource.*`` actions plus a ``feature: 'shared_resource'``
    marker in ``details`` so these rows are filterable without a new action
    constant or DB table.
    """
    try:
        from app.services.audit_service import AuditService
        details = kwargs.pop('details', None) or {}
        details.setdefault('feature', 'shared_resource')
        AuditService.log(action, details=details, **kwargs)
    except Exception:
        pass


def _current_user_id():
    """Resolve the acting user id, or None outside a request.

    Goes through rbac.get_current_user() rather than get_jwt_identity() so an
    API-key caller is attributed to the key's owner. Reading the JWT directly
    *raises* for those requests, and the blanket except below turned that into
    a silent user_id=None on every row written here."""
    try:
        from app.middleware.rbac import get_current_user
        user = get_current_user()
        return user.id if user else None
    except Exception:
        return None


class SharedResourceService:
    """Static facade for tags and shared variable groups."""

    # Supported polymorphic resource types. Kept as a constant so the API and
    # the frontend can advertise the same catalog.
    RESOURCE_TYPES = (
        'application',
        'database',
        'service',
        'wordpress',
        'server',
    )

    # ------------------------------------------------------------------ tags

    @staticmethod
    def _rid(resource_id):
        """Normalize a resource id to the string form stored in the DB."""
        return str(resource_id)

    @staticmethod
    def add_tag(resource_type, resource_id, tag):
        """Attach a tag to a resource. Idempotent — returns the existing or new row."""
        tag = (tag or '').strip()
        if not tag:
            raise ValueError('tag is required')
        rid = SharedResourceService._rid(resource_id)

        existing = ResourceTag.query.filter_by(
            resource_type=resource_type, resource_id=rid, tag=tag
        ).first()
        if existing:
            return existing

        row = ResourceTag(resource_type=resource_type, resource_id=rid, tag=tag)
        db.session.add(row)
        try:
            db.session.commit()
        except Exception:
            # Lost a race with a concurrent insert — fall back to the winner.
            db.session.rollback()
            return ResourceTag.query.filter_by(
                resource_type=resource_type, resource_id=rid, tag=tag
            ).first()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type=resource_type,
            details={'op': 'tag.add', 'resource_id': rid, 'tag': tag},
        )
        return row

    @staticmethod
    def remove_tag(resource_type, resource_id, tag):
        """Detach a tag from a resource. Returns True if a row was deleted."""
        rid = SharedResourceService._rid(resource_id)
        row = ResourceTag.query.filter_by(
            resource_type=resource_type, resource_id=rid, tag=(tag or '').strip()
        ).first()
        if not row:
            return False
        db.session.delete(row)
        db.session.commit()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type=resource_type,
            details={'op': 'tag.remove', 'resource_id': rid,
                     'tag': (tag or '').strip()},
        )
        return True

    @staticmethod
    def list_tags(resource_type, resource_id):
        """List all tags on a resource (ordered by tag name)."""
        rid = SharedResourceService._rid(resource_id)
        return ResourceTag.query.filter_by(
            resource_type=resource_type, resource_id=rid
        ).order_by(ResourceTag.tag.asc()).all()

    @staticmethod
    def list_resources_by_tag(tag, resource_type=None):
        """List every resource carrying a given tag (optionally one type)."""
        query = ResourceTag.query.filter_by(tag=(tag or '').strip())
        if resource_type:
            query = query.filter_by(resource_type=resource_type)
        return query.order_by(
            ResourceTag.resource_type.asc(), ResourceTag.resource_id.asc()
        ).all()

    # --------------------------------------------------------------- groups

    @staticmethod
    def create_group(scope_type, scope_id, name, description=None):
        """Create a new shared variable group."""
        if scope_type not in SharedVariableGroup.VALID_SCOPES:
            raise ValueError(f'invalid scope_type: {scope_type}')
        name = (name or '').strip()
        if not name:
            raise ValueError('name is required')

        group = SharedVariableGroup(
            scope_type=scope_type,
            scope_id=SharedResourceService._rid(scope_id),
            name=name,
            description=(description or None),
        )
        db.session.add(group)
        db.session.commit()
        _audit(
            'resource.create',
            user_id=_current_user_id(),
            target_type='shared_variable_group',
            target_id=group.id,
            details={'op': 'group.create', 'scope_type': scope_type,
                     'scope_id': SharedResourceService._rid(scope_id),
                     'name': group.name},
        )
        return group

    @staticmethod
    def get_group(group_id):
        return SharedVariableGroup.query.get(group_id)

    @staticmethod
    def list_groups(scope_type=None, scope_id=None):
        """List groups, optionally filtered by scope."""
        query = SharedVariableGroup.query
        if scope_type:
            query = query.filter_by(scope_type=scope_type)
        if scope_id is not None:
            query = query.filter_by(scope_id=SharedResourceService._rid(scope_id))
        return query.order_by(SharedVariableGroup.name.asc()).all()

    @staticmethod
    def update_group(group_id, name=None, description=None):
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return None
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError('name cannot be empty')
            group.name = name
        if description is not None:
            group.description = description or None
        db.session.commit()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type='shared_variable_group',
            target_id=group.id,
            details={'op': 'group.update', 'name': group.name},
        )
        return group

    @staticmethod
    def delete_group(group_id):
        """Delete a group (cascades to its variables and attachments)."""
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return False
        name = group.name
        db.session.delete(group)
        db.session.commit()
        _audit(
            'resource.delete',
            user_id=_current_user_id(),
            target_type='shared_variable_group',
            target_id=group_id,
            details={'op': 'group.delete', 'name': name},
        )
        return True

    # --------------------------------------------- variables within a group

    @staticmethod
    def set_variable(group_id, key, value, is_secret=False, target_service=_UNSET):
        """Create or update a variable in a group (upsert by key).

        ``target_service`` scopes the var to one compose service (None = all).
        Left unset on update, the existing target is preserved.
        """
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return None
        key = (key or '').strip()
        if not key:
            raise ValueError('key is required')

        norm_target = None if target_service in ('', _UNSET) else target_service
        var = SharedVariable.query.filter_by(group_id=group_id, key=key).first()
        created = var is None
        if var is None:
            var = SharedVariable(group_id=group_id, key=key, is_secret=bool(is_secret),
                                 target_service=norm_target)
            var.value = value if value is not None else ''
            db.session.add(var)
        else:
            var.value = value if value is not None else ''
            var.is_secret = bool(is_secret)
            if target_service is not _UNSET:
                var.target_service = norm_target
        db.session.commit()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type='shared_variable_group',
            target_id=group_id,
            details={'op': 'variable.create' if created else 'variable.update',
                     'key': key, 'is_secret': bool(is_secret)},
        )
        return var

    @staticmethod
    def update_variable(variable_id, value=None, is_secret=None, target_service=_UNSET):
        var = SharedVariable.query.get(variable_id)
        if not var:
            return None
        if value is not None:
            var.value = value
        if is_secret is not None:
            var.is_secret = bool(is_secret)
        if target_service is not _UNSET:
            var.target_service = None if target_service in ('', None) else target_service
        db.session.commit()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type='shared_variable_group',
            target_id=var.group_id,
            details={'op': 'variable.update', 'key': var.key,
                     'is_secret': bool(var.is_secret)},
        )
        return var

    @staticmethod
    def delete_variable(variable_id):
        var = SharedVariable.query.get(variable_id)
        if not var:
            return False
        group_id, key = var.group_id, var.key
        db.session.delete(var)
        db.session.commit()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type='shared_variable_group',
            target_id=group_id,
            details={'op': 'variable.delete', 'key': key},
        )
        return True

    @staticmethod
    def list_variables(group_id):
        return SharedVariable.query.filter_by(group_id=group_id).order_by(
            SharedVariable.key.asc()
        ).all()

    # ---------------------------------------------------------- attachments

    @staticmethod
    def attach_group(group_id, resource_type, resource_id):
        """Attach a group to a resource. Idempotent."""
        group = SharedVariableGroup.query.get(group_id)
        if not group:
            return None
        rid = SharedResourceService._rid(resource_id)

        existing = SharedVariableGroupAttachment.query.filter_by(
            group_id=group_id, resource_type=resource_type, resource_id=rid
        ).first()
        if existing:
            return existing

        att = SharedVariableGroupAttachment(
            group_id=group_id, resource_type=resource_type, resource_id=rid
        )
        db.session.add(att)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return SharedVariableGroupAttachment.query.filter_by(
                group_id=group_id, resource_type=resource_type, resource_id=rid
            ).first()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type=resource_type,
            details={'op': 'group.attach', 'resource_id': rid,
                     'group_id': group_id},
        )
        return att

    @staticmethod
    def detach_group(group_id, resource_type, resource_id):
        """Detach a group from a resource. Returns True if a row was deleted."""
        rid = SharedResourceService._rid(resource_id)
        att = SharedVariableGroupAttachment.query.filter_by(
            group_id=group_id, resource_type=resource_type, resource_id=rid
        ).first()
        if not att:
            return False
        db.session.delete(att)
        db.session.commit()
        _audit(
            'resource.update',
            user_id=_current_user_id(),
            target_type=resource_type,
            details={'op': 'group.detach', 'resource_id': rid,
                     'group_id': group_id},
        )
        return True

    @staticmethod
    def list_attached_groups(resource_type, resource_id):
        """Return the groups attached to a resource, in attachment order."""
        rid = SharedResourceService._rid(resource_id)
        attachments = SharedVariableGroupAttachment.query.filter_by(
            resource_type=resource_type, resource_id=rid
        ).order_by(SharedVariableGroupAttachment.created_at.asc(),
                   SharedVariableGroupAttachment.id.asc()).all()

        groups = []
        for att in attachments:
            group = SharedVariableGroup.query.get(att.group_id)
            if group:
                groups.append(group)
        return groups

    # ------------------------------------------------------------- resolve

    @staticmethod
    def resolve_variables(resource_type, resource_id, mask_secrets=True):
        """Merge variables from every attached group into one effective set.

        Merge rule: groups are applied in attachment order (oldest first), so a
        key defined in a later-attached group overrides an earlier one
        (**last attachment wins**). Each entry records its source group.
        """
        groups = SharedResourceService.list_attached_groups(resource_type, resource_id)

        resolved = {}
        for group in groups:
            for var in group.variables:
                resolved[var.key] = {
                    'key': var.key,
                    'value': (SharedVariable.to_dict(var, mask_secrets=mask_secrets)
                              ['value']),
                    'is_secret': var.is_secret,
                    'group_id': group.id,
                    'group_name': group.name,
                }

        return [resolved[k] for k in sorted(resolved.keys())]

    # ------------------------------------------------ hierarchical resolve

    # Precedence ladder, lowest → highest. The most specific scope wins on a
    # key collision, with directly-attached groups overriding every inherited
    # scope. ``resource`` is reserved for a resource's own direct variables and
    # always wins last.
    SCOPE_PRECEDENCE = ('workspace', 'project', 'environment', 'direct', 'resource')

    # Matches ``{{group.KEY}}`` references for cross-variable interpolation.
    _REF_RE = re.compile(r'\{\{\s*group\.([A-Za-z0-9_.\-]+)\s*\}\}')

    @staticmethod
    def _interpolate(value, plaintext_by_key, _depth=0):
        """Resolve ``{{group.KEY}}`` references within a plaintext value.

        References point at other resolved keys (the plaintext map). Unknown
        references are left verbatim. Recursion is depth-bounded so a cycle
        (A→B→A) degrades to the raw token instead of looping forever. This only
        runs on already-decrypted plaintext, so secrets are interpolated before
        masking — never the mask glyphs.
        """
        if not isinstance(value, str) or '{{' not in value or _depth > 8:
            return value

        def _sub(match):
            ref_key = match.group(1)
            if ref_key not in plaintext_by_key:
                return match.group(0)  # leave unknown refs untouched
            return SharedResourceService._interpolate(
                plaintext_by_key[ref_key], plaintext_by_key, _depth + 1
            )

        return SharedResourceService._REF_RE.sub(_sub, value)

    @staticmethod
    def resolve_hierarchical_from_layers(layers, direct_vars=None,
                                         mask_secrets=True, interpolate=True,
                                         service=None):
        """Pure merge over pre-fetched layers — the unit-testable core.

        ``layers`` is an ordered iterable of ``(source_scope, groups)`` tuples
        applied lowest → highest precedence; each ``groups`` is an iterable of
        :class:`SharedVariableGroup`. ``direct_vars`` is an optional iterable of
        :class:`SharedVariable` representing the resource's own direct variables,
        which always take top precedence (``source_scope='resource'``).

        A later layer overrides an earlier one on key collisions ("most specific
        wins"). Each resolved entry records the ``source_scope`` it won at plus
        its source group. Secrets are masked in the returned ``value`` when
        ``mask_secrets`` is set, but ``{{group.KEY}}`` interpolation runs on the
        decrypted plaintext first so references resolve correctly regardless of
        masking.
        """
        # First pass (lowest → highest): accumulate the winning entry per key
        # along with its decrypted plaintext, so interpolation can see the
        # final effective set.
        resolved = {}
        plaintext_by_key = {}

        def _targets(var):
            """A var applies when it targets all services (NULL) or, if a service
            is requested, that specific service."""
            tgt = getattr(var, 'target_service', None)
            if service is None or tgt in (None, ''):
                return True
            return tgt == service

        def _apply(source_scope, var, group):
            if not _targets(var):
                return
            plaintext = var.value  # decrypted
            resolved[var.key] = {
                'key': var.key,
                'plaintext': plaintext,
                'is_secret': bool(var.is_secret),
                'target_service': getattr(var, 'target_service', None),
                'group_id': group.id if group is not None else None,
                'group_name': group.name if group is not None else None,
                'source_scope': source_scope,
            }
            plaintext_by_key[var.key] = plaintext

        for source_scope, groups in layers:
            for group in (groups or []):
                for var in group.variables:
                    _apply(source_scope, var, group)

        for var in (direct_vars or []):
            _apply('resource', var, None)

        # Second pass: interpolate references against the final plaintext map,
        # then mask. Two passes keep references stable even when the referenced
        # value is overridden by a more specific scope.
        out = []
        for key in sorted(resolved.keys()):
            entry = resolved[key]
            plaintext = entry.pop('plaintext')
            if interpolate:
                plaintext = SharedResourceService._interpolate(
                    plaintext, plaintext_by_key
                )
            entry['value'] = ('••••••••' if (mask_secrets and entry['is_secret'])
                              else plaintext)
            out.append(entry)
        return out

    @staticmethod
    def resolve_hierarchical(resource_type, resource_id, context=None,
                             mask_secrets=True, interpolate=True, service=None):
        """DB-backed hierarchical resolution for a resource.

        ``context`` may carry ``workspace_id``, ``project_id`` and
        ``environment_id``. Groups scoped to each (by ``scope_type``/``scope_id``)
        form the inherited layers; the resource's directly-attached groups form
        the ``direct`` layer on top. Precedence, lowest → highest:

            workspace < project < environment < direct attachments

        See :meth:`resolve_hierarchical_from_layers` for the pure merge.
        """
        context = context or {}
        layers = []

        def _scoped(scope_type, scope_id):
            if scope_id in (None, ''):
                return []
            return SharedResourceService.list_groups(
                scope_type=scope_type, scope_id=scope_id
            )

        layers.append(('workspace', _scoped('workspace', context.get('workspace_id'))))
        layers.append(('project', _scoped('project', context.get('project_id'))))
        layers.append(('environment',
                       _scoped('environment', context.get('environment_id'))))
        layers.append(('direct',
                       SharedResourceService.list_attached_groups(
                           resource_type, resource_id)))

        return SharedResourceService.resolve_hierarchical_from_layers(
            layers, direct_vars=None, mask_secrets=mask_secrets,
            interpolate=interpolate, service=service,
        )
