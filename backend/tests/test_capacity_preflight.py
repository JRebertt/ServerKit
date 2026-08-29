"""Capacity preflight for template installs (capacity_service).

Installing checked the name, the server row and the directory — never whether
the box could carry the thing, so a 2 GB app landed on a 1 GB VPS at full speed
and the OOM killer delivered the news.

The rules this pins down are the ones that make the answer trustworthy: it
advises and never blocks, it says "unknown" instead of guessing, and "tight" is
measured against what is actually free rather than what the box has in total.
"""

from datetime import datetime, timedelta

import pytest

from app import db
from app.models.server import Server, ServerMetrics
from app.services import capacity_service
from app.services.capacity_service import check_fit, parse_size, template_footprint

GB = 1024 ** 3
MB = 1024 ** 2


def _template(memory='512MB', storage='1GB'):
    requirements = {}
    if memory is not None:
        requirements['memory'] = memory
    if storage is not None:
        requirements['storage'] = storage
    return {'id': 'demo', 'name': 'Demo', 'requirements': requirements}


@pytest.fixture
def server(app):
    """A managed server with 4 GB RAM / 100 GB disk and one usage sample."""
    row = Server(id='srv-cap-1', name='box', status='online',
                 total_memory=4 * GB, total_disk=100 * GB, cpu_cores=2)
    db.session.add(row)
    db.session.commit()
    return row


def _sample(server_id, memory_used, disk_used, age_minutes=0, disk_percent=None):
    metric = ServerMetrics(
        server_id=server_id,
        timestamp=datetime.utcnow() - timedelta(minutes=age_minutes),
        memory_used=memory_used, disk_used=disk_used,
        disk_percent=disk_percent,
    )
    db.session.add(metric)
    db.session.commit()
    return metric


class TestParsing:
    @pytest.mark.parametrize('text,expected', [
        ('512MB', 512 * MB), ('2GB', 2 * GB), ('1 GB', GB), ('256 mb', 256 * MB),
        ('1.5GB', int(1.5 * GB)), ('2GiB', 2 * GB), ('1024', 1024), ('4G', 4 * GB),
    ])
    def test_reads_the_forms_catalog_authors_write(self, text, expected):
        assert parse_size(text) == expected

    @pytest.mark.parametrize('text', ['', 'lots', None, 'MB', '-1GB', 0])
    def test_unusable_values_are_none_not_zero(self, text):
        # None degrades to "unknown"; zero would read as "needs nothing".
        assert parse_size(text) is None

    def test_footprint_accepts_storage_or_disk(self):
        assert template_footprint({'requirements': {'storage': '2GB'}})['disk'] == 2 * GB
        assert template_footprint({'requirements': {'disk': '2GB'}})['disk'] == 2 * GB

    def test_footprint_of_a_template_that_declares_nothing(self):
        footprint = template_footprint({'id': 'x'})
        assert footprint['memory'] is None and footprint['disk'] is None


class TestVerdicts:
    def test_comfortable_fit(self, app, server):
        _sample(server.id, memory_used=1 * GB, disk_used=10 * GB)
        result = check_fit(_template('512MB', '1GB'), server.id)
        assert result['verdict'] == 'ok'
        assert result['headline'] == 'Fits comfortably'

    def test_more_memory_than_the_server_has_free(self, app, server):
        _sample(server.id, memory_used=int(3.5 * GB), disk_used=10 * GB)
        result = check_fit(_template('2GB', '1GB'), server.id)
        assert result['verdict'] == 'insufficient'
        assert 'more memory than it has' in result['detail']

    def test_fits_but_leaves_almost_nothing(self, app, server):
        # 700 MB free, needs 512 MB — it fits, but the reserve floor is 409 MB
        # (10% of 4 GB), so this is the case worth warning about.
        _sample(server.id, memory_used=4 * GB - 700 * MB, disk_used=10 * GB)
        result = check_fit(_template('512MB', '1GB'), server.id)
        assert result['verdict'] == 'tight'
        assert 'would leave only' in result['detail']

    def test_disk_alone_can_decide_it(self, app, server):
        _sample(server.id, memory_used=1 * GB, disk_used=99 * GB)
        result = check_fit(_template('512MB', '20GB'), server.id)
        assert result['verdict'] == 'insufficient'
        assert [c['verdict'] for c in result['checks'] if c['resource'] == 'memory'] == ['ok']

    def test_the_worst_resource_decides_the_overall_verdict(self, app, server):
        _sample(server.id, memory_used=1 * GB, disk_used=99 * GB)
        result = check_fit(_template('512MB', '20GB'), server.id)
        assert result['verdict'] == 'insufficient'

    def test_it_never_blocks(self, app, server):
        _sample(server.id, memory_used=int(3.9 * GB), disk_used=99 * GB)
        result = check_fit(_template('4GB', '50GB'), server.id)
        # The operator decides. An estimate is an estimate.
        assert result['blocking'] is False


class TestHonestUnknowns:
    def test_a_server_with_no_readings_is_unknown_not_fine(self, app, server):
        result = check_fit(_template(), server.id)
        assert result['verdict'] == 'unknown'
        assert "can't check the fit" in result['headline']

    def test_a_template_that_declares_nothing_is_unknown(self, app, server):
        _sample(server.id, memory_used=1 * GB, disk_used=10 * GB)
        result = check_fit({'id': 'x'}, server.id)
        assert result['verdict'] == 'unknown'
        assert 'does not declare' in result['detail']

    def test_unknown_outranks_ok(self, app, server):
        # Memory is fine, disk unknown (template declares no storage): the
        # honest overall answer is "we don't know", not "fits comfortably".
        _sample(server.id, memory_used=1 * GB, disk_used=10 * GB)
        result = check_fit(_template('512MB', None), server.id)
        assert result['verdict'] == 'unknown'

    def test_a_missing_server_does_not_explode(self, app):
        result = check_fit(_template(), 'no-such-server')
        assert result['verdict'] == 'unknown'

    def test_stale_readings_are_flagged_but_still_used(self, app, server):
        _sample(server.id, memory_used=1 * GB, disk_used=10 * GB, age_minutes=45)
        result = check_fit(_template('512MB', '1GB'), server.id)
        assert result['server']['stale'] is True
        assert 'more than 15 minutes old' in result['detail']
        assert result['verdict'] == 'ok'

    def test_disk_total_is_derived_when_the_row_never_got_one(self, app):
        # Agents report the percentage even when the absolute total is absent;
        # a disk check that silently does nothing is worse.
        row = Server(id='srv-cap-2', name='no-total', status='online',
                     total_memory=4 * GB, total_disk=None)
        db.session.add(row)
        db.session.commit()
        _sample(row.id, memory_used=1 * GB, disk_used=50 * GB, disk_percent=50.0)

        result = check_fit(_template('512MB', '1GB'), row.id)
        assert result['server']['disk_total'] == 100 * GB
        assert result['server']['disk_free'] == 50 * GB


class TestReserveMath:
    def test_reserve_has_a_floor_for_small_boxes(self, app):
        # 10% of 1 GB is 102 MB — too little to call healthy, so the floor
        # (256 MB) governs and this counts as tight.
        row = Server(id='srv-cap-3', name='tiny', status='online',
                     total_memory=1 * GB, total_disk=20 * GB)
        db.session.add(row)
        db.session.commit()
        _sample(row.id, memory_used=1 * GB - 600 * MB, disk_used=1 * GB)

        result = check_fit(_template('400MB', '1GB'), row.id)
        memory = next(c for c in result['checks'] if c['resource'] == 'memory')
        assert memory['reserve'] == capacity_service.MEMORY_RESERVE_MIN
        assert result['verdict'] == 'tight'

    def test_reserve_scales_up_on_a_big_box(self, app):
        row = Server(id='srv-cap-4', name='big', status='online',
                     total_memory=64 * GB, total_disk=1000 * GB)
        db.session.add(row)
        db.session.commit()
        _sample(row.id, memory_used=1 * GB, disk_used=1 * GB)

        result = check_fit(_template('1GB', '1GB'), row.id)
        memory = next(c for c in result['checks'] if c['resource'] == 'memory')
        assert memory['reserve'] == int(64 * GB * capacity_service.MEMORY_RESERVE_FRACTION)


class TestEndpoint:
    def _seed_admin(self):
        from app.models import User
        from werkzeug.security import generate_password_hash
        user = User(email='cap@test.local', username='cap_admin',
                    password_hash=generate_password_hash('x'),
                    role=User.ROLE_ADMIN, is_active=True)
        db.session.add(user)
        db.session.commit()
        return user

    def test_validate_install_reports_capacity(self, app, client, auth_headers, server):
        _sample(server.id, memory_used=1 * GB, disk_used=10 * GB)

        res = client.post('/api/v1/templates/validate-install', headers=auth_headers,
                          json={'template_id': 'actualbudget', 'app_name': 'budget-app',
                                'server_id': server.id})

        assert res.status_code == 200
        body = res.get_json()
        assert body['valid'] is True
        assert body['capacity']['verdict'] in ('ok', 'tight', 'insufficient', 'unknown')
        assert body['capacity']['blocking'] is False

    def test_a_full_server_still_validates(self, app, client, auth_headers, server):
        # The install is allowed; the operator is merely told. If this ever
        # starts returning 400, the feature has become a gate.
        _sample(server.id, memory_used=4 * GB, disk_used=100 * GB)

        res = client.post('/api/v1/templates/validate-install', headers=auth_headers,
                          json={'template_id': 'jenkins', 'app_name': 'ci-box',
                                'server_id': server.id})

        assert res.status_code == 200
        assert res.get_json()['capacity']['verdict'] == 'insufficient'

    def test_capacity_is_omitted_rather_than_faked_without_a_template(
            self, app, client, auth_headers):
        res = client.post('/api/v1/templates/validate-install', headers=auth_headers,
                          json={'app_name': 'x'})
        assert res.status_code == 400
        assert res.get_json()['capacity'] is None

    def test_capacity_endpoint_answers_for_a_server(self, app, client, auth_headers, server):
        # The drawer reads this while the operator is still choosing a target,
        # so it must work without an app name or any form state.
        _sample(server.id, memory_used=1 * GB, disk_used=10 * GB)

        res = client.get(f'/api/v1/templates/actualbudget/capacity?server_id={server.id}',
                         headers=auth_headers)

        assert res.status_code == 200
        body = res.get_json()
        assert body['verdict'] == 'ok'
        assert body['server']['name'] == 'box'
        assert body['requirements']['memory'] == 512 * MB

    def test_capacity_endpoint_defaults_to_this_host(self, app, client, auth_headers):
        # No server_id means the panel's own machine, which is the common case
        # for a single-server install.
        res = client.get('/api/v1/templates/actualbudget/capacity', headers=auth_headers)

        assert res.status_code == 200
        assert res.get_json()['server']['source'] == 'local'

    def test_capacity_endpoint_404s_for_an_unknown_template(self, app, client, auth_headers):
        res = client.get('/api/v1/templates/no-such-template/capacity', headers=auth_headers)
        assert res.status_code == 404

    def test_capacity_endpoint_needs_auth(self, app, client):
        res = client.get('/api/v1/templates/actualbudget/capacity')
        assert res.status_code == 401


class TestAttachedVolumes:
    """A disk shortfall on ONE filesystem is not "no room" on a box with a
    volume attached — the app's data can live there. Red must mean the whole
    box is short, not that the measured mountpoint is."""

    @staticmethod
    def _headroom(disk_free, other_mounts, memory_free=6 * GB):
        return {'server_id': None, 'name': 'This server', 'source': 'local',
                'measured_at': '2026-08-28T00:00:00Z', 'stale': False,
                'memory_total': 8 * GB, 'memory_free': memory_free,
                'disk_total': 25 * GB, 'disk_free': disk_free,
                'disk_mountpoint': '/', 'other_mounts': other_mounts}

    def test_a_volume_with_room_downgrades_wont_fit_to_tight(self, app, monkeypatch):
        # The reported bug: 20 GB storage vs 10 GB free on root read as a red
        # "doesn't have room" while an 80 GB volume sat attached and empty.
        monkeypatch.setattr(capacity_service, 'server_headroom',
                            lambda server_id=None: self._headroom(
                                10 * GB,
                                [{'mountpoint': '/mnt/volume1',
                                  'free': 80 * GB, 'total': 100 * GB}]))
        result = check_fit(_template('4GB', '20GB'))
        assert result['verdict'] == 'tight'
        assert 'attached volume' in result['headline']
        assert '/mnt/volume1' in result['detail']
        assert "point the app's data there" in result['detail']
        disk = next(c for c in result['checks'] if c['resource'] == 'disk')
        assert disk['alt_mountpoint'] == '/mnt/volume1'
        assert disk['alt_free'] == 80 * GB

    def test_a_volume_too_small_does_not_rescue(self, app, monkeypatch):
        monkeypatch.setattr(capacity_service, 'server_headroom',
                            lambda server_id=None: self._headroom(
                                10 * GB,
                                [{'mountpoint': '/mnt/volume1',
                                  'free': 15 * GB, 'total': 100 * GB}]))
        result = check_fit(_template('4GB', '20GB'))
        assert result['verdict'] == 'insufficient'
        assert 'more disk than it has free' in result['detail']

    def test_memory_has_no_escape_hatch(self, app, monkeypatch):
        # A volume holds files, not processes; a memory shortfall stays red.
        monkeypatch.setattr(capacity_service, 'server_headroom',
                            lambda server_id=None: self._headroom(
                                22 * GB,
                                [{'mountpoint': '/mnt/volume1',
                                  'free': 80 * GB, 'total': 100 * GB}],
                                memory_free=2 * GB))
        result = check_fit(_template('4GB', '20GB'))
        assert result['verdict'] == 'insufficient'

    def test_local_headroom_reports_the_other_mounts(self, app, monkeypatch):
        from collections import namedtuple
        from app.services import host_inventory_service
        Usage = namedtuple('Usage', 'total used free percent')
        monkeypatch.setattr(host_inventory_service, 'data_path_usage',
                            lambda: ('/', Usage(25 * GB, 15 * GB, 10 * GB, 60.0)))
        monkeypatch.setattr(host_inventory_service, 'enumerate_filesystems',
                            lambda: [
                                {'mountpoint': '/', 'device': '/dev/vda1',
                                 'free': 10 * GB, 'total': 25 * GB},
                                {'mountpoint': '/mnt/volume1', 'device': '/dev/sda',
                                 'free': 80 * GB, 'total': 100 * GB},
                            ])
        headroom = capacity_service.server_headroom(None)
        # The measured mountpoint is excluded — it is already `disk_free`.
        assert headroom['other_mounts'] == [
            {'mountpoint': '/mnt/volume1', 'free': 80 * GB, 'total': 100 * GB}]


class TestLocalHost:
    def test_reads_the_panel_host_live(self, app):
        # The single-server case: no agent, no metrics row, psutil instead —
        # so `measured_at` is always now and nothing can go stale.
        headroom = capacity_service.server_headroom(None)
        assert headroom['source'] == 'local'
        assert headroom['stale'] is False
        assert headroom['memory_total'] > 0
        assert 0 < headroom['memory_free'] <= headroom['memory_total']

    def test_local_and_explicit_local_agree(self, app):
        assert (capacity_service.server_headroom('local')['source']
                == capacity_service.server_headroom(None)['source'])

    def test_a_real_template_fits_this_machine(self, app):
        from app.services.template_service import TemplateService

        template = TemplateService.get_template('actualbudget')['template']
        result = check_fit(template, None)
        # Whatever the verdict, the shape the drawer renders must be complete.
        assert result['verdict'] in ('ok', 'tight', 'insufficient', 'unknown')
        assert result['requirements']['memory'] == 512 * MB
        assert result['headline'] and result['detail']
