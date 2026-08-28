"""Config-injection validation in the advanced nginx builder.

``create_reverse_proxy`` interpolates domains, upstreams, headers and
locations straight into a generated vhost. A ``;`` or ``}`` in any of them
closes the directive being written and starts an attacker-chosen one — and
the builder writes through ``write_vhost``, which config-tests and reloads,
so an injected-but-valid fragment would go live. Every interpolated value is
now validated first; these tests pin both the rejections and the clean path.
"""

import pytest

from app.services.nginx_advanced_service import NginxAdvancedService
from app.services.nginx_service import NginxService


@pytest.fixture
def written(monkeypatch):
    """write_vhost seam: captures what the builder tried to write."""
    captured = {}

    def fake_write(name, content, *, enable=True):
        captured['name'] = name
        captured['content'] = content
        return {'success': True, 'path': f'/etc/nginx/sites-available/{name}'}

    monkeypatch.setattr(NginxService, 'write_vhost', staticmethod(fake_write))
    return captured


def _clean_payload():
    return {
        'domain': 'shop.example.com',
        'upstreams': [{'address': '127.0.0.1:8001', 'weight': 2}],
        'lb_method': 'least_conn',
        'rate_limit': {'enabled': True, 'requests_per_second': 5, 'burst': 10},
        'cache': {'enabled': True, 'size': '100m', 'ttl': '60m',
                  'bypass_rules': ['$http_authorization']},
        'headers': {'add': {'X-Frame-Options': 'DENY'},
                    'remove': ['X-Powered-By']},
        'locations': [{'path': '/api', 'proxy_pass': 'http://127.0.0.1:9000'}],
    }


class TestCleanPayload:
    def test_a_clean_payload_builds_and_writes(self, written):
        res = NginxAdvancedService.create_reverse_proxy(_clean_payload())

        assert 'error' not in res
        assert written['name'] == 'shop.example.com'
        config = written['content']
        assert 'upstream shop_example_com {' in config
        assert 'least_conn;' in config
        assert 'server 127.0.0.1:8001 weight=2;' in config
        assert 'server_name shop.example.com;' in config
        assert 'add_header X-Frame-Options "DENY";' in config
        assert 'proxy_hide_header X-Powered-By;' in config
        assert 'location /api {' in config
        assert 'proxy_pass http://127.0.0.1:9000;' in config

    def test_a_unix_socket_upstream_is_accepted(self, written):
        payload = _clean_payload()
        payload['upstreams'] = [{'address': 'unix:/run/app.sock'}]
        res = NginxAdvancedService.create_reverse_proxy(payload)
        assert 'error' not in res
        assert 'server unix:/run/app.sock;' in written['content']

    def test_a_regex_location_is_accepted(self, written):
        payload = _clean_payload()
        payload['locations'] = [{'path': '~ \\.php$', 'proxy_pass': 'http://127.0.0.1:9000'}]
        res = NginxAdvancedService.create_reverse_proxy(payload)
        assert 'error' not in res


class TestInjectionIsRefused:
    """Each payload has exactly one poisoned value; the builder must refuse
    it and write nothing."""

    @pytest.mark.parametrize('mutate,fragment', [
        (lambda p: p.update(domain='example.com; } server {'), 'domain'),
        (lambda p: p.update(domain='--bogus'), 'domain'),
        (lambda p: p.update(lb_method='least_conn; }'), 'lb_method'),
        (lambda p: p['upstreams'][0].update(address='127.0.0.1:8001; } server {'), 'upstream'),
        (lambda p: p['upstreams'][0].update(address='not-a-socket'), 'upstream'),
        (lambda p: p['upstreams'][0].update(weight='2; drop'), 'weight'),
        (lambda p: p['upstreams'][0].update(weight=0), 'weight'),
        (lambda p: p['rate_limit'].update(requests_per_second='5; x'), 'requests_per_second'),
        (lambda p: p['rate_limit'].update(burst=-1), 'burst'),
        (lambda p: p['cache'].update(size='100m; }'), 'size'),
        (lambda p: p['cache'].update(ttl='60m 0'), 'ttl'),
        (lambda p: p['cache'].update(bypass_rules=['$http_x; }']), 'bypass'),
        (lambda p: p['headers']['add'].update({'X-Test"; add_header X-Evil "1': 'v'}), 'header name'),
        (lambda p: p['headers']['add'].update(
            {'X-Frame-Options': 'DENY"; add_header X-Evil "1'}), 'header value'),
        (lambda p: p['headers']['add'].update({'X-Frame-Options': 'line1\nline2'}), 'header newline'),
        (lambda p: p['headers'].update(remove=['X-Powered-By;']), 'remove header'),
        (lambda p: p['locations'][0].update(path='/api; return 200;'), 'location path'),
        (lambda p: p['locations'][0].update(path='/api { deny all; }'), 'location brace'),
        (lambda p: p['locations'][0].update(proxy_pass='http://127.0.0.1:9000; return 200'), 'proxy_pass'),
        (lambda p: p['locations'][0].update(proxy_pass='file:///etc/passwd'), 'proxy_pass scheme'),
    ])
    def test_a_poisoned_value_is_refused_and_nothing_is_written(
            self, written, mutate, fragment):
        payload = _clean_payload()
        mutate(payload)

        res = NginxAdvancedService.create_reverse_proxy(payload)

        assert 'error' in res, f'{fragment} injection was accepted'
        assert written == {}, f'{fragment} injection still reached write_vhost'
