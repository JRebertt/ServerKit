from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin


class AuditLog(JsonColumnMixin, db.Model):
    """Audit log for tracking user actions."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    target_type = db.Column(db.String(50), nullable=True)  # user, app, setting, etc.
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)  # JSON string
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 compatible
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationship to user
    user = db.relationship('User', foreign_keys=[user_id])

    # Common action types
    ACTION_LOGIN = 'user.login'
    ACTION_LOGIN_FAILED = 'user.login_failed'
    ACTION_LOGOUT = 'user.logout'
    ACTION_USER_CREATE = 'user.create'
    ACTION_USER_UPDATE = 'user.update'
    ACTION_USER_DELETE = 'user.delete'
    ACTION_USER_DISABLE = 'user.disable'
    ACTION_USER_ENABLE = 'user.enable'
    ACTION_SETTINGS_UPDATE = 'settings.update'
    ACTION_API_MUTATION = 'api.mutation'
    ACTION_RESOURCE_CREATE = 'resource.create'
    ACTION_RESOURCE_UPDATE = 'resource.update'
    ACTION_RESOURCE_DELETE = 'resource.delete'
    ACTION_RESOURCE_INSTALL = 'resource.install'
    ACTION_RESOURCE_UNINSTALL = 'resource.uninstall'
    ACTION_RESOURCE_ENABLE = 'resource.enable'
    ACTION_RESOURCE_DISABLE = 'resource.disable'
    ACTION_RESOURCE_ARCHIVE = 'resource.archive'
    ACTION_RESOURCE_RESTORE = 'resource.restore'
    ACTION_APP_CREATE = 'app.create'
    ACTION_APP_UPDATE = 'app.update'
    ACTION_APP_DELETE = 'app.delete'
    ACTION_APP_START = 'app.start'
    ACTION_APP_STOP = 'app.stop'
    ACTION_APP_RESTART = 'app.restart'
    ACTION_DEPLOY = 'app.deploy'
    ACTION_BACKUP_CREATE = 'backup.create'
    ACTION_BACKUP_RESTORE = 'backup.restore'
    ACTION_RESTORE_POINT_CREATE = 'restore_point.create'
    ACTION_RESTORE_POINT_RESTORE = 'restore_point.restore'
    ACTION_SSO_LOGIN = 'sso.login'
    ACTION_SSO_LOGIN_FAILED = 'sso.login_failed'
    ACTION_SSO_PROVISION = 'sso.provision'
    ACTION_SSO_LINK = 'sso.link'
    ACTION_SSO_UNLINK = 'sso.unlink'
    ACTION_API_KEY_CREATE = 'api_key.create'
    ACTION_API_KEY_REVOKE = 'api_key.revoke'
    ACTION_API_KEY_ROTATE = 'api_key.rotate'
    ACTION_INVITATION_CREATE = 'invitation.create'
    ACTION_INVITATION_REVOKE = 'invitation.revoke'
    ACTION_INVITATION_ACCEPT = 'invitation.accept'
    ACTION_USER_PERMISSIONS_UPDATE = 'user.permissions_update'
    ACTION_USER_PERMISSIONS_RESET = 'user.permissions_reset'

    def get_details(self):
        """Return parsed details JSON."""
        return self._json_read('details')

    def set_details(self, details_dict):
        """Set details from a dictionary."""
        self._json_write('details', details_dict)

    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'details': self.get_details(),
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    @staticmethod
    def log(action, user_id=None, target_type=None, target_id=None,
            details=None, ip_address=None, user_agent=None):
        """Create an audit log entry."""
        log_entry = AuditLog(
            action=action,
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        log_entry.set_details(details)
        db.session.add(log_entry)
        return log_entry

    def __repr__(self):
        return f'<AuditLog {self.action} by user {self.user_id}>'
