"""Probe honesty for SSL/certificate checks — a failed probe must not read as a
healthy one.

Plan 75 §A5. The convention: a probe answers a value when it determined one;
None/unknown when it could NOT determine one — never the negative. The bugs
fixed here all collapsed "the check failed" into a positive-looking answer:

- Doctor's cert check queried ``Domain.ssl_expires_at``, a column nothing in
  production writes, so it returned ok "No certificates tracked." forever —
  a dead column hardwired to green.
- ``SSLService.check_expiry`` treated any ``openssl x509 -checkend`` non-zero
  exit as "expiring soon", but the same exit code means "unreadable PEM", so
  a failed probe produced a phantom "needs renewal" — and the exception path
  (no ``expiring_soon`` key) silently vanished from the status endpoint's
  expiring list, rendering a failed check as "not expiring".
- The monitor cert probe bumped ``cert_checked_at`` on failure but left the
  OLD ``cert_expires_at`` in place, so the UI rendered a fresh green
  "valid / N days" chip from weeks-old data.
- ``get_expiry_alerts`` dropped unprobeable certs from the alert list —
  "not expiring" by omission.
- ``get_cert_health`` started from valid: False / grade: 'F' and on exception
  only added an error, so a DNS timeout rendered as a determined grade F.
- ``list_certificates`` swallowed a certbot failure and returned possibly
  empty, so /ssl/status reported "0 certificates, nothing expiring" with
  HTTP 200 when the inventory probe itself had failed.

The rule, as in test_backup_verify_honesty.py: **ok must be positively
earned.**
"""

import socket
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app import db
from app.services.advanced_ssl_service import AdvancedSSLService
from app.services.doctor_service import DoctorService
from app.services.monitor_service import MonitorService
from app.services.ssl_service import SSLService


def _completed(returncode=0, stdout='', stderr=''):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------- #
# 1. Doctor: no collected expiry data is "not monitored", never ok
# --------------------------------------------------------------------------- #

def test_doctor_empty_cert_data_is_warn_not_ok(app):
    """The bug, stated directly: a dead column hardwired to green."""
    check = DoctorService._cert_check()

    assert check['status'] == 'warn'
    assert 'not being monitored' in check['detail']


def test_doctor_cert_check_ok_is_still_earned(app):
    """A real future-dated expiry row still earns ok."""
    from app.models import Application
    from app.models.domain import Domain

    app_row = Application(name='cert-site', app_type='static',
                          status='running', root_path='/srv/cert-site',
                          user_id=1)
    db.session.add(app_row)
    db.session.flush()
    db.session.add(Domain(name='cert.example.com', application_id=app_row.id,
                          ssl_expires_at=datetime.utcnow() + timedelta(days=60)))
    db.session.commit()

    check = DoctorService._cert_check()

    assert check['status'] == 'ok'
    assert 'cert.example.com' in check['detail']


# --------------------------------------------------------------------------- #
# 2. check_expiry: an unreadable cert is unknown, not "expiring / renew now"
# --------------------------------------------------------------------------- #

def test_checkend_failure_without_a_date_is_an_error_not_expiring(app):
    """-checkend exits non-zero for BOTH "expires soon" and "unreadable PEM".
    With no parsed expiry date the probe determined nothing."""
    calls = {
        'checkend': _completed(1, stderr='unable to load certificate'),
        'enddate': _completed(1, stderr='error opening certificate file'),
    }

    def fake_run(cmd, **kwargs):
        if '-checkend' in cmd:
            return calls['checkend']
        if '-enddate' in cmd:
            return calls['enddate']
        raise AssertionError(f'unexpected command: {cmd}')

    with patch('app.services.ssl_service.run_privileged', side_effect=fake_run):
        result = SSLService.check_expiry('broken.example.com')

    assert result['domain'] == 'broken.example.com'
    assert 'error' in result
    assert 'unable to load certificate' in result['error']
    assert 'expiring_soon' not in result
    assert 'needs_renewal' not in result


def test_checkend_failure_with_a_date_is_really_expiring(app):
    """The honest positive path: non-zero -checkend plus a parsed enddate
    means the cert genuinely expires within the window."""

    def fake_run(cmd, **kwargs):
        if '-checkend' in cmd:
            return _completed(1)
        if '-enddate' in cmd:
            return _completed(0, stdout='notAfter=Sep  1 00:00:00 2026 GMT\n')
        raise AssertionError(f'unexpected command: {cmd}')

    with patch('app.services.ssl_service.run_privileged', side_effect=fake_run):
        result = SSLService.check_expiry('expiring.example.com')

    assert result['expiring_soon'] is True
    assert result['needs_renewal'] is True
    assert result['expiry_date']


def test_ssl_status_surfaces_check_errors(app, client, auth_headers):
    """A cert whose check failed must appear in check_errors, not silently
    drop out of expiring_soon and read as "not expiring"."""
    certbot_out = (
        'Certificate Name: broken.example.com\n'
        '    Domains: broken.example.com\n'
        '    Expiry Date: 2026-09-01 00:00:00+00:00 (VALID: 14 days)\n'
        '    Certificate Path: /etc/letsencrypt/live/broken.example.com/fullchain.pem\n'
        '    Private Key Path: /etc/letsencrypt/live/broken.example.com/privkey.pem\n'
    )

    def fake_run(cmd, **kwargs):
        if 'certificates' in cmd:
            return _completed(0, stdout=certbot_out)
        if '-checkend' in cmd:
            return _completed(1, stderr='unable to load certificate')
        if '-enddate' in cmd:
            return _completed(1, stderr='error opening certificate file')
        raise AssertionError(f'unexpected command: {cmd}')

    with patch('app.services.ssl_service.run_privileged', side_effect=fake_run), \
            patch.object(SSLService, 'is_certbot_installed', return_value=True):
        resp = client.get('/api/v1/ssl/status', headers=auth_headers)

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['expiring_soon'] == []
    assert payload['check_errors'] == [
        {'name': 'broken.example.com', 'error': 'unable to load certificate'}]


# --------------------------------------------------------------------------- #
# 4. Monitor cert probe: a failed refresh clears the stale expiry
# --------------------------------------------------------------------------- #

def _https_monitor(app):
    return MonitorService.create({
        'name': 'TLS watch',
        'check_type': 'http',
        'check_target': 'https://stale.example.test/',
        'check_interval': 60,
        'retries': 0,
    })


def test_failed_cert_probe_clears_stale_expiry(app):
    """The throttle stamp (cert_checked_at) stays; the stale cert_expires_at
    must not — otherwise the UI renders a fresh green chip from old data."""
    monitor = _https_monitor(app)
    monitor.cert_expires_at = datetime.utcnow() + timedelta(days=10)
    monitor.cert_checked_at = None
    db.session.commit()

    result = {'status': 'up'}
    with patch.object(MonitorService, '_probe_certificate',
                      side_effect=OSError('connection refused')):
        MonitorService._maybe_attach_certificate(monitor, result)
    assert result['cert_checked_at'] is not None  # throttle stamp kept
    assert result['cert_expires_at'] is None

    MonitorService._record(monitor, result)
    db.session.refresh(monitor)
    assert monitor.cert_expires_at is None


def test_dateless_cert_probe_clears_stale_expiry(app):
    """An unparseable notAfter (probe returns no expiry) is the same
    stale-retention bug; any None result clears."""
    monitor = _https_monitor(app)
    monitor.cert_expires_at = datetime.utcnow() + timedelta(days=10)
    db.session.commit()

    result = {'status': 'up'}
    with patch.object(MonitorService, '_probe_certificate',
                      return_value={'cert_issuer': "Let's Encrypt"}):
        MonitorService._maybe_attach_certificate(monitor, result)
    MonitorService._record(monitor, result)
    db.session.refresh(monitor)
    assert monitor.cert_expires_at is None
    assert monitor.cert_issuer == "Let's Encrypt"


def test_successful_cert_probe_repopulates_expiry(app):
    """Clearing on failure must not break the normal refresh path."""
    monitor = _https_monitor(app)
    expires = datetime.utcnow() + timedelta(days=40)

    result = {'status': 'up'}
    with patch.object(MonitorService, '_probe_certificate',
                      return_value={'cert_issuer': "Let's Encrypt",
                                    'cert_expires_at': expires}):
        MonitorService._maybe_attach_certificate(monitor, result)
    MonitorService._record(monitor, result)
    db.session.refresh(monitor)
    assert monitor.cert_expires_at == expires


# --------------------------------------------------------------------------- #
# 5. Expiry alerts: an unprobeable cert is an unknown-severity entry
# --------------------------------------------------------------------------- #

def test_expiry_alerts_surface_unprobeable_certs_as_unknown(app):
    paths = ['/etc/letsencrypt/live/gone.example/cert.pem',
             '/etc/letsencrypt/live/fine.example/cert.pem']

    def fake_run(cmd, **kwargs):
        if 'gone.example' in cmd[-1]:
            raise OSError('openssl: No such file or directory')
        return {'returncode': 0, 'stdout': 'notAfter=Sep  1 00:00:00 2026 GMT\n',
                'stderr': ''}

    with patch('glob.glob', return_value=paths), \
            patch('app.services.advanced_ssl_service.run_unprivileged',
                  side_effect=fake_run):
        alerts = AdvancedSSLService.get_expiry_alerts(days_threshold=30)

    by_domain = {a['domain']: a for a in alerts}
    unknown = by_domain['gone.example']
    assert unknown['severity'] == 'unknown'
    assert unknown['days_remaining'] is None
    assert unknown['error']
    # The probeable cert still reports normally alongside it.
    assert by_domain['fine.example']['severity'] in ('warning', 'critical')
    assert by_domain['fine.example']['days_remaining'] is not None


# --------------------------------------------------------------------------- #
# 6. Cert health: a failed probe is grade None / valid None, never grade F
# --------------------------------------------------------------------------- #

def test_cert_health_probe_failure_is_unknown_not_grade_f(app):
    """A DNS failure/timeout is not a determined "terrible TLS config"."""
    with patch.object(socket, 'create_connection',
                      side_effect=OSError('Name or service not known')):
        result = AdvancedSSLService.get_cert_health('unreachable.example.com')

    assert result['grade'] is None
    assert result['valid'] is None
    assert 'Name or service not known' in result['error']


# --------------------------------------------------------------------------- #
# 7. Certificate inventory: a failed certbot probe is surfaced, not "0 certs"
# --------------------------------------------------------------------------- #

def test_list_certificates_report_surfaces_certbot_failure(app):
    with patch('app.services.ssl_service.run_privileged',
               side_effect=FileNotFoundError('certbot')):
        certificates, errors = SSLService.list_certificates_report()

    assert certificates == []
    assert errors
    assert 'certbot inventory failed' in errors[0]


def test_ssl_status_surfaces_list_errors(app, client, auth_headers):
    """The status payload must let the UI show "inventory unavailable"
    instead of an empty list rendered as "0 certificates, nothing expiring"."""
    with patch('app.services.ssl_service.run_privileged',
               side_effect=FileNotFoundError('certbot')), \
            patch.object(SSLService, 'is_certbot_installed', return_value=False):
        resp = client.get('/api/v1/ssl/status', headers=auth_headers)

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['total_certificates'] == 0
    assert payload['list_errors']
    assert 'certbot inventory failed' in payload['list_errors'][0]
