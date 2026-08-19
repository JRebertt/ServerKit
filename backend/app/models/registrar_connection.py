from datetime import datetime
from app import db
from app.models.mixins import EncryptedSecret, TimestampMixin


class RegistrarConnection(TimestampMixin, db.Model):
    """A connected domain-registrar account (GoDaddy, …) used to read the domain
    portfolio: registration status, expiry dates, auto-renew and nameservers.

    This is an *ownership* connection, distinct from a DNS-provider connection
    (DNSProviderConfig) which manages records. Credentials are stored
    Fernet-encrypted via app.utils.crypto, like SourceConnection tokens.
    """
    __tablename__ = 'registrar_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    provider = db.Column(db.String(40), nullable=False)      # 'godaddy'
    name = db.Column(db.String(120), nullable=True)          # user-facing label
    api_key_encrypted = db.Column(db.Text, nullable=True)
    api_secret_encrypted = db.Column(db.Text, nullable=True)
    api_key = EncryptedSecret('api_key_encrypted', legacy_plaintext=True)
    api_secret = EncryptedSecret('api_secret_encrypted', legacy_plaintext=True)
    account_label = db.Column(db.String(180), nullable=True)  # e.g. domain count / shopper id
    config_json = db.Column(db.Text, nullable=True)  # provider-specific non-secret extras (e.g. Namecheap username + client_ip)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    @property
    def config(self):
        import json
        if not self.config_json:
            return {}
        try:
            return json.loads(self.config_json)
        except Exception:
            return {}

    @config.setter
    def config(self, value):
        import json
        self.config_json = json.dumps(value) if value else None

    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'name': self.name or self.provider,
            'account_label': self.account_label,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<RegistrarConnection {self.provider}:{self.id}>'
