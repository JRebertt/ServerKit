import pytest

from app.models.audit_log import AuditLog

# Adds routes to the app fixture with @app.route. Flask refuses setup methods
# once an app has served its first request, so these need a private app rather
# than the session-wide one (plan 64 Phase 1).
pytestmark = pytest.mark.fresh_app


def test_generic_resource_action_constants_are_defined():
    assert AuditLog.ACTION_API_MUTATION == 'api.mutation'
    assert AuditLog.ACTION_RESOURCE_CREATE == 'resource.create'
    assert AuditLog.ACTION_RESOURCE_UPDATE == 'resource.update'
    assert AuditLog.ACTION_RESOURCE_DELETE == 'resource.delete'
    assert AuditLog.ACTION_RESOURCE_INSTALL == 'resource.install'
    assert AuditLog.ACTION_RESOURCE_UNINSTALL == 'resource.uninstall'
    assert AuditLog.ACTION_RESOURCE_ENABLE == 'resource.enable'
    assert AuditLog.ACTION_RESOURCE_DISABLE == 'resource.disable'
    assert AuditLog.ACTION_RESOURCE_ARCHIVE == 'resource.archive'
    assert AuditLog.ACTION_RESOURCE_RESTORE == 'resource.restore'


def test_audit_service_log_commits_without_caller_commit(app):
    from app.services.audit_service import AuditService

    with app.app_context():
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=None,
            target_type='test_resource',
            target_id=123,
            details={'name': 'created'},
        )

        log = AuditLog.query.filter_by(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            target_type='test_resource',
            target_id=123,
        ).one()
        assert log.get_details() == {'name': 'created'}


def test_sensitive_setting_audit_values_are_redacted(app):
    from app.services.audit_service import AuditService

    with app.app_context():
        AuditService.log_settings_change(
            user_id=None,
            key='sso_google_client_secret',
            old_value='old-secret',
            new_value='new-secret',
        )

        log = AuditLog.query.filter_by(action=AuditLog.ACTION_SETTINGS_UPDATE).one()
        assert log.get_details() == {
            'key': 'sso_google_client_secret',
            'old_value': '[redacted]',
            'new_value': '[redacted]',
        }


def test_fallback_audit_logs_unlogged_authenticated_mutation(app, client):
    from flask import jsonify
    from flask_jwt_extended import create_access_token, jwt_required
    from werkzeug.security import generate_password_hash

    from app import db
    from app.models import User

    @app.route('/api/v1/test-audit/items/<int:item_id>', methods=['PUT'])
    @jwt_required()
    def test_audit_update_item(item_id):
        return jsonify({'item_id': item_id, 'ok': True})

    with app.app_context():
        user = User(
            email='audit@test.local',
            username='audituser',
            password_hash=generate_password_hash('testpass'),
            role=User.ROLE_ADMIN,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=user.id)

    response = client.put(
        '/api/v1/test-audit/items/42?filter=recent',
        json={
            'name': 'updated',
            'password': 'plain-text-password',
            'nested': {'api_key': 'secret-key'},
        },
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200

    with app.app_context():
        log = AuditLog.query.filter_by(action=AuditLog.ACTION_API_MUTATION).one()
        details = log.get_details()
        assert log.user_id == user.id
        assert log.target_type == 'test_audit_update_item'
        assert log.target_id == 42
        assert details['method'] == 'PUT'
        assert details['path'] == '/api/v1/test-audit/items/42'
        assert details['status_code'] == 200
        assert details['route_args'] == {'item_id': 42}
        assert details['query'] == {'filter': ['recent']}
        assert details['payload']['name'] == 'updated'
        assert details['payload']['password'] == '[redacted]'
        assert details['payload']['nested']['api_key'] == '[redacted]'


def test_explicit_audit_log_suppresses_fallback(app, client):
    from flask import jsonify
    from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
    from werkzeug.security import generate_password_hash

    from app import db
    from app.models import User
    from app.services.audit_service import AuditService

    @app.route('/api/v1/test-audit/explicit', methods=['POST'])
    @jwt_required()
    def test_audit_explicit():
        user_id = int(get_jwt_identity())
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user_id,
            target_type='explicit_resource',
            target_id=7,
            details={'source': 'route'},
        )
        return jsonify({'ok': True})

    with app.app_context():
        user = User(
            email='explicit-audit@test.local',
            username='explicitaudit',
            password_hash=generate_password_hash('testpass'),
            role=User.ROLE_ADMIN,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=user.id)

    response = client.post(
        '/api/v1/test-audit/explicit',
        json={'name': 'created'},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200

    with app.app_context():
        assert AuditLog.query.filter_by(action=AuditLog.ACTION_API_MUTATION).count() == 0
        log = AuditLog.query.filter_by(action=AuditLog.ACTION_RESOURCE_CREATE).one()
        assert log.target_type == 'explicit_resource'
        assert log.target_id == 7
