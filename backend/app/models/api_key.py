"""API Key model for programmatic API access."""
from datetime import datetime
from app import db
from app.models.json_column_mixin import JsonColumnMixin
import hashlib
import secrets


class ApiKey(JsonColumnMixin, db.Model):
    """API key for programmatic access to the ServerKit API."""
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    key_prefix = db.Column(db.String(8), nullable=False)
    key_hash = db.Column(db.String(256), unique=True, nullable=False)
    scopes = db.Column(db.Text, nullable=True)  # JSON array
    tier = db.Column(db.String(20), default='standard')  # standard | elevated | unlimited
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    last_used_ip = db.Column(db.String(45), nullable=True)
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked_at = db.Column(db.DateTime, nullable=True)

    # Parent-side backref so the delete-cascade policy covers the NOT NULL FK:
    # a user's API keys die with the account.
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('api_keys', lazy='dynamic'))

    TIER_STANDARD = 'standard'
    TIER_ELEVATED = 'elevated'
    TIER_UNLIMITED = 'unlimited'
    VALID_TIERS = [TIER_STANDARD, TIER_ELEVATED, TIER_UNLIMITED]

    @staticmethod
    def generate_key():
        """Generate a new API key. Returns (raw_key, prefix, hash)."""
        raw = 'sk_' + secrets.token_hex(20)
        prefix = raw[:8]
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        return raw, prefix, key_hash

    @staticmethod
    def hash_key(raw_key):
        """Hash a raw API key."""
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def get_scopes(self):
        """Return parsed scopes list."""
        return self._json_read('scopes', [])

    def set_scopes(self, scopes_list):
        """Set scopes from a list."""
        self._json_write('scopes', scopes_list)

    def is_expired(self):
        """Check if the key has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def is_valid(self):
        """Check if the key is active and not expired or revoked."""
        return self.is_active and not self.is_expired() and self.revoked_at is None

    def has_scope(self, required_scope):
        """Check if this key has the required scope."""
        scopes = self.get_scopes()
        if not scopes or '*' in scopes:
            return True
        if required_scope in scopes:
            return True
        # Check wildcard resource match (e.g. 'apps:*' matches 'apps:read')
        resource = required_scope.split(':')[0] if ':' in required_scope else required_scope
        if f'{resource}:*' in scopes:
            return True
        return False

    def record_usage(self, ip_address=None):
        """Record a usage of this key."""
        self.last_used_at = datetime.utcnow()
        self.usage_count = (self.usage_count or 0) + 1
        if ip_address:
            self.last_used_ip = ip_address

    def to_dict(self):
        """Serialize key info (never expose hash)."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'key_prefix': self.key_prefix,
            'scopes': self.get_scopes(),
            'tier': self.tier,
            'is_active': self.is_active,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'last_used_ip': self.last_used_ip,
            'usage_count': self.usage_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
        }

    def __repr__(self):
        return f'<ApiKey {self.key_prefix}... ({self.name})>'
