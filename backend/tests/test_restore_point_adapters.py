"""Core restore-point adapter registration contract."""


def test_app_factory_registers_every_builtin_restore_surface(app):
    from app.services.restore_point_service import get_adapter

    assert {
        scope for scope in ('cron', 'dns', 'env', 'firewall', 'nginx_vhost')
        if get_adapter(scope) is not None
    } == {'cron', 'dns', 'env', 'firewall', 'nginx_vhost'}
