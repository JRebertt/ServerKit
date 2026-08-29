"""WordPress shared-state and edge-protection contracts."""
from pathlib import Path
from types import SimpleNamespace

import yaml

from app.services.nginx_service import NginxService
from app.services.site_domain_service import SiteDomainService
from subprocess_stub import FakeProc


def _wordpress_template():
    repo_root = Path(__file__).resolve().parents[2]
    return yaml.safe_load((repo_root / 'backend' / 'templates' / 'wordpress.yaml').read_text())


def _tee_to_disk(fake):
    def write(argv, kwargs):
        path = Path(argv[2] if argv[1] == '-a' else argv[1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(kwargs.get('input', ''))
        return FakeProc()

    fake.when(['tee'], write)


def test_wordpress_template_shares_the_full_site_tree_between_replicas():
    compose = _wordpress_template()['compose']
    wordpress = compose['services']['wordpress']

    assert 'wordpress_html:/var/www/html' in wordpress['volumes']
    assert 'wordpress_html' in compose['volumes']


def test_wordpress_protection_adds_exact_login_and_xmlrpc_limits():
    result = NginxService.render_site_config(
        'blog',
        'docker',
        ['blog.example.com'],
        port=8300,
        wordpress_protection=True,
    )

    assert result['success'] is True
    config = result['config']
    assert 'location = /wp-login.php {' in config
    assert 'limit_req zone=serverkit_wp_login burst=10 nodelay;' in config
    assert 'location = /xmlrpc.php {' in config
    assert 'limit_req zone=serverkit_wp_xmlrpc burst=20 nodelay;' in config
    assert config.count('proxy_pass http://127.0.0.1:8300;') == 3
    assert config.index('location = /wp-login.php') < config.index('location / {')


def test_generic_docker_vhost_has_no_wordpress_limits():
    result = NginxService.render_site_config(
        'api',
        'docker',
        ['api.example.com'],
        port=8400,
    )

    assert result['success'] is True
    assert 'serverkit_wp_login' not in result['config']
    assert 'serverkit_wp_xmlrpc' not in result['config']


def test_wordpress_rate_limit_zones_are_partitioned_by_site_and_client():
    snippet = NginxService.WORDPRESS_RATE_LIMIT_ZONE_SNIPPET

    assert snippet.count('$server_name$binary_remote_addr') == 2
    assert 'zone=serverkit_wp_login:10m rate=10r/m;' in snippet
    assert 'zone=serverkit_wp_xmlrpc:10m rate=30r/m;' in snippet


def test_wordpress_rate_limit_zone_write_is_idempotent(
        tmp_path, fake_subprocess, monkeypatch):
    conf_dir = tmp_path / 'nginx'
    monkeypatch.setattr(NginxService, 'NGINX_CONF_DIR', str(conf_dir))
    _tee_to_disk(fake_subprocess)

    first = NginxService.ensure_wordpress_rate_limit_zones()
    second = NginxService.ensure_wordpress_rate_limit_zones()

    assert first['success'] is True and first['changed'] is True
    assert second['success'] is True and second['changed'] is False
    conf_path = conf_dir / 'conf.d' / NginxService.WORDPRESS_RATE_LIMIT_CONF_NAME
    assert conf_path.read_text() == NginxService.WORDPRESS_RATE_LIMIT_ZONE_SNIPPET
    assert len([c for c in fake_subprocess.commands() if c[0] == 'tee']) == 1


def test_create_wordpress_vhost_installs_zones_before_write(monkeypatch):
    events = []
    monkeypatch.setattr(
        NginxService,
        'ensure_wordpress_rate_limit_zones',
        classmethod(lambda cls: events.append('zones') or {'success': True}),
    )
    monkeypatch.setattr(
        NginxService,
        'write_vhost',
        classmethod(lambda cls, name, content: events.append('vhost') or {
            'success': True,
            'path': f'/etc/nginx/sites-available/{name}',
        }),
    )

    result = NginxService.create_site(
        'blog',
        'docker',
        ['blog.example.com'],
        port=8300,
        wordpress_protection=True,
    )

    assert result['success'] is True
    assert events == ['zones', 'vhost']


def test_wordpress_template_application_enables_protection():
    app = SimpleNamespace(
        name='blog',
        app_type='docker',
        port=8300,
        docker_image='WordPress',
        micro_cache_enabled=False,
    )

    kwargs, warning = SiteDomainService._vhost_create_kwargs(
        app,
        ['blog.example.com'],
        None,
        None,
    )

    assert warning is None
    assert kwargs['app_type'] == 'docker'
    assert kwargs['wordpress_protection'] is True


def test_generic_docker_application_does_not_enable_wordpress_protection():
    app = SimpleNamespace(
        name='api',
        app_type='docker',
        port=8400,
        docker_image='nginx',
        micro_cache_enabled=False,
    )

    kwargs, warning = SiteDomainService._vhost_create_kwargs(
        app,
        ['api.example.com'],
        None,
        None,
    )

    assert warning is None
    assert kwargs['wordpress_protection'] is False


def test_existing_wordpress_site_drift_target_includes_protection(app):
    from app import db
    from app.models.domain import Domain
    from app.services.drift_service import _nginx_render_expected
    from tests.factories import make_application

    wordpress = make_application(
        db,
        name='existing-wp',
        status='running',
        root_path='/srv/existing-wp',
        docker_image='WordPress',
        port=8500,
    )
    db.session.add(Domain(
        name='existing-wp.example.com',
        is_primary=True,
        application_id=wordpress.id,
    ))
    db.session.commit()

    expected = _nginx_render_expected(wordpress.id)

    [config] = expected.values()
    assert 'limit_req zone=serverkit_wp_login burst=10 nodelay;' in config
    assert 'limit_req zone=serverkit_wp_xmlrpc burst=20 nodelay;' in config
