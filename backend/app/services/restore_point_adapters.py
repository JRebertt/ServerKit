"""Registration for the restore-point adapters shipped by core."""


def register_builtin_restore_point_adapters():
    """Register core surfaces on every app-factory invocation.

    Registration is deliberately idempotent: tests and plugin reloads may
    rebuild the Flask app in the same process, and replacing an adapter with
    the same module is harmless.
    """
    from app.services import (
        restore_point_adapter_cron,
        restore_point_adapter_dns,
        restore_point_adapter_env,
        restore_point_adapter_firewall,
        restore_point_adapter_nginx,
        restore_point_service,
    )

    adapters = {
        'cron': restore_point_adapter_cron,
        'dns': restore_point_adapter_dns,
        'env': restore_point_adapter_env,
        'firewall': restore_point_adapter_firewall,
        'nginx_vhost': restore_point_adapter_nginx,
    }
    for scope_type, adapter in adapters.items():
        restore_point_service.register_adapter(scope_type, adapter)
    return adapters
