from datetime import datetime

from app import db
from app.models.mixins import uuid_pk, TimestampMixin


class Tunnel(TimestampMixin, db.Model):
    """A WireGuard pairing between two ServerKit agents: a public-IP
    "edge" and a NAT'd "private" host. The data plane is kernel WireGuard
    running on the agents; this row is the panel's brokered record of it.

    SECURITY: stores PUBLIC keys only. Private keys are generated on and
    never leave the hosts. See docs/REMOTE_ACCESS_ROADMAP.md.
    """
    __tablename__ = 'tunnels'

    id = uuid_pk()
    name = db.Column(db.String(120))

    # Two FKs to servers → relationships must name foreign_keys explicitly.
    edge_server_id = db.Column(db.String(36), db.ForeignKey('servers.id'), nullable=False, index=True)
    private_server_id = db.Column(db.String(36), db.ForeignKey('servers.id'), nullable=False, index=True)

    interface_name = db.Column(db.String(15), nullable=False)
    subnet = db.Column(db.String(43), nullable=False)        # CIDR, e.g. 10.88.3.0/24
    edge_wg_ip = db.Column(db.String(45), nullable=False)    # 10.88.3.1
    private_wg_ip = db.Column(db.String(45), nullable=False)  # 10.88.3.2
    listen_port = db.Column(db.Integer, default=51820)

    # PUBLIC keys only — never private.
    edge_pubkey = db.Column(db.String(64))
    private_pubkey = db.Column(db.String(64))

    # pending → up → degraded / down / error
    status = db.Column(db.String(20), default='pending', index=True)
    last_handshake_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)


    # Parent-side backrefs so the delete-cascade policy covers both NOT NULL
    # FKs: a tunnel cannot outlive either of its endpoints.
    edge_server = db.relationship(
        'Server', foreign_keys=[edge_server_id],
        backref=db.backref('tunnels_as_edge', lazy='dynamic'))
    private_server = db.relationship(
        'Server', foreign_keys=[private_server_id],
        backref=db.backref('tunnels_as_private', lazy='dynamic'))

    def _prefix(self):
        return self.subnet.split('/')[-1] if self.subnet and '/' in self.subnet else '24'

    def edge_address(self):
        """CIDR address for the edge's interface, e.g. 10.88.3.1/24."""
        return "%s/%s" % (self.edge_wg_ip, self._prefix())

    def private_address(self):
        """CIDR address for the private host's interface, e.g. 10.88.3.2/24."""
        return "%s/%s" % (self.private_wg_ip, self._prefix())

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'edge_server_id': self.edge_server_id,
            'edge_server_name': self.edge_server.name if self.edge_server else None,
            'private_server_id': self.private_server_id,
            'private_server_name': self.private_server.name if self.private_server else None,
            'interface_name': self.interface_name,
            'subnet': self.subnet,
            'edge_wg_ip': self.edge_wg_ip,
            'private_wg_ip': self.private_wg_ip,
            'listen_port': self.listen_port,
            'edge_pubkey': self.edge_pubkey,
            'private_pubkey': self.private_pubkey,
            'status': self.status,
            'last_handshake_at': self.last_handshake_at.isoformat() if self.last_handshake_at else None,
            'last_error': self.last_error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return '<Tunnel %s %s->%s>' % (self.interface_name, self.edge_server_id, self.private_server_id)
