"""PHP-FPM pool name/version guards + honest unreadable pools (plan 82 §F.3).

version and pool_name both come straight from the URL into a filesystem path
handed to privileged write/rm — a traversal pool_name reached
``run_privileged(['rm', <escaped path>])``. And an unreadable pool file used
to list as ``user: www-data, pm: dynamic`` — fabricated defaults, not the
honest unknown (the probe-honesty house rule).
"""
import pytest

from app.services.php_service import PHPService


class TestPathGuards:
    def test_create_rejects_traversal_pool_name(self):
        res = PHPService.create_pool('8.2', '../../etc/cron.d/evil', {})
        assert res['success'] is False
        assert 'invalid pool name' in res['error']

    def test_delete_rejects_traversal_pool_name(self):
        res = PHPService.delete_pool('8.2', '../www')
        assert res['success'] is False
        assert 'invalid pool name' in res['error']

    def test_rejects_traversal_version(self):
        res = PHPService.delete_pool('8.2/../..', 'www2')
        assert res['success'] is False
        assert 'invalid PHP version' in res['error']

    @pytest.mark.parametrize('bad', ['', 'a/b', 'a\\b', '.hidden', '..',
                                     'name with space', 'a;b'])
    def test_rejects_malformed_pool_names(self, bad):
        path, error = PHPService._pool_file('8.2', bad)
        assert path is None and 'invalid pool name' in error

    @pytest.mark.parametrize('good', ['www2', 'my-app', 'my_app', 'my.site',
                                      'App9'])
    def test_accepts_conventional_pool_names(self, good):
        path, error = PHPService._pool_file('8.2', good)
        assert error is None
        assert path == f'/etc/php/8.2/fpm/pool.d/{good}.conf'


class TestHonestParsing:
    def test_unreadable_pool_lists_as_unknown_not_defaults(self, tmp_path, monkeypatch):
        pool_dir = tmp_path / 'pool.d'
        pool_dir.mkdir()
        (pool_dir / 'ok.conf').write_text('[ok]\nuser = deploy\npm = static\n')
        monkeypatch.setattr(PHPService, '_parse_pool_config',
                            classmethod(lambda cls, p:
                                        None if p.endswith('broken.conf')
                                        else {'user': 'deploy', 'pm': 'static'}))
        (pool_dir / 'broken.conf').write_text('')

        monkeypatch.setattr(PHPService, '_pool_dir',
                            classmethod(lambda cls, v: (str(pool_dir), None)))
        pools = {p['name']: p for p in PHPService.get_pools('8.2')}

        assert pools['ok']['user'] == 'deploy'
        assert pools['broken']['unreadable'] is True
        assert pools['broken']['user'] is None      # not 'www-data'
        assert pools['broken']['pm'] is None        # not 'dynamic'

    def test_parse_returns_none_for_missing_file(self, tmp_path):
        assert PHPService._parse_pool_config(str(tmp_path / 'nope.conf')) is None

    def test_parse_reads_real_file(self, tmp_path):
        f = tmp_path / 'p.conf'
        f.write_text('[p]\n; comment\nuser = deploy\npm.max_children = 12\n')
        cfg = PHPService._parse_pool_config(str(f))
        assert cfg == {'user': 'deploy', 'pm.max_children': '12'}
