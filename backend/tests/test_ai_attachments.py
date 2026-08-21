"""Plan 80 D1 — authorization-first AI attachment resolver contract."""
import json

import pytest

from app.services.ai_attachment_registry import (
    AttachmentValidationError,
    AiAttachmentRegistry,
    MAX_ATTACHMENTS,
    ai_attachment_registry,
    normalize_references,
    register_builtin_attachment_resolvers,
    resolve_attachments,
)


def test_reference_manifest_is_bounded_validated_and_deduplicated():
    refs = normalize_references([
        {'type': 'service', 'id': 7, 'label': 'API'},
        {'type': 'SERVICE', 'id': '7', 'label': 'duplicate'},
    ])
    assert refs == [{'type': 'service', 'id': '7', 'label': 'API'}]

    with pytest.raises(AttachmentValidationError, match='at most'):
        normalize_references([
            {'type': 'service', 'id': str(index)}
            for index in range(MAX_ATTACHMENTS + 1)
        ])
    with pytest.raises(AttachmentValidationError, match='type is invalid'):
        normalize_references([{'type': '../../secret', 'id': '1'}])


def test_resolver_masks_sensitive_keys_and_caps_context():
    registry = AiAttachmentRegistry()
    registry.register('demo', lambda user, resource_id: {
        'label': 'Demo resource',
        'source': 'test fixture',
        'observed_at': '2026-08-21T00:00:00Z',
        'summary': {'status': 'ok', 'password': 'never-send-me'},
    })

    result = resolve_attachments(
        object(), [{'type': 'demo', 'id': 'one'}], registry=registry,
    )
    assert result['manifest'][0]['status'] == 'resolved'
    assert result['context'][0]['summary']['password'] == '[redacted]'
    assert 'never-send-me' not in json.dumps(result)

    registry.register('large', lambda user, resource_id: {
        'label': 'Large', 'source': 'test', 'summary': {'text': 'x' * 13_000},
    })
    capped = resolve_attachments(
        object(), [{'type': 'large', 'id': 'two'}], registry=registry,
    )
    assert capped['context'] == []
    assert capped['manifest'][0]['status'] == 'omitted'
    assert capped['warnings'][0]['status'] == 'omitted'


def test_unknown_attachment_is_audited_without_untrusted_label(app):
    from app import db
    from app.models import AuditLog
    from factories import make_user

    user = make_user(db, 'attachment_auditor')
    secret_label = 'TOKEN=should-never-enter-audit'
    result = resolve_attachments(user, [{
        'type': 'missing.kind', 'id': '42', 'label': secret_label,
    }], registry=AiAttachmentRegistry())

    assert result['manifest'][0]['status'] == 'unknown'
    row = AuditLog.query.filter_by(action='ai.attachment.unknown').one()
    encoded = json.dumps(row.to_dict())
    assert secret_label not in encoded
    assert row.get_details() == {
        'attachment_type': 'missing.kind', 'reason': 'unknown',
    }


def test_service_resolver_rechecks_workspace_access(app, scoping_rbac):
    from app.models import AuditLog, User

    register_builtin_attachment_resolvers()
    owner = User.query.filter_by(username='scope_owner').one()
    viewer = User.query.filter_by(username='scope_viewer').one()
    foreign = User.query.filter_by(username='scope_foreign').one()
    reference = [{'type': 'service', 'id': str(scoping_rbac.app_id)}]

    owner_result = resolve_attachments(owner, reference)
    viewer_result = resolve_attachments(viewer, reference)
    denied_result = resolve_attachments(foreign, reference)

    assert owner_result['context'][0]['summary']['name'] == 'scope-app'
    assert viewer_result['manifest'][0]['status'] == 'resolved'
    assert denied_result['context'] == []
    assert denied_result['manifest'][0]['status'] == 'denied'
    audit = AuditLog.query.filter_by(action='ai.attachment.denied').one()
    assert audit.user_id == foreign.id
    assert audit.get_details() == {
        'attachment_type': 'service', 'reason': 'denied',
    }


def test_plugin_binder_namespaces_attachment_types():
    from app.plugins_sdk.ai import PluginToolBinder
    from app.services.ai_tool_registry import ai_tool_registry

    binder = PluginToolBinder('demo')
    binder.register_attachment_resolver('demo.node', lambda user, resource_id: {
        'label': 'Node', 'source': 'demo', 'summary': {'id': resource_id},
    })
    try:
        assert ai_attachment_registry.get('demo.node') is not None
        with pytest.raises(ValueError, match='namespaced'):
            binder.register_attachment_resolver('other.node', lambda user, resource_id: {})
        ai_tool_registry.unregister_plugin('demo')
        assert ai_attachment_registry.get('demo.node') is None
    finally:
        ai_attachment_registry.unregister_plugin('demo')
