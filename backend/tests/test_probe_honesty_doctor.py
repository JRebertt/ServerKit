"""A probe that could not answer must never render as a healthy (or guilty)
answer — host doctor + drift edition.

Plan 75 §A2. The bug class: a probe's failure mode was collapsed into a real
answer at the summarising boundary, so Doctor lied in both directions:

* **Green by omission.** A broken Domain query returned ``[]`` from
  ``_site_domains``, which `_dns_checks` rendered as the ok row "No public
  site domains to check." A failed backup-run query returned ``None`` from
  ``_backup_unverified_check`` and the check vanished entirely. A failing
  setup-health or extension section returned ``[]`` — a whole doctor section
  silently missing. A docker capability probe that blew up read as "Docker
  absent", so a Minimal-profile box got the green "Not installed" skip row.
* **Guilty by omission.** Any resolver exception in `_dns_check_one` —
  including the panel's own DNS server being down — was treated as NXDOMAIN:
  a fail row, a repair offer, and an admin page via `_notify_dns_failures`.
  A missing ``systemctl`` made `ServiceControl.is_active` answer ``False``,
  so the doctor reported fail "Not running." and offered a repair that could
  only fail. An app the drift sweep could not even inspect was dropped from
  the resource list — "in sync" by omission.

The rule is the drill/verify rule: **`ok` must be positively earned** — and
its mirror: **`fail` must be positively earned too.** "Couldn't check" is its
own answer (warn/error), never the negative and never the positive.
"""
import socket

import pytest

from app import db
from app.services import doctor_service
from app.services.doctor_service import DoctorService


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def site(app):
    """An Application to hang test Domain rows off (same shape as
    test_doctor_dns)."""
    from werkzeug.security import generate_password_hash
    from app.models import User
    from app.models.application import Application

    user = User(email='honesty@test.local', username='honestyuser',
                password_hash=generate_password_hash('x'),
                role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.flush()
    row = Application(name='honestysite', app_type='static', user_id=user.id)
    db.session.add(row)
    db.session.commit()
    return row


def add_domain(site, name):
    from app.models.domain import Domain
    db.session.add(Domain(name=name, application_id=site.id))
    db.session.commit()


def set_server_ip(monkeypatch, ip):
    from app.services.site_domain_service import SiteDomainService
    monkeypatch.setattr(SiteDomainService, 'server_ip',
                        classmethod(lambda cls: ip))


# --------------------------------------------------------------------------- #
# Finding 1: a broken Domain query is "could not check", not "no domains" (ok)
# --------------------------------------------------------------------------- #

def test_broken_domain_query_is_a_warn_not_a_green_ok(app, monkeypatch):
    """The bug, stated directly: `except Exception: return []` fed the
    'No public site domains to check.' ok row."""
    from app.models.domain import Domain

    def _boom(cls):
        raise RuntimeError('database is locked')

    monkeypatch.setattr(Domain, 'query_active', classmethod(_boom))

    checks = DoctorService._dns_checks()

    assert len(checks) == 1
    assert checks[0]['key'] == 'dns.resolve'
    assert checks[0]['status'] == 'warn'
    assert 'Could not read site domains' in checks[0]['detail']


def test_empty_domain_table_is_still_an_honest_ok(app):
    """A query that RAN and found nothing earns its ok — only the broken
    query degrades."""
    checks = DoctorService._dns_checks()
    assert len(checks) == 1
    assert checks[0]['status'] == 'ok'
    assert 'No public site domains' in checks[0]['detail']


def test_dns_repair_survives_an_unreadable_domain_table(app, site, monkeypatch):
    """_repair_dns iterates _site_domains(); None must not 500 the repair —
    it refuses as 'not managed' (it cannot verify manageability)."""
    monkeypatch.setattr(DoctorService, '_site_domains',
                        classmethod(lambda cls: None))
    result = DoctorService._repair_dns('gone.example.com')
    assert result['success'] is False
    assert 'Not a managed site domain' in result['error']


# --------------------------------------------------------------------------- #
# Finding 2: NXDOMAIN is a fail; a resolver outage is "could not check" (warn)
# --------------------------------------------------------------------------- #

def test_nxdomain_is_still_a_fail(app, site, monkeypatch):
    """The honest negative: the name provably does not exist."""
    add_domain(site, 'gone.example.com')
    set_server_ip(monkeypatch, '203.0.113.7')
    monkeypatch.setattr(
        doctor_service, '_resolve_host_ips',
        lambda host: (_ for _ in ()).throw(
            socket.gaierror(socket.EAI_NONAME, 'Name or service not known')))

    checks = {c['key']: c for c in DoctorService._dns_checks()}
    c = checks['dns.resolve.gone.example.com']
    assert c['status'] == 'fail'
    assert 'does not resolve' in c['detail']


def test_a_resolver_error_is_a_warn_not_a_fake_nxdomain(app, site, monkeypatch):
    """The bug, stated directly: EAI_AGAIN (our DNS server is down) used to
    render as 'gone.example.com does not resolve' — fail + repair offer."""
    add_domain(site, 'gone.example.com')
    set_server_ip(monkeypatch, '203.0.113.7')
    monkeypatch.setattr(
        doctor_service, '_resolve_host_ips',
        lambda host: (_ for _ in ()).throw(
            socket.gaierror(socket.EAI_AGAIN, 'Temporary failure in name resolution')))

    checks = {c['key']: c for c in DoctorService._dns_checks()}
    c = checks['dns.resolve.gone.example.com']
    assert c['status'] == 'warn'
    assert 'could not check' in c['detail']
    assert c['repairable'] is False


def test_a_non_gaierror_resolver_failure_is_also_a_warn(app, site, monkeypatch):
    """Timeout / OSError from the resolver is likewise not proof of NXDOMAIN."""
    add_domain(site, 'gone.example.com')
    set_server_ip(monkeypatch, '203.0.113.7')
    monkeypatch.setattr(
        doctor_service, '_resolve_host_ips',
        lambda host: (_ for _ in ()).throw(TimeoutError('resolver timed out')))

    checks = {c['key']: c for c in DoctorService._dns_checks()}
    c = checks['dns.resolve.gone.example.com']
    assert c['status'] == 'warn'
    assert 'could not check' in c['detail']


def test_warn_dns_rows_are_not_failed_hosts(app):
    """The notification boundary: only fail rows may page admins."""
    checks = [
        {'key': 'dns.resolve.broken.example.com', 'status': 'fail'},
        {'key': 'dns.resolve.unknown.example.com', 'status': 'warn'},
    ]
    assert DoctorService._failed_dns_hosts(checks) == ['broken.example.com']


class _JobStub:
    def get_payload(self):
        return {}


def test_a_resolver_outage_pages_nobody(app, site, monkeypatch):
    """End to end: a sweep during a panel-side DNS outage must not send the
    'Site domain(s) no longer resolve' admin notification."""
    import app.plugins_sdk as sdk
    from app.services.settings_service import SettingsService

    add_domain(site, 'maybe-fine.example.com')
    set_server_ip(monkeypatch, '203.0.113.7')
    monkeypatch.setattr(
        doctor_service, '_resolve_host_ips',
        lambda host: (_ for _ in ()).throw(
            socket.gaierror(socket.EAI_AGAIN, 'Temporary failure')))
    # Keep every non-DNS section out of the way.
    monkeypatch.setattr(DoctorService, '_drift_checks', classmethod(lambda cls: []))
    monkeypatch.setattr(DoctorService, '_service_checks', classmethod(lambda cls: []))
    monkeypatch.setattr(DoctorService, '_backup_proof_checks',
                        classmethod(lambda cls: []))
    monkeypatch.setattr(DoctorService, '_setup_checks', classmethod(lambda cls: []))
    monkeypatch.setattr(DoctorService, '_extension_checks',
                        classmethod(lambda cls: []))
    monkeypatch.setattr(DoctorService, 'store_report',
                        classmethod(lambda cls, report: None))

    sent = []
    monkeypatch.setattr(sdk.notify, 'send',
                        lambda event, to, data=None, **kw: sent.append(event))

    summary = DoctorService.run_doctor_job(_JobStub())

    assert summary['dns_new_failures'] == []
    assert sent == []


# --------------------------------------------------------------------------- #
# Finding 3: an unreadable backup-run table is a warn, not a vanished check
# --------------------------------------------------------------------------- #

def _policy(app):
    from app.models.backup_policy import BackupPolicy
    policy = BackupPolicy(target_type='application', target_id=1)
    db.session.add(policy)
    db.session.commit()
    return policy


def test_broken_backup_run_query_is_a_warn_not_a_vanished_check(app, monkeypatch):
    """The bug: `except Exception: return None` — the check simply wasn't in
    the report."""
    from app.models.backup_run import BackupRun

    class _Boom:
        def filter_by(self, **kw):
            raise RuntimeError('database is locked')

    monkeypatch.setattr(BackupRun, 'query', _Boom())
    policy = _policy(app)

    check = DoctorService._backup_unverified_check(policy)

    assert check is not None
    assert check['status'] == 'warn'
    assert 'Could not read backup runs' in check['detail']


# --------------------------------------------------------------------------- #
# Finding 8: one bad policy row must not 500 the whole backup-proof sweep
# --------------------------------------------------------------------------- #

def test_one_bad_policy_degrades_to_a_warn_row(app, monkeypatch):
    policy = _policy(app)

    def _boom(cls, p):
        raise RuntimeError('corrupt row')

    monkeypatch.setattr(DoctorService, '_backup_drill_stale_check',
                        classmethod(_boom))

    checks = DoctorService._backup_proof_checks()

    assert len(checks) == 1
    assert checks[0]['status'] == 'warn'
    assert checks[0]['key'] == f'backup_proof.{policy.id}'
    assert 'Could not evaluate backup policy' in checks[0]['detail']


# --------------------------------------------------------------------------- #
# Finding 4: a failed doctor section is a warn row, not a missing section
# --------------------------------------------------------------------------- #

def test_setup_section_failure_leaves_a_warn_row(app, monkeypatch):
    from app.services.setup_health_service import SetupHealthService
    monkeypatch.setattr(
        SetupHealthService, 'doctor_checks',
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError('boom'))))

    checks = DoctorService._setup_checks()

    assert len(checks) == 1
    assert checks[0]['key'] == 'setup.health'
    assert checks[0]['status'] == 'warn'
    assert 'Could not run setup-health checks' in checks[0]['detail']


def test_extension_section_failure_leaves_a_warn_row(app, monkeypatch):
    from app.services import doctor_check_registry
    monkeypatch.setattr(
        doctor_check_registry, 'collect',
        lambda: (_ for _ in ()).throw(RuntimeError('boom')))

    checks = DoctorService._extension_checks()

    assert len(checks) == 1
    assert checks[0]['key'] == 'extensions.checks'
    assert checks[0]['status'] == 'warn'
    assert 'Could not collect extension checks' in checks[0]['detail']


# --------------------------------------------------------------------------- #
# Finding 5: no systemctl = "Status probe failed" (warn), never "Not running."
# --------------------------------------------------------------------------- #

def test_missing_systemctl_is_a_warn_not_a_repairable_fail(app, monkeypatch):
    """The bug: is_active answered False on a host without systemctl, so the
    doctor reported fail 'Not running.' and offered a repair that cannot work."""
    from app.utils.system import ServiceControl

    monkeypatch.setattr(DoctorService, '_expected_services',
                        classmethod(lambda cls: ['docker']))

    def _no_systemctl(name):
        raise FileNotFoundError('systemctl')

    monkeypatch.setattr(ServiceControl, 'is_active', staticmethod(_no_systemctl))
    monkeypatch.setattr(doctor_service.sys, 'platform', 'linux')

    checks = {c['key']: c for c in DoctorService._service_checks()}

    c = checks['service.docker']
    assert c['status'] == 'warn'
    assert 'Status probe failed' in c['detail']
    assert c['repairable'] is False


def test_a_stopped_service_still_fails_and_is_repairable(app, monkeypatch):
    """The honest negative keeps its teeth: systemctl RAN and said inactive."""
    from app.utils.system import ServiceControl

    monkeypatch.setattr(DoctorService, '_expected_services',
                        classmethod(lambda cls: ['docker']))
    monkeypatch.setattr(ServiceControl, 'is_active',
                        staticmethod(lambda name: False))
    monkeypatch.setattr(doctor_service.sys, 'platform', 'linux')

    checks = {c['key']: c for c in DoctorService._service_checks()}

    c = checks['service.docker']
    assert c['status'] == 'fail'
    assert c['detail'] == 'Not running.'
    assert c['repairable'] is True


# --------------------------------------------------------------------------- #
# Finding 6: a failed docker probe is "unknown" — the box still gets probed,
# never the green "Not installed — Minimal profile." skip row
# --------------------------------------------------------------------------- #

def test_docker_probe_exception_is_unknown_not_absent(monkeypatch):
    from app.services import install_profile_service as ips

    monkeypatch.setattr(ips, '_binary_present', lambda name: True)
    monkeypatch.setattr(
        ips, 'run_checked',
        lambda *a, **k: (_ for _ in ()).throw(OSError('exec failed')))

    assert ips._docker_usable() is None


def test_docker_binary_absent_is_still_a_real_absent(monkeypatch):
    from app.services import install_profile_service as ips

    monkeypatch.setattr(ips, '_binary_present', lambda name: False)

    assert ips._docker_usable() is False


def test_a_failed_docker_probe_does_not_earn_the_minimal_skip_row(app, monkeypatch):
    """The bug chain: _docker_usable False → get_capabilities['docker'] falsy →
    _expected_services dropped docker → ok 'Not installed — Minimal profile.'
    on a box where the probe merely failed."""
    from app.services import install_profile_service as ips

    monkeypatch.setattr(ips, 'get_profile', lambda: ips.PROFILE_MINIMAL)
    monkeypatch.setattr(ips, 'get_capabilities',
                        lambda force_refresh=False: {'docker': None})

    probed = DoctorService._expected_services()

    assert 'docker' in probed
    skipped = DoctorService._skipped_service_checks(probed)
    assert all('docker' not in c['key'] for c in skipped)


def test_a_confirmed_absent_docker_still_earns_the_skip_row(app, monkeypatch):
    """The honest skip: probe RAN and Docker is genuinely not there."""
    from app.services import install_profile_service as ips

    monkeypatch.setattr(ips, 'get_profile', lambda: ips.PROFILE_MINIMAL)
    monkeypatch.setattr(ips, 'get_capabilities',
                        lambda force_refresh=False: {'docker': False})

    probed = DoctorService._expected_services()

    assert 'docker' not in probed
    skipped = DoctorService._skipped_service_checks(probed)
    assert [c['status'] for c in skipped] == ['ok']


# --------------------------------------------------------------------------- #
# Findings 9/10: an app the drift sweep cannot inspect is an error entry,
# not "in sync" by omission
# --------------------------------------------------------------------------- #

def _compose_app(app, tmp_path, name='composeapp'):
    from werkzeug.security import generate_password_hash
    from app.models import User
    from app.models.application import Application

    user = User(email=f'{name}@test.local', username=name,
                password_hash=generate_password_hash('x'),
                role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.flush()
    row = Application(name=name, app_type='docker', user_id=user.id,
                      root_path=str(tmp_path))
    db.session.add(row)
    db.session.commit()
    return row


def test_an_uninspectable_compose_app_is_an_error_entry(app, tmp_path, monkeypatch):
    """The bug: `except Exception: continue` dropped the app from the sweep,
    so the report read 'in sync' over a set it never checked."""
    from app.services.compose_env_service import ComposeEnvService
    from app.services.drift_service import _compose_list_resources

    app_row = _compose_app(app, tmp_path)
    monkeypatch.setattr(
        ComposeEnvService, 'find_base_compose',
        classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(
            PermissionError('root_path unreadable'))))

    resources = _compose_list_resources()

    assert len(resources) == 1
    entry = resources[0]
    assert entry['status'] == 'error'
    assert entry['id'] == app_row.id
    assert entry['type'] == 'compose_override'
    assert 'Could not inspect this app' in entry['detail']


def test_an_unresolvable_manifest_app_is_an_error_entry(app, tmp_path, monkeypatch):
    from app.services.drift_service import _manifest_list_resources
    from app.services.manifest_apply_service import ManifestApplyService

    app_row = _compose_app(app, tmp_path, name='manifestapp')
    app_row.project_id = 1  # manifest-managed candidate
    db.session.commit()
    monkeypatch.setattr(
        ManifestApplyService, 'resolved_for_app',
        classmethod(lambda cls, a: (_ for _ in ()).throw(
            RuntimeError('manifest blob is corrupt'))))

    resources = _manifest_list_resources()

    assert len(resources) == 1
    entry = resources[0]
    assert entry['status'] == 'error'
    assert entry['id'] == app_row.id
    assert entry['type'] == 'manifest'
    assert 'Could not resolve' in entry['detail']


def test_check_all_passes_inline_error_entries_through(app, monkeypatch):
    """The plumbing: a dict entry from list_resources reaches the report as an
    error row (which the doctor renders as a warn check), not a crash and not
    a dropped resource."""
    from app.services import drift_service
    from app.services.drift_service import DriftService

    registry = {}
    monkeypatch.setattr(drift_service, 'DRIFT_CHECKS', registry)
    drift_service.register_check({
        'type': 'fake',
        'title': 'Fake check',
        'list_resources': lambda: [
            {'type': 'fake', 'id': 7, 'name': 'unreadable-app',
             'status': 'error', 'diff': None,
             'detail': 'Could not inspect this app: boom',
             'checked_at': 'now'},
            (8, 'healthy-app'),
        ],
        'render_expected': lambda rid: {},
    })

    results = {r['id']: r for r in DriftService.check_all()}

    assert results[7]['status'] == 'error'
    assert 'Could not inspect' in results[7]['detail']
    assert results[8]['status'] == 'in_sync'


def test_doctor_renders_an_inline_error_entry_as_a_warn_check(app, monkeypatch):
    """The doctor boundary: the dropped app used to contribute nothing — an
    all-green drift section. Now it is a visible warn."""
    from app.services.drift_service import DriftService

    monkeypatch.setattr(DriftService, 'check_all', classmethod(lambda cls: [
        {'type': 'compose_override', 'id': 7, 'name': 'unreadable-app',
         'status': 'error', 'diff': None,
         'detail': 'Could not inspect this app: boom', 'checked_at': 'now'},
    ]))

    checks = DoctorService._drift_checks()

    assert len(checks) == 1
    assert checks[0]['status'] == 'warn'
    assert 'Could not inspect this app' in checks[0]['detail']
