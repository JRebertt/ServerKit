"""Server capacity: live headroom, install profiles, and the de-gated features.

Covers the shift away from the three-bucket tier gate. The old service
classified a box once from total CPU/RAM and then permanently disabled a
button; these tests pin the replacement — headroom computed from *available*
memory, an install profile that says what was provisioned, and feature flags
that advise instead of block.
"""
import os
from unittest.mock import patch

import pytest

from app.services import install_profile_service as ips
from app.services.resource_tier_service import (
    OS_RESERVE_MB,
    WORKLOAD_FOOTPRINTS_MB,
    ResourceTierService,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    """Specs cache for an hour and capabilities for a minute; tests must not
    inherit each other's readings."""
    from app.services import resource_tier_service as rts

    def reset():
        rts._tier_cache['data'] = None
        rts._tier_cache['timestamp'] = 0
        ips._capability_cache['data'] = None
        ips._capability_cache['timestamp'] = 0

    reset()
    yield
    reset()


def _specs(ram_gb=4, cores=4, disk_free_gb=50, swap_mb=1024, container=None):
    return {
        'cpu_cores': cores,
        'ram_gb': ram_gb,
        'total_memory_gb': ram_gb,
        'ram_bytes': int(ram_gb * 1024 ** 3),
        'swap_mb': swap_mb,
        'disk_free_gb': disk_free_gb,
        'container': container,
    }


# ── specs shape ──────────────────────────────────────────────────────────────

def test_specs_expose_both_ram_key_names():
    """The wizard reads total_memory_gb; the original service only set ram_gb,
    so RAM rendered blank on every setup screen. Both must be present."""
    specs = ResourceTierService._get_system_specs()
    assert specs['ram_gb'] == specs['total_memory_gb']
    assert specs['total_memory_gb'] > 0


def test_specs_include_disk_swap_and_container_keys():
    specs = ResourceTierService._get_system_specs()
    for key in ('disk_free_gb', 'swap_mb', 'container', 'cpu_cores'):
        assert key in specs


# ── headroom ─────────────────────────────────────────────────────────────────

def test_headroom_subtracts_the_os_reserve_from_available():
    """Headroom is available memory minus the OS margin — never total memory.
    Using total is what made the old tier wrong the moment anything deployed."""
    available_mb = 4096
    with patch('psutil.virtual_memory') as vm:
        vm.return_value.available = available_mb * 1024 ** 2
        headroom = ResourceTierService.get_headroom(_specs())

    assert headroom['ram_available_mb'] == available_mb
    assert headroom['ram_for_apps_mb'] == available_mb - OS_RESERVE_MB


def test_headroom_never_goes_negative_on_an_exhausted_box():
    with patch('psutil.virtual_memory') as vm:
        vm.return_value.available = 8 * 1024 ** 2  # 8MB left
        headroom = ResourceTierService.get_headroom(_specs())

    assert headroom['ram_for_apps_mb'] == 0
    assert headroom['fits']['wordpress'] is False
    assert headroom['fits']['static'] is False


def test_headroom_fit_map_tracks_the_workload_footprints():
    # Exactly enough for WordPress once the OS reserve is taken off the top.
    available_mb = WORKLOAD_FOOTPRINTS_MB['wordpress'] + OS_RESERVE_MB
    with patch('psutil.virtual_memory') as vm:
        vm.return_value.available = available_mb * 1024 ** 2
        headroom = ResourceTierService.get_headroom(_specs())

    assert headroom['fits']['wordpress'] is True
    assert headroom['fits']['node'] is True

    # One megabyte short and WordPress stops fitting, but a Node app still does.
    with patch('psutil.virtual_memory') as vm:
        vm.return_value.available = (available_mb - 1) * 1024 ** 2
        headroom = ResourceTierService.get_headroom(_specs())

    assert headroom['fits']['wordpress'] is False
    assert headroom['fits']['node'] is True


@pytest.mark.parametrize('for_apps_mb,expected_fragment', [
    (0, 'No room'),
    (64, 'static sites only'),
    (400, 'but not WordPress'),
    (600, 'WordPress site'),
    (1600, 'WordPress sites'),
])
def test_headroom_summary_is_actionable_prose(for_apps_mb, expected_fragment):
    """"1.2 GB free — roughly 2 WordPress sites" beats "you are Lite tier"."""
    assert expected_fragment in ResourceTierService._describe_headroom(for_apps_mb)


def test_headroom_warns_about_containers_low_disk_and_missing_swap():
    with patch('psutil.virtual_memory') as vm:
        vm.return_value.available = 4096 * 1024 ** 2
        headroom = ResourceTierService.get_headroom(
            _specs(ram_gb=1, disk_free_gb=2, swap_mb=0, container='lxc')
        )

    joined = ' '.join(headroom['warnings']).lower()
    assert 'lxc' in joined
    assert 'disk free' in joined
    assert 'swap' in joined


def test_headroom_is_never_served_from_cache():
    """Specs may be cached for an hour; the live number must not be."""
    # get_tier_info() also reads .total for the specs, so the mock has to carry
    # a real number there or _calculate_tier compares against a MagicMock.
    with patch('psutil.virtual_memory') as vm:
        vm.return_value.total = 8 * 1024 ** 3
        vm.return_value.available = 4096 * 1024 ** 2
        first = ResourceTierService.get_tier_info()
    assert first['cached'] is False

    with patch('psutil.virtual_memory') as vm:
        vm.return_value.total = 8 * 1024 ** 3
        vm.return_value.available = 512 * 1024 ** 2
        second = ResourceTierService.get_tier_info()

    assert second['cached'] is True  # specs came from cache...
    # ...but headroom was recomputed against the new reading.
    assert second['headroom']['ram_available_mb'] == 512
    assert second['headroom']['ram_for_apps_mb'] != first['headroom']['ram_for_apps_mb']


# ── de-gating ────────────────────────────────────────────────────────────────

def test_wordpress_creation_is_never_blocked_on_resources():
    """A hard gate reads like a paywall on an OSS panel and is wrong the moment
    the VPS is resized. The flag stays permissive; the advice moves to
    wordpress_create_advised."""
    tiny = _specs(ram_gb=0.5, cores=1)
    features = ResourceTierService._get_features_for_tier(
        ResourceTierService.TIER_LITE, tiny
    )

    assert features['wordpress_create'] is True
    assert features['wordpress_create_advised'] is False
    assert ResourceTierService.can_create_wordpress() is True


def test_wordpress_is_advised_on_an_adequate_box():
    features = ResourceTierService._get_features_for_tier(
        ResourceTierService.TIER_STANDARD, _specs(ram_gb=4, cores=2)
    )
    assert features['wordpress_create_advised'] is True


@pytest.mark.parametrize('ram_gb,cores,expected', [
    (0.5, 1, ResourceTierService.TIER_LITE),
    (1, 4, ResourceTierService.TIER_LITE),
    (4, 2, ResourceTierService.TIER_STANDARD),
    (8, 4, ResourceTierService.TIER_PERFORMANCE),
])
def test_tier_label_still_derives_for_display(ram_gb, cores, expected):
    """Tier survives as a display label — nothing gates on it any more."""
    assert ResourceTierService._calculate_tier(_specs(ram_gb, cores)) == expected


# ── install profiles ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('specs,expected', [
    # Mirrors T31 in scripts/test/test_install.sh — the installer and the panel
    # must not disagree about what a given box should get.
    (_specs(ram_gb=0.7, cores=8, disk_free_gb=100), ips.PROFILE_MINIMAL),
    (_specs(ram_gb=2, cores=2, disk_free_gb=50), ips.PROFILE_STANDARD),
    (_specs(ram_gb=8, cores=4, disk_free_gb=50), ips.PROFILE_FULL),
    (_specs(ram_gb=8, cores=8, disk_free_gb=2), ips.PROFILE_MINIMAL),
    (_specs(ram_gb=8, cores=8, container='lxc'), ips.PROFILE_MINIMAL),
    (_specs(ram_gb=8, cores=8, container='openvz'), ips.PROFILE_MINIMAL),
])
def test_recommend_profile_matches_the_installer_thresholds(specs, expected):
    assert ips.recommend_profile(specs) == expected


def test_recommend_profile_tolerates_missing_facts():
    """A host where disk/container could not be read must still get an answer."""
    assert ips.recommend_profile({}) in ips.VALID_PROFILES
    assert ips.recommend_profile(
        {'ram_gb': 8, 'cpu_cores': 4, 'disk_free_gb': None}
    ) == ips.PROFILE_FULL


def test_get_profile_reads_the_installer_env(app):
    with app.app_context():
        with patch.dict(os.environ, {'SERVERKIT_PROFILE': 'minimal'}):
            assert ips.get_profile() == ips.PROFILE_MINIMAL


def test_get_profile_falls_back_on_a_hand_edited_env(app):
    """A typo in .env must not take the panel down."""
    with app.app_context():
        with patch.dict(os.environ, {'SERVERKIT_PROFILE': 'banana'}):
            assert ips.get_profile() == ips.DEFAULT_PROFILE


def test_set_profile_overrides_the_env(app):
    with app.app_context():
        with patch.dict(os.environ, {'SERVERKIT_PROFILE': 'minimal'}):
            ips.set_profile(ips.PROFILE_STANDARD)
            assert ips.get_profile() == ips.PROFILE_STANDARD


def test_set_profile_rejects_unknown_values(app):
    with app.app_context():
        with pytest.raises(ValueError):
            ips.set_profile('enterprise-plus')


def test_capabilities_report_docker_unusable_when_the_daemon_is_dead(app):
    """An installed binary proves nothing — inside LXC the client is often
    present while the daemon has never started."""
    with app.app_context():
        with patch.object(ips, '_binary_present', return_value=True), \
             patch('subprocess.run') as run:
            run.return_value.returncode = 1
            caps = ips.get_capabilities()

    assert caps['docker'] is False
    assert caps['can_host_apps'] is False


def test_docker_probe_is_cached_between_calls(app):
    """`docker info` can block for its full timeout on exactly the wedged host
    most likely to be asking, so a page load must not pay for it twice."""
    with app.app_context():
        with patch.object(ips, '_binary_present', return_value=True), \
             patch('subprocess.run') as run:
            run.return_value.returncode = 0
            ips.get_capabilities()
            ips.get_capabilities()
            assert run.call_count == 1

            ips.get_capabilities(force_refresh=True)
            assert run.call_count == 2


def test_profile_info_flags_drift_between_intent_and_reality(app):
    with app.app_context():
        with patch.dict(os.environ, {'SERVERKIT_PROFILE': 'standard'}), \
             patch.object(ips, 'get_capabilities', return_value={
                 'docker': False, 'node': True, 'nginx': True,
                 'git': True, 'can_host_apps': False,
             }):
            info = ips.get_profile_info()

    assert info['profile'] == ips.PROFILE_STANDARD
    assert any('Docker is not responding' in d for d in info['drift'])


def test_every_profile_is_described_for_the_wizard():
    """The wizard renders card bodies straight from the backend, so a profile
    without a description would render an empty card."""
    for profile in ips.VALID_PROFILES:
        described = ips.PROFILE_DESCRIPTIONS[profile]
        assert described['label']
        assert described['summary']
        assert described['installs']
        assert 'skips' in described
        assert described['suited_for']


# ── doctor must not fail a healthy Dockerless box ────────────────────────────

def test_doctor_skips_docker_on_a_minimal_install(app):
    """A minimal install has no Docker by design; probing for it reported a
    permanent, unrepairable 'Not running.' failure on a healthy box."""
    from app.services.doctor_service import DoctorService

    with app.app_context():
        with patch.dict(os.environ, {'SERVERKIT_PROFILE': 'minimal'}), \
             patch.object(ips, 'get_capabilities', return_value={
                 'docker': False, 'node': True, 'nginx': True,
                 'git': True, 'can_host_apps': False,
             }):
            probed = DoctorService._expected_services()
            skipped = DoctorService._skipped_service_checks(probed)

    assert 'docker' not in probed
    assert 'nginx' in probed
    assert [c['status'] for c in skipped] == ['ok']
    assert 'Minimal profile' in skipped[0]['detail']


def test_doctor_still_probes_docker_when_it_was_installed_later(app):
    """Minimal profile but Docker present = the operator added it; it is in use
    and a stopped daemon is a real failure."""
    from app.services.doctor_service import DoctorService

    with app.app_context():
        with patch.dict(os.environ, {'SERVERKIT_PROFILE': 'minimal'}), \
             patch.object(ips, 'get_capabilities', return_value={
                 'docker': True, 'node': True, 'nginx': True,
                 'git': True, 'can_host_apps': True,
             }):
            probed = DoctorService._expected_services()

    assert 'docker' in probed


def test_doctor_still_fails_a_standard_install_missing_docker(app):
    """Standard promised Docker, so its absence is drift and must surface."""
    from app.services.doctor_service import DoctorService

    with app.app_context():
        with patch.dict(os.environ, {'SERVERKIT_PROFILE': 'standard'}), \
             patch.object(ips, 'get_capabilities', return_value={
                 'docker': False, 'node': True, 'nginx': True,
                 'git': True, 'can_host_apps': False,
             }):
            probed = DoctorService._expected_services()

    assert 'docker' in probed


def test_doctor_probes_everything_when_profile_resolution_breaks(app):
    """Profile lookup must never be able to suppress a real health check."""
    from app.services.doctor_service import DoctorService

    with app.app_context():
        with patch.object(ips, 'get_profile', side_effect=RuntimeError('boom')):
            probed = DoctorService._expected_services()

    assert 'docker' in probed
    assert 'nginx' in probed


def test_docker_stays_repairable_even_when_not_probed(app):
    """_restart_service gates on the static CORE_SERVICES allowlist, so an
    operator who installs Docker later can still have the doctor restart it."""
    from app.services.doctor_service import CORE_SERVICES

    assert 'docker' in CORE_SERVICES


# ── endpoints ────────────────────────────────────────────────────────────────

def test_capacity_endpoint_returns_headroom_and_profile(client, auth_headers):
    resp = client.get('/api/v1/system/capacity', headers=auth_headers)
    assert resp.status_code == 200

    body = resp.get_json()
    assert body['profile'] in ips.VALID_PROFILES
    assert body['recommended_profile'] in ips.VALID_PROFILES
    assert 'summary' in body['headroom']
    assert 'fits' in body['headroom']
    assert body['specs']['total_memory_gb'] > 0
    assert body['capabilities']['can_host_apps'] in (True, False)
    # De-gated: the API must never report creation as forbidden.
    assert body['features']['wordpress_create'] is True


def test_capacity_endpoint_requires_admin(client, app):
    from app import db
    from app.models import User
    from flask_jwt_extended import create_access_token
    from werkzeug.security import generate_password_hash

    with app.app_context():
        user = User(
            email='dev@test.local',
            username='devuser',
            password_hash=generate_password_hash('x'),
            role=User.ROLE_DEVELOPER,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=user.id)

    resp = client.get(
        '/api/v1/system/capacity',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == 403


def test_capacity_endpoint_rejects_anonymous(client):
    assert client.get('/api/v1/system/capacity').status_code == 401


def test_profile_can_be_changed_through_the_api(client, auth_headers):
    resp = client.put(
        '/api/v1/system/capacity/profile',
        json={'profile': 'minimal'},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()['profile'] == ips.PROFILE_MINIMAL

    resp = client.put(
        '/api/v1/system/capacity/profile',
        json={'profile': 'enterprise-plus'},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_resource_tier_endpoint_still_works_for_existing_callers(client, auth_headers):
    resp = client.get('/api/v1/system/resource-tier', headers=auth_headers)
    assert resp.status_code == 200

    body = resp.get_json()
    assert body['tier'] in ('lite', 'standard', 'performance')
    assert 'headroom' in body
