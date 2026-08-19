"""
PendingAgent model — tracks agents that have enrolled for short-code pairing
but have not yet been claimed by an operator.

A PendingAgent stores:
  - The agent's Ed25519 public key (for identity / TOFU verification)
  - A short, rotating pair code (shown by the agent's tray UI)
  - A bcrypt hash of the operator-set passphrase
  - The agent's stable machine_id (so re-pairs on the same host are detectable)

When an operator submits (code, passphrase) via /pairing/claim, the entry is
matched, real Server credentials are minted, and `claimed_server_id` is set.
"""

import uuid
import hashlib
from datetime import datetime, timedelta

import bcrypt

from app import db
from app.models.mixins import EncryptedSecret


# Pair code uses Crockford-ish base32 minus ambiguous chars (0/O, 1/I/L)
PAIR_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
PAIR_CODE_LENGTH = 6
DEFAULT_PAIR_CODE_TTL = timedelta(minutes=5)
DEFAULT_ENROLLMENT_TTL = timedelta(hours=24)


class PendingAgent(db.Model):
    """An agent that has enrolled and is waiting to be claimed."""

    __tablename__ = 'pending_agents'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Opaque token the agent uses to authenticate poll/refresh calls.
    # Stored hashed; the agent receives the plaintext value once on enroll.
    enrollment_id = db.Column(db.String(64), unique=True, index=True, nullable=False)
    enrollment_secret_hash = db.Column(db.String(256), nullable=False)

    # Agent identity
    pubkey = db.Column(db.String(128), nullable=False)         # Ed25519 hex (64 chars)
    pubkey_fpr = db.Column(db.String(32), nullable=False, index=True)  # SHA-256 first 16 hex chars

    # Pair code (visible to operator)
    pair_code = db.Column(db.String(16), index=True, nullable=False)
    pair_code_expires_at = db.Column(db.DateTime, nullable=False)
    pair_code_frozen = db.Column(db.Boolean, default=False, nullable=False)

    # Passphrase (set by user on agent host; never sent to panel in plaintext)
    passphrase_hash = db.Column(db.String(256), nullable=False)

    # Brute-force lockout (seconds-resolution timestamp)
    lockout_until = db.Column(db.DateTime, nullable=True)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)

    # Host identity
    machine_id = db.Column(db.String(128), index=True, nullable=True)
    system_info = db.Column(db.JSON, default=dict)

    # Lifecycle
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    claimed_at = db.Column(db.DateTime, nullable=True)
    claimed_server_id = db.Column(db.String(36), db.ForeignKey('servers.id'), nullable=True)

    # When claimed, we stash credentials here briefly (Fernet-encrypted) so the
    # next /poll call can deliver them to the agent. Cleared after retrieval.
    claim_payload_encrypted = db.Column(db.Text, nullable=True)
    claim_payload = EncryptedSecret('claim_payload_encrypted')

    claimed_server = db.relationship('Server', foreign_keys=[claimed_server_id])

    @staticmethod
    def fingerprint(pubkey_hex: str) -> str:
        """Return a short, human-friendly fingerprint of a public key."""
        digest = hashlib.sha256(pubkey_hex.encode('ascii')).hexdigest()
        return digest[:16].upper()

    @staticmethod
    def hash_passphrase(passphrase: str) -> str:
        return bcrypt.hashpw(passphrase.encode('utf-8'), bcrypt.gensalt()).decode('ascii')

    def verify_passphrase(self, passphrase: str) -> bool:
        try:
            return bcrypt.checkpw(passphrase.encode('utf-8'), self.passphrase_hash.encode('ascii'))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def hash_enrollment_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode('utf-8')).hexdigest()

    def verify_enrollment_secret(self, secret: str) -> bool:
        if not secret or not self.enrollment_secret_hash:
            return False
        return self.hash_enrollment_secret(secret) == self.enrollment_secret_hash

    def is_pair_code_valid(self) -> bool:
        return self.pair_code_expires_at and datetime.utcnow() < self.pair_code_expires_at

    def is_locked_out(self) -> bool:
        return self.lockout_until is not None and datetime.utcnow() < self.lockout_until

    def is_expired(self) -> bool:
        return self.expires_at and datetime.utcnow() >= self.expires_at

    def is_claimed(self) -> bool:
        return self.claimed_at is not None

    def to_dict(self, include_secrets: bool = False) -> dict:
        result = {
            'id': self.id,
            'pubkey_fpr': self.pubkey_fpr,
            'pair_code': self.pair_code if include_secrets else None,
            'pair_code_expires_at': self.pair_code_expires_at.isoformat() if self.pair_code_expires_at else None,
            'pair_code_frozen': self.pair_code_frozen,
            'machine_id': self.machine_id,
            'system_info': self.system_info or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'claimed': self.is_claimed(),
        }
        return result

    def __repr__(self):
        return f'<PendingAgent {self.id} fpr={self.pubkey_fpr}>'
