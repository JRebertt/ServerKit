"""Shared wire-protocol constants (plan 77 E3).

``SOCKET_EVENTS`` is mirrored verbatim by ``frontend/src/constants/events.js``
so a renamed event cannot fail silently — ``tests/test_socket_contract.py``
parses the JS file and asserts the two tables are identical. Add or rename an
event in BOTH files (the test tells you when you forgot).
"""

SOCKET_EVENTS = {
    # lifecycle / control plane
    'CONNECTED': 'connected',
    'ERROR': 'error',
    'SUBSCRIBED': 'subscribed',
    'UNSUBSCRIBED': 'unsubscribed',
    'JOINED': 'joined',
    'LEFT': 'left',

    # broadcast channels
    'METRICS': 'metrics',
    'CONTAINER_STATUS': 'container_status',
    'NOTIFICATION': 'notification',

    # file log streaming
    'LOG_LINE': 'log_line',
    'LOG_ERROR': 'log_error',

    # deploy console (legacy names, dual-emitted with the run envelope)
    'DEPLOY_LOG': 'deploy_log',
    'DEPLOY_STATUS': 'deploy_status',

    # generalized run envelope (plan 77 E1) — one event pair for every run kind
    'RUN_LOG': 'run_log',
    'RUN_STATUS': 'run_status',

    # container log streaming
    'CONTAINER_LOG': 'container_log',
    'CONTAINER_LOG_ERROR': 'container_log_error',
    'CONTAINER_LOG_ENDED': 'container_log_ended',

    # agent stream rebroadcast (metrics / PTY / arbitrary channels)
    'SERVER_STREAM': 'server_stream',
}
