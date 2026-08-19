"""Linked-panel (ServerKit-to-ServerKit) model.

A single-row config that turns THIS panel into a worker of another
("master") ServerKit panel: instead of installing the standalone Go agent,
the panel runs an embedded agent client (see
app/services/linked_panel_agent.py) that speaks the exact same agent
protocol (HMAC auth + HTTP long-poll transport) to the master.

The master needs zero changes — to it, a linked panel is just another
agent-backed Server row, with the usual scoped/revocable credentials and
Managed/Observed trust levels.
"""

from datetime import datetime

from app import db
from app.models.mixins import EncryptedSecret


class LinkedPanelConfig(db.Model):
    """Credentials + addressing for the master panel this panel links to."""

    __tablename__ = 'linked_panel_config'

    id = db.Column(db.Integer, primary_key=True)
    master_url = db.Column(db.String(255), nullable=False)
    # Agent identity minted by the master during registration.
    agent_id = db.Column(db.String(64), nullable=False)
    api_key_prefix = db.Column(db.String(24), nullable=False)
    api_secret_encrypted = db.Column(db.Text, nullable=False)
    # The Server row id/name the master created for us.
    remote_server_id = db.Column(db.String(36), nullable=False)
    remote_server_name = db.Column(db.String(120), nullable=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # One crypto path (plan 77 C1). legacy_plaintext: rows written before
    # encryption-at-rest read back unchanged until rewritten.
    api_secret = EncryptedSecret('api_secret_encrypted', legacy_plaintext=True)

    def set_api_secret(self, plaintext: str):
        self.api_secret = plaintext

    def get_api_secret(self):
        return self.api_secret

    def to_dict(self):
        return {
            'linked': True,
            'enabled': self.enabled,
            'master_url': self.master_url,
            'agent_id': self.agent_id,
            'api_key_prefix': self.api_key_prefix,
            'remote_server_id': self.remote_server_id,
            'remote_server_name': self.remote_server_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
