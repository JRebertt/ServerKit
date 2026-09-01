"""Per-application WAF policy (ModSecurity v3 + OWASP Core Rule Set).

One row per :class:`~app.models.application.Application`. Stores the desired
engine mode, OWASP CRS paranoia level / anomaly threshold, and the list of CRS
rule IDs to disable. The :class:`~app.services.waf_service.WafService` renders
these into ModSecurity rules and an nginx snippet.
"""
from datetime import datetime
import json

from app import db
from app.models.json_column_mixin import JsonColumnMixin


class WafPolicy(JsonColumnMixin, db.Model):
    """ModSecurity / OWASP CRS configuration for a single application."""
    __tablename__ = 'waf_policies'

    # Allowed engine modes. 'off' disables the WAF, 'detect' logs only
    # (DetectionOnly), 'block' enforces (SecRuleEngine On).
    MODES = ('off', 'detect', 'block')

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey('applications.id'),
        nullable=False,
        unique=True,
        index=True,
    )
    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK.
    application = db.relationship('Application',
                                  backref=db.backref('waf_policy', uselist=False))

    mode = db.Column(db.String(10), default='off', nullable=False)
    paranoia_level = db.Column(db.Integer, default=1, nullable=False)  # 1-4
    anomaly_threshold = db.Column(db.Integer, default=5, nullable=False)

    # JSON-encoded list of OWASP CRS rule IDs to disable (SecRuleRemoveById).
    disabled_rule_ids = db.Column(db.Text, nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def disabled_rules(self):
        """Return the disabled rule IDs as a list (empty list when unset)."""
        return self._json_read('disabled_rule_ids', [], expect=list)

    @disabled_rules.setter
    def disabled_rules(self, value):
        if not value:
            self.disabled_rule_ids = None
        else:
            # Normalise to a list of strings, dropping blanks.
            self.disabled_rule_ids = json.dumps(
                [str(v).strip() for v in value if str(v).strip()]
            )

    def to_dict(self):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'mode': self.mode,
            'paranoia_level': self.paranoia_level,
            'anomaly_threshold': self.anomaly_threshold,
            'disabled_rule_ids': self.disabled_rules,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<WafPolicy app={self.application_id} mode={self.mode}>'
