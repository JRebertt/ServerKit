// Shared wire-protocol constants (plan 77 E3).
//
// This table mirrors backend/app/constants.py::SOCKET_EVENTS verbatim — a
// backend test (tests/test_socket_contract.py) parses this file and fails
// when the two drift, so a renamed event can never fail silently. Add or
// rename events in BOTH files.

export const SOCKET_EVENTS = {
    // lifecycle / control plane
    CONNECTED: 'connected',
    ERROR: 'error',
    SUBSCRIBED: 'subscribed',
    UNSUBSCRIBED: 'unsubscribed',
    JOINED: 'joined',
    LEFT: 'left',

    // broadcast channels
    METRICS: 'metrics',
    CONTAINER_STATUS: 'container_status',
    NOTIFICATION: 'notification',

    // file log streaming
    LOG_LINE: 'log_line',
    LOG_ERROR: 'log_error',

    // deploy console (legacy names, dual-emitted with the run envelope)
    DEPLOY_LOG: 'deploy_log',
    DEPLOY_STATUS: 'deploy_status',

    // generalized run envelope (plan 77 E1) — one event pair for every run kind
    RUN_LOG: 'run_log',
    RUN_STATUS: 'run_status',

    // container log streaming
    CONTAINER_LOG: 'container_log',
    CONTAINER_LOG_ERROR: 'container_log_error',
    CONTAINER_LOG_ENDED: 'container_log_ended',

    // agent stream rebroadcast (metrics / PTY / arbitrary channels)
    SERVER_STREAM: 'server_stream',
};

// Room-name builders — the same grammar as backend/app/sockets_rooms.py.
// Never assemble a room string inline in a component; a typo'd segment is a
// silently dead stream.

export const rooms = {
    serverChannel: (serverId, channel) => `server_${serverId}_${channel}`,
    deploy: (jobId) => `deploy_${jobId}`,
    run: (kind, runId) => `run_${kind}_${runId}`,
    appLogs: (appId) => `logs_${appId}`,
    serverTerminal: (serverId, sessionId) => `server_${serverId}_terminal:${sessionId}`,
};
