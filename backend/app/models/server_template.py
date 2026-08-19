from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
from app.models.mixins import TimestampMixin
import json


class ServerTemplate(JsonColumnMixin, TimestampMixin, db.Model):
    """Defines expected state for a server — packages, services, firewall rules, users, files."""
    __tablename__ = 'server_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    description = db.Column(db.Text)
    category = db.Column(db.String(64), default='general')  # web, database, mail, custom

    # Template version tracking
    version = db.Column(db.Integer, default=1)

    # Inheritance
    parent_id = db.Column(db.Integer, db.ForeignKey('server_templates.id'), nullable=True)
    parent = db.relationship('ServerTemplate', remote_side=[id], backref='children')

    # Expected state specification
    packages_json = db.Column(db.Text)       # ["nginx", "php8.1-fpm", ...]
    services_json = db.Column(db.Text)       # [{"name": "nginx", "enabled": true, "running": true}, ...]
    firewall_rules_json = db.Column(db.Text) # [{"port": 80, "protocol": "tcp", "action": "allow"}, ...]
    files_json = db.Column(db.Text)          # [{"path": "/etc/nginx/...", "content_hash": "...", "mode": "0644"}, ...]
    users_json = db.Column(db.Text)          # [{"name": "www-data", "groups": ["www-data"]}, ...]
    sysctl_json = db.Column(db.Text)         # [{"key": "net.ipv4.ip_forward", "value": "1"}, ...]

    # Auto-remediation
    auto_remediate = db.Column(db.Boolean, default=False)
    remediation_approval_required = db.Column(db.Boolean, default=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    assignments = db.relationship('ServerTemplateAssignment', backref='template', lazy='dynamic')

    def _get_json(self, field):
        return self._json_read(field, [])

    def _set_json(self, field, value):
        setattr(self, field, json.dumps(value))

    @property
    def packages(self):
        return self._get_json('packages_json')

    @packages.setter
    def packages(self, v):
        self._set_json('packages_json', v)

    @property
    def services(self):
        return self._get_json('services_json')

    @services.setter
    def services(self, v):
        self._set_json('services_json', v)

    @property
    def firewall_rules(self):
        return self._get_json('firewall_rules_json')

    @firewall_rules.setter
    def firewall_rules(self, v):
        self._set_json('firewall_rules_json', v)

    @property
    def files(self):
        return self._get_json('files_json')

    @files.setter
    def files(self, v):
        self._set_json('files_json', v)

    @property
    def users(self):
        return self._get_json('users_json')

    @users.setter
    def users(self, v):
        self._set_json('users_json', v)

    @property
    def sysctl_params(self):
        return self._get_json('sysctl_json')

    @sysctl_params.setter
    def sysctl_params(self, v):
        self._set_json('sysctl_json', v)

    def get_merged_spec(self):
        """Get full spec including inherited fields from parent."""
        if not self.parent:
            return {
                'packages': self.packages,
                'services': self.services,
                'firewall_rules': self.firewall_rules,
                'files': self.files,
                'users': self.users,
                'sysctl_params': self.sysctl_params,
            }
        parent_spec = self.parent.get_merged_spec()
        # Child overrides parent
        for key in ['packages', 'services', 'firewall_rules', 'files', 'users', 'sysctl_params']:
            child_val = getattr(self, key)
            if child_val:
                if key == 'packages':
                    parent_spec[key] = list(set(parent_spec.get(key, []) + child_val))
                else:
                    parent_spec[key] = child_val
        return parent_spec

    def to_dict(self):
        # Compliance is recorded per ASSIGNMENT, but the question asked of a
        # template list is "which template is drifting?" — so each row carries
        # its own tally. Pulling the statuses in one go costs the same single
        # query the bare assignment count used to.
        statuses = [s for (s,) in self.assignments.with_entities(
            ServerTemplateAssignment.status)]
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'version': self.version,
            'parent_id': self.parent_id,
            'parent_name': self.parent.name if self.parent else None,
            'packages': self.packages,
            'services': self.services,
            'firewall_rules': self.firewall_rules,
            'files': self.files,
            'users': self.users,
            'sysctl_params': self.sysctl_params,
            'auto_remediate': self.auto_remediate,
            'remediation_approval_required': self.remediation_approval_required,
            'assignment_count': len(statuses),
            'compliant_count': statuses.count(ServerTemplateAssignment.STATUS_COMPLIANT),
            'drifted_count': statuses.count(ServerTemplateAssignment.STATUS_DRIFTED),
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<ServerTemplate {self.name} v{self.version}>'


class ServerTemplateAssignment(JsonColumnMixin, db.Model):
    """Tracks which template is applied to which server."""
    __tablename__ = 'server_template_assignments'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('server_templates.id'), nullable=False)
    server_id = db.Column(db.Integer, db.ForeignKey('servers.id'), nullable=False)

    # Compliance status
    STATUS_COMPLIANT = 'compliant'
    STATUS_DRIFTED = 'drifted'
    STATUS_CHECKING = 'checking'
    STATUS_REMEDIATING = 'remediating'
    STATUS_UNKNOWN = 'unknown'
    status = db.Column(db.String(32), default=STATUS_UNKNOWN)

    # Drift details
    drift_report_json = db.Column(db.Text)
    last_check_at = db.Column(db.DateTime)
    last_remediation_at = db.Column(db.DateTime)

    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    server = db.relationship('Server', backref=db.backref('template_assignments', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('template_id', 'server_id', name='uq_template_server'),
    )

    @property
    def drift_report(self):
        return self._json_read('drift_report_json')

    @drift_report.setter
    def drift_report(self, v):
        self.drift_report_json = json.dumps(v)

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'template_name': self.template.name if self.template else None,
            'server_id': self.server_id,
            'server_name': self.server.name if self.server else None,
            'status': self.status,
            'drift_report': self.drift_report,
            'last_check_at': self.last_check_at.isoformat() if self.last_check_at else None,
            'last_remediation_at': self.last_remediation_at.isoformat() if self.last_remediation_at else None,
            'applied_at': self.applied_at.isoformat() if self.applied_at else None,
        }

    def __repr__(self):
        return f'<ServerTemplateAssignment template={self.template_id} server={self.server_id}>'
