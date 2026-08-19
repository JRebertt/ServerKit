"""Tests for Dynamic DNS — token-authenticated A/AAAA record updates."""
import pytest

from app.exceptions import AuthenticationError, ValidationError

from app import db
from app.models.dns_zone import DNSZone, DNSRecord
from app.services.ddns_service import DdnsService


def _manual_zone(domain='example.com'):
    zone = DNSZone(domain=domain, provider='manual')
    db.session.add(zone)
    db.session.commit()
    return zone


class TestDdnsService:
    def test_update_creates_then_reports_unchanged_then_updates(self, app):
        zone = _manual_zone()
        host = DdnsService.create_host({'zone_id': zone.id, 'record_name': 'home'})

        status, h = DdnsService.update_ip(host.token, '203.0.113.7')
        assert status == 'updated'
        rec = DNSRecord.query.filter_by(zone_id=zone.id, record_type='A', name='home').first()
        assert rec is not None and rec.content == '203.0.113.7'
        assert h.last_ip == '203.0.113.7'

        # Same IP → no-op.
        status2, _ = DdnsService.update_ip(host.token, '203.0.113.7')
        assert status2 == 'unchanged'

        # New IP → updated in place, never a duplicate record.
        status3, _ = DdnsService.update_ip(host.token, '203.0.113.9')
        assert status3 == 'updated'
        recs = DNSRecord.query.filter_by(zone_id=zone.id, record_type='A', name='home').all()
        assert len(recs) == 1 and recs[0].content == '203.0.113.9'

    def test_ipv6_uses_aaaa_record(self, app):
        zone = _manual_zone('v6.example.com')
        host = DdnsService.create_host({'zone_id': zone.id, 'record_name': '@'})
        status, _ = DdnsService.update_ip(host.token, '2001:db8::1')
        assert status == 'updated'
        assert DNSRecord.query.filter_by(zone_id=zone.id, record_type='AAAA', name='@').first()

    def test_invalid_token_rejected(self, app):
        with pytest.raises(AuthenticationError):
            DdnsService.update_ip('nope', '203.0.113.1')

    def test_invalid_ip_rejected(self, app):
        zone = _manual_zone('bad.example.com')
        host = DdnsService.create_host({'zone_id': zone.id})
        with pytest.raises(ValidationError):
            DdnsService.update_ip(host.token, 'not-an-ip')

    def test_disabled_host_rejected(self, app):
        zone = _manual_zone('off.example.com')
        host = DdnsService.create_host({'zone_id': zone.id, 'enabled': False})
        with pytest.raises(AuthenticationError):
            DdnsService.update_ip(host.token, '203.0.113.1')


class TestDdnsApi:
    def test_create_returns_token_but_list_masks_it(self, client, auth_headers, app):
        zone = _manual_zone('api.example.com')
        resp = client.post('/api/v1/ddns/hosts',
                           json={'zone_id': zone.id, 'record_name': 'home'},
                           headers=auth_headers)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['token'] and body['hostname'] == 'home.api.example.com'

        listed = client.get('/api/v1/ddns/hosts', headers=auth_headers).get_json()
        assert listed['hosts'] and 'token' not in listed['hosts'][0]

    def test_public_update_endpoint(self, client, auth_headers, app):
        zone = _manual_zone('pub.example.com')
        created = client.post('/api/v1/ddns/hosts',
                              json={'zone_id': zone.id, 'record_name': 'nas'},
                              headers=auth_headers).get_json()
        token = created['token']

        ok = client.get(f'/api/v1/ddns/update?token={token}&ip=203.0.113.50')
        assert ok.status_code == 200
        assert ok.get_json()['status'] == 'updated'
        assert ok.get_json()['hostname'] == 'nas.pub.example.com'

        # Wrong token → 401; bad IP → 400.
        assert client.get('/api/v1/ddns/update?token=wrong&ip=203.0.113.1').status_code == 401
        assert client.get(f'/api/v1/ddns/update?token={token}&ip=xxx').status_code == 400

    def test_create_requires_auth(self, client, app):
        assert client.post('/api/v1/ddns/hosts', json={'zone_id': 1}).status_code == 401
