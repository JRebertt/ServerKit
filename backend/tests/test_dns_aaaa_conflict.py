"""Plan 73 item 7 — a stray AAAA record was invisible to both DNS surfaces.

Let's Encrypt prefers IPv6 whenever a AAAA record exists. So a domain whose A
record points at this server perfectly still fails HTTP-01 issuance if its
AAAA points somewhere else — and that is the shape that looked healthy
everywhere:

* ``DoctorService._dns_check_one`` returned ok as soon as the server IP was
  *among* the resolved addresses, so the extra IPv6 answer never registered.
* ``verify_domain`` used ``socket.gethostbyname``, which is IPv4-only and
  cannot see a AAAA record at all.

Both now resolve A and AAAA and name the conflict.
"""
import socket
from collections import namedtuple
from unittest.mock import patch

import pytest

from app.services import doctor_service
from app.services.doctor_service import DoctorService, _aaaa_conflicts


SERVER_V4 = '203.0.113.10'
SERVER_V6 = '2001:db8:cafe::10'
STRAY_V6 = '2001:db8:dead::99'

# Shape of a psutil.net_if_addrs() entry, to the extent this code reads it.
_snic = namedtuple('snicaddr', 'family address')


# --------------------------------------------------------------------------- #
# _aaaa_conflicts
# --------------------------------------------------------------------------- #
class TestAaaaConflicts:

    def test_no_ipv6_no_conflict(self):
        assert _aaaa_conflicts([SERVER_V4], SERVER_V4, set()) == []

    def test_stray_ipv6_is_a_conflict(self):
        assert _aaaa_conflicts([SERVER_V4, STRAY_V6], SERVER_V4, set()) == [STRAY_V6]

    def test_ipv6_belonging_to_this_host_is_not_a_conflict(self):
        conflicts = _aaaa_conflicts([SERVER_V4, SERVER_V6], SERVER_V4, {SERVER_V6})
        assert conflicts == []

    def test_the_configured_server_ip_is_never_a_conflict(self):
        """A box whose public IP *is* the v6 address, with no local interface
        detection available."""
        assert _aaaa_conflicts([SERVER_V6], SERVER_V6, set()) == []

    def test_comparison_is_by_value_not_by_spelling(self):
        """2001:db8:0:0:0:0:0:1 and 2001:db8::1 are the same address; a string
        compare would have called the expanded form a stray."""
        expanded = '2001:0db8:0000:0000:0000:0000:0000:0001'
        conflicts = _aaaa_conflicts([expanded], SERVER_V4, {'2001:db8::1'})
        assert conflicts == []

    def test_garbage_entries_are_ignored(self):
        assert _aaaa_conflicts(['not-an-ip', SERVER_V4], SERVER_V4, set()) == []


class TestLocalHostIps:
    """_local_host_ips reads the host's own interfaces through psutil, which
    doctor_service imports lazily inside the function."""

    def test_addresses_are_normalized_and_zone_ids_stripped(self):
        """psutil reports link-local addresses as fe80::1%eth0, and expanded
        IPv6 forms would not string-compare against a DNS answer."""
        addrs = {
            'eth0': [
                _snic(socket.AF_INET, SERVER_V4),
                _snic(socket.AF_INET6, '2001:0db8:cafe:0000:0000:0000:0000:0010'),
                _snic(socket.AF_INET6, 'fe80::1%eth0'),
            ],
        }
        with patch('psutil.net_if_addrs', return_value=addrs):
            found = doctor_service._local_host_ips()

        assert SERVER_V4 in found
        assert SERVER_V6 in found      # compressed, not the expanded spelling
        assert 'fe80::1' in found      # zone id gone

    def test_non_ip_families_are_skipped(self):
        """MAC addresses come back from the same call (AF_LINK/AF_PACKET)."""
        addrs = {'eth0': [_snic(-1, '00:11:22:33:44:55'),
                          _snic(socket.AF_INET, SERVER_V4)]}
        with patch('psutil.net_if_addrs', return_value=addrs):
            assert doctor_service._local_host_ips() == {SERVER_V4}

    def test_detection_failure_returns_empty_rather_than_raising(self):
        """Best-effort: a psutil failure must not break the whole sweep."""
        with patch('psutil.net_if_addrs', side_effect=Exception('no psutil for you')):
            assert doctor_service._local_host_ips() == set()

    def test_a_matching_local_address_clears_the_conflict(self):
        """End to end through the real enumeration, not a hand-passed set."""
        addrs = {'eth0': [_snic(socket.AF_INET6, SERVER_V6)]}
        with patch('psutil.net_if_addrs', return_value=addrs):
            assert _aaaa_conflicts([SERVER_V4, SERVER_V6], SERVER_V4) == []
            assert _aaaa_conflicts([SERVER_V4, STRAY_V6], SERVER_V4) == [STRAY_V6]


# --------------------------------------------------------------------------- #
# doctor: the sweep warns instead of reporting ok
# --------------------------------------------------------------------------- #
class TestDoctorSweepSeesTheConflict:

    def _check_one(self, resolved, local_ips=frozenset()):
        with patch('app.services.doctor_service._resolve_host_ips',
                   return_value=list(resolved)):
            return DoctorService._dns_check_one(
                'site.example', SERVER_V4, False, set(local_ips))

    def test_correct_a_record_with_a_stray_aaaa_warns(self):
        """The regression case: the A record is right, so the old check said
        ok and stopped looking."""
        check = self._check_one([SERVER_V4, STRAY_V6])

        assert check['status'] == 'warn'
        assert STRAY_V6 in check['detail']
        assert 'AAAA' in check['detail']
        # The text has to tell the operator what to actually do.
        assert 'Remove the AAAA record' in check['detail']

    def test_correct_a_and_correct_aaaa_is_ok(self):
        check = self._check_one([SERVER_V4, SERVER_V6], local_ips={SERVER_V6})

        assert check['status'] == 'ok'

    def test_ipv4_only_domain_is_still_ok(self):
        assert self._check_one([SERVER_V4])['status'] == 'ok'

    def test_a_record_pointing_elsewhere_keeps_its_own_warning(self):
        """The AAAA logic must not swallow the pre-existing wrong-A-record
        message — that branch is only reached when the A record is right."""
        check = self._check_one(['198.51.100.7'])

        assert check['status'] == 'warn'
        assert 'not this server' in check['detail']

    def test_interfaces_are_enumerated_once_per_sweep(self, monkeypatch):
        """_local_host_ips shells out through psutil; doing it per domain in a
        multi-site sweep was pure waste."""
        calls = []
        monkeypatch.setattr(doctor_service, '_local_host_ips',
                            lambda: calls.append(1) or {SERVER_V6})
        # Real-looking public names: `.example` is in the doctor's
        # skip-suffix list and would be filtered out before any lookup.
        monkeypatch.setattr(DoctorService, '_site_domains',
                            classmethod(lambda cls: ['a.example.com', 'b.example.com',
                                                     'c.example.com']))
        monkeypatch.setattr(DoctorService, '_dns_provider_available',
                            classmethod(lambda cls: False))

        with patch('app.services.site_domain_service.SiteDomainService.server_ip',
                   return_value=SERVER_V4), \
                patch('app.services.doctor_service._resolve_host_ips',
                      return_value=[SERVER_V4]):
            DoctorService._dns_checks()

        assert len(calls) == 1


# --------------------------------------------------------------------------- #
# verify_domain: the API surface
# --------------------------------------------------------------------------- #
@pytest.fixture
def domain_row(app):
    from werkzeug.security import generate_password_hash
    from app import db
    from app.models import User
    from app.models.application import Application
    from app.models.domain import Domain

    user = User(email='aaaa@test.local', username='aaaauser',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.flush()
    site = Application(name='aaaasite', app_type='static', user_id=user.id)
    db.session.add(site)
    db.session.flush()
    row = Domain(name='site.example', application_id=site.id)
    db.session.add(row)
    db.session.commit()
    return row, user


@pytest.fixture
def auth(app, domain_row):
    from flask_jwt_extended import create_access_token
    _, user = domain_row
    with app.app_context():
        return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


def _verify(client, auth, domain, resolved, local_ips=frozenset()):
    with patch('app.services.doctor_service._resolve_host_ips',
               return_value=list(resolved)), \
            patch('app.services.doctor_service._local_host_ips',
                  return_value=set(local_ips)), \
            patch('app.services.site_domain_service.SiteDomainService.server_ip',
                  return_value=SERVER_V4):
        return client.get(f'/api/v1/domains/{domain.id}/verify', headers=auth)


class TestVerifyDomainReportsTheConflict:

    def test_stray_aaaa_is_reported_with_actionable_text(self, client, auth, domain_row):
        domain, _ = domain_row
        resp = _verify(client, auth, domain, [SERVER_V4, STRAY_V6])
        body = resp.get_json()

        assert resp.status_code == 200
        assert body['aaaa_conflict'] == [STRAY_V6]
        assert STRAY_V6 in body['warning']
        assert 'Remove the AAAA record' in body['warning']
        assert body['ip_addresses'] == [SERVER_V4, STRAY_V6]

    def test_clean_domain_has_no_warning(self, client, auth, domain_row):
        domain, _ = domain_row
        body = _verify(client, auth, domain, [SERVER_V4]).get_json()

        assert body['verified'] is True
        assert 'warning' not in body
        assert 'aaaa_conflict' not in body

    def test_matching_aaaa_has_no_warning(self, client, auth, domain_row):
        domain, _ = domain_row
        body = _verify(client, auth, domain, [SERVER_V4, SERVER_V6],
                       local_ips={SERVER_V6}).get_json()

        assert body['verified'] is True
        assert 'warning' not in body

    def test_ip_address_stays_the_ipv4_one_for_existing_callers(self, client, auth, domain_row):
        """The field predates ip_addresses and the UI prints it verbatim; a
        dual-stack domain must not start reporting its IPv6 address there."""
        domain, _ = domain_row
        body = _verify(client, auth, domain, [SERVER_V6, SERVER_V4],
                       local_ips={SERVER_V6}).get_json()

        assert body['ip_address'] == SERVER_V4

    def test_unresolvable_domain_still_reports_the_old_shape(self, client, auth, domain_row):
        domain, _ = domain_row
        with patch('app.services.doctor_service._resolve_host_ips',
                   side_effect=OSError('nope')):
            resp = client.get(f'/api/v1/domains/{domain.id}/verify', headers=auth)
        body = resp.get_json()

        assert body['verified'] is False
        assert body['error'] == 'Domain could not be resolved'
