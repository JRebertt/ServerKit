"""What this panel tells ServerKit Cloud it manages.

Cloud counts a host once per organisation however many panels report it, and
it can only do that if it can recognise the same machine twice. Reporting an
agent's own id and nothing else is what let one agent under two panels take
two server slots, so every identifier this panel holds goes in the report.
"""
from datetime import datetime, timedelta

from app import db
from app.models.pending_agent import PendingAgent
from app.models.server import Server
from app.services import connect_client


def _enrolment(server_id, *, machine_id, pubkey='ab' * 32):
    """A claimed enrolment, the row an agent's identity actually lives in."""
    now = datetime.utcnow()
    return PendingAgent(
        enrollment_id=f'enr-{server_id}',
        enrollment_secret_hash=PendingAgent.hash_enrollment_secret('s3cret'),
        pubkey=pubkey,
        pubkey_fpr=PendingAgent.fingerprint(pubkey),
        pair_code='ABCD-2345',
        pair_code_expires_at=now + timedelta(minutes=10),
        passphrase_hash=PendingAgent.hash_passphrase('hunter2'),
        machine_id=machine_id,
        expires_at=now + timedelta(hours=1),
        claimed_at=now,
        claimed_server_id=server_id,
    )


def test_a_reported_agent_carries_every_id_this_panel_holds(app):
    with app.app_context():
        server = Server(name='worker-1', hostname='worker-1.example.com',
                        agent_id='agent-hosts-1')
        db.session.add(server)
        db.session.commit()
        db.session.add(_enrolment(server.id, machine_id='mach-worker-1'))
        db.session.commit()

        entry = next(h for h in connect_client._gather_hosts()
                     if h['agent_id'] == 'agent-hosts-1')
        assert entry['machine_id'] == 'mach-worker-1'
        assert entry['fingerprint'] == PendingAgent.fingerprint('ab' * 32).lower()
        assert entry['hostname'] == 'worker-1.example.com'
        assert entry['kind'] == 'agent'


def test_an_agent_with_no_enrolment_row_is_still_reported(app):
    """Honest about what we do not know: the entry goes out with the ids we
    have, rather than being dropped. A missing host is a server Cloud cannot
    show at all."""
    with app.app_context():
        server = Server(name='worker-2', agent_id='agent-hosts-2')
        db.session.add(server)
        db.session.commit()

        entry = next(h for h in connect_client._gather_hosts()
                     if h['agent_id'] == 'agent-hosts-2')
        assert entry['machine_id'] is None
        assert entry['fingerprint'] is None
        assert entry['hostname'] == 'worker-2'
