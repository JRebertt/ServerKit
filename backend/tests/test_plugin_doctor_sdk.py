"""Doctor checks contributed by plugins (plugins_sdk.doctor).

An extension had no way to say "the thing I manage is unhealthy" on the page an
operator opens to ask exactly that. Registering a provider puts its checks in
the sweep, and the panel renders them with no frontend change.

Core's own producers each hand-roll their isolation and nothing bounds their
runtime; because these run third-party code, the registry adds both — most of
this file is about what happens when a contributed check misbehaves.
"""

import time

import pytest

from app.services import doctor_check_registry
from app.services.doctor_service import DoctorService


@pytest.fixture(autouse=True)
def _clean_registry():
    doctor_check_registry.clear()
    yield
    doctor_check_registry.clear()


def _ok(**over):
    check = {'key': 'worlds', 'title': 'Worlds', 'status': 'ok', 'detail': 'Fine.'}
    check.update(over)
    return check


def _collect_keys():
    return {c['key']: c for c in doctor_check_registry.collect()}


class TestRegistry:
    def test_registers_and_resolves(self):
        provider = lambda: []
        doctor_check_registry.register('minecraft', provider)
        assert doctor_check_registry.get('minecraft')['provider'] is provider
        assert 'minecraft' in doctor_check_registry.namespaces()

    def test_core_namespaces_cannot_be_hijacked(self):
        for namespace in doctor_check_registry.CORE_NAMESPACES:
            with pytest.raises(ValueError):
                doctor_check_registry.register(namespace, lambda: [])

    def test_duplicate_registration_needs_replace(self):
        doctor_check_registry.register('minecraft', lambda: [])
        with pytest.raises(ValueError):
            doctor_check_registry.register('minecraft', lambda: [])
        doctor_check_registry.register('minecraft', lambda: [], replace=True)

    def test_rejects_non_callables(self):
        with pytest.raises(ValueError):
            doctor_check_registry.register('minecraft', 'nope')
        with pytest.raises(ValueError):
            doctor_check_registry.register('minecraft', lambda: [], repair='nope')


class TestCollect:
    def test_namespaces_the_keys(self, app):
        doctor_check_registry.register('minecraft', lambda: _ok())
        assert 'minecraft.worlds' in _collect_keys()

    def test_does_not_double_prefix_an_already_namespaced_key(self, app):
        doctor_check_registry.register('minecraft', lambda: _ok(key='minecraft.worlds'))
        assert list(_collect_keys()) == ['minecraft.worlds']

    def test_accepts_one_check_or_a_list(self, app):
        doctor_check_registry.register('a', lambda: _ok())
        doctor_check_registry.register('b', lambda: [_ok(key='one'), _ok(key='two')])
        assert set(_collect_keys()) == {'a.worlds', 'b.one', 'b.two'}

    def test_drops_checks_missing_a_key_or_title(self, app):
        doctor_check_registry.register(
            'minecraft', lambda: [{'title': 'no key'}, {'key': 'no-title'}, 'junk'])
        assert _collect_keys() == {}

    def test_unrenderable_status_becomes_a_warning(self, app):
        # A blank pill would hide a plugin bug; a warning shows it.
        doctor_check_registry.register('minecraft', lambda: _ok(status='catastrophe'))
        assert _collect_keys()['minecraft.worlds']['status'] == 'warn'

    def test_attributes_checks_to_their_plugin(self, app):
        doctor_check_registry.register('minecraft', lambda: _ok())
        assert _collect_keys()['minecraft.worlds']['plugin'] == 'minecraft'


class TestMisbehaviour:
    def test_a_raising_provider_becomes_one_warning(self, app):
        def explode():
            raise RuntimeError('provider is broken')

        doctor_check_registry.register('minecraft', explode)
        checks = doctor_check_registry.collect()

        assert len(checks) == 1
        assert checks[0]['status'] == 'warn'
        assert 'provider is broken' in checks[0]['detail']

    def test_a_hanging_provider_is_abandoned(self, app):
        def hang():
            time.sleep(5)
            return _ok()

        doctor_check_registry.register('minecraft', hang, timeout=0.2)
        started = time.monotonic()
        checks = doctor_check_registry.collect()

        # The sweep must not wait on it — POST /doctor/run is synchronous.
        assert time.monotonic() - started < 3
        assert checks[0]['status'] == 'warn'
        assert 'timed out' in checks[0]['title']

    def test_one_bad_provider_does_not_hide_a_good_one(self, app):
        doctor_check_registry.register('good', lambda: _ok())
        doctor_check_registry.register('bad', lambda: 1 / 0)

        statuses = {c['key']: c['status'] for c in doctor_check_registry.collect()}
        assert statuses['good.worlds'] == 'ok'
        assert statuses['bad.error'] == 'warn'


class TestRepair:
    def test_repairable_ref_is_wrapped_for_routing(self, app):
        doctor_check_registry.register(
            'minecraft',
            lambda: _ok(status='warn', repairable=True, repair_ref={'worlds': [1]}),
            repair=lambda ref: {'success': True})

        check = _collect_keys()['minecraft.worlds']
        assert check['repairable'] is True
        assert check['repair_ref'] == {'kind': 'extension', 'namespace': 'minecraft',
                                       'ref': {'worlds': [1]}}

    def test_repairable_without_a_handler_is_demoted(self, app):
        # Otherwise the panel shows a button whose dispatch goes nowhere —
        # which is exactly the state two core checks are already in.
        doctor_check_registry.register(
            'minecraft', lambda: _ok(repairable=True, repair_ref={'worlds': [1]}))

        check = _collect_keys()['minecraft.worlds']
        assert check['repairable'] is False
        assert check['repair_ref'] is None

    def test_doctor_repair_routes_to_the_plugin(self, app):
        seen = {}

        def fix(ref):
            seen['ref'] = ref
            return {'success': True, 'message': 'fixed'}

        doctor_check_registry.register('minecraft', lambda: [], repair=fix)

        results = DoctorService.repair([
            {'kind': 'extension', 'namespace': 'minecraft', 'ref': {'worlds': [7]}}])

        assert results[0]['success'] is True
        assert results[0]['message'] == 'fixed'
        assert seen['ref'] == {'worlds': [7]}

    def test_repair_for_an_unregistered_namespace_is_refused(self, app):
        # The registry IS the allowlist, so a crafted ref reaches nothing.
        results = DoctorService.repair([
            {'kind': 'extension', 'namespace': 'not-installed', 'ref': {}}])
        assert results[0]['success'] is False

    def test_a_raising_repair_reports_failure(self, app):
        def fix(ref):
            raise RuntimeError('could not fix')

        doctor_check_registry.register('minecraft', lambda: [], repair=fix)
        results = DoctorService.repair([
            {'kind': 'extension', 'namespace': 'minecraft', 'ref': {}}])

        assert results[0]['success'] is False
        assert 'could not fix' in results[0]['error']


class TestSweep:
    def test_contributed_checks_appear_in_the_report(self, app, monkeypatch):
        # Stub the core producers so this test is about the wiring, not about
        # whatever the host machine's nginx is doing.
        for producer in ('_drift_checks', '_service_checks', '_dns_checks',
                         '_backup_proof_checks', '_setup_checks'):
            monkeypatch.setattr(DoctorService, producer, classmethod(lambda cls: []))
        for producer in ('_cert_check', '_disk_check', '_db_check'):
            monkeypatch.setattr(DoctorService, producer, classmethod(
                lambda cls: {'key': 'core', 'title': 'Core', 'status': 'ok',
                             'detail': '', 'repairable': False, 'repair_ref': None}))

        doctor_check_registry.register('minecraft', lambda: _ok(status='fail'))

        report = DoctorService.run()

        contributed = [c for c in report['checks'] if c['key'] == 'minecraft.worlds']
        assert len(contributed) == 1
        assert contributed[0]['status'] == 'fail'
        # Every core check carries these six fields and the panel reads them
        # positionally-by-name; a contributed one must be indistinguishable.
        for field in ('key', 'title', 'status', 'detail', 'repairable', 'repair_ref'):
            assert field in contributed[0]


def test_sdk_is_reachable_from_the_package(app):
    from app import plugins_sdk

    plugins_sdk.doctor.register('minecraft', lambda: _ok())
    assert 'minecraft' in plugins_sdk.doctor.namespaces()
    assert plugins_sdk.doctor.STATUSES == ('ok', 'warn', 'fail')
