"""Ownership registry for raw ``threading.Thread`` call sites.

Raw threads are allowed only when their lifecycle is intentionally coupled to
the process/request or when a persisted parent operation already owns recovery.
Bounded user work that needs restart recovery, retries, or global observability
belongs in :class:`app.jobs.service.JobService` instead.

``backend/tests/test_thread_ownership.py`` keeps this registry exact: adding or
removing a raw thread requires an explicit lifecycle decision here.
"""

LIFECYCLE_PROCESS_LOOP = 'process_loop'
LIFECYCLE_REQUEST_STREAM = 'request_stream'
LIFECYCLE_BOUNDED_DELIVERY = 'bounded_delivery'
LIFECYCLE_BOUNDED_FANOUT = 'bounded_fanout'
LIFECYCLE_DURABLE_CANDIDATE = 'durable_candidate'


THREAD_OWNERSHIP = {
    'app/api/ai.py:chat_stream:producer': {
        'owner': 'AI SSE response',
        'lifecycle': LIFECYCLE_REQUEST_STREAM,
        'rationale': 'Producer lifetime is coupled to one streaming HTTP response.',
    },
    'app/jobs/consumer.py:start:self._run': {
        'owner': 'unified job runtime',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'The process-level consumer is the executor for durable jobs.',
    },
    'app/jobs/scheduler.py:start:self._run': {
        'owner': 'unified job runtime',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'The process-level ticker publishes persisted scheduled jobs.',
    },
    'app/middleware/api_analytics.py:start_analytics_flush_thread:flush_loop': {
        'owner': 'API analytics middleware',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Flushes an in-memory request metrics buffer owned by this process.',
    },
    'app/notifications/consumer.py:start:self._run': {
        'owner': 'notification queue',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Long-lived consumer for already-persisted notification messages.',
    },
    'app/plugins/serverkit-analytics/ingest_service.py:ensure_flush_thread:_flush_loop': {
        'owner': 'analytics extension ingest',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Flushes an in-memory analytics batch owned by this process.',
    },
    'app/queue_bus/consumers/webhook_consumer.py:start:self._run': {
        'owner': 'webhook queue',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Long-lived consumer for persisted webhook messages.',
    },
    'app/services/agent_fleet_service.py:staged_rollout:self._run_staged_rollout': {
        'owner': 'agent fleet rollout',
        'lifecycle': LIFECYCLE_DURABLE_CANDIDATE,
        'rationale': 'User-triggered bounded rollout; migrate after restart/resume semantics are specified.',
    },
    'app/services/agent_fleet_service.py:retry_command:self._deliver_single_command': {
        'owner': 'agent command delivery',
        'lifecycle': LIFECYCLE_BOUNDED_DELIVERY,
        'rationale': 'Low-latency delivery attempt is owned and recoverable by its persisted command row.',
    },
    'app/services/agent_fleet_service.py:upgrade_servers:dispatch_agent_command': {
        'owner': 'agent fleet upgrade',
        'lifecycle': LIFECYCLE_BOUNDED_FANOUT,
        'rationale': 'Parallel delivery fan-out creates persisted agent command state.',
    },
    'app/services/agent_fleet_service.py:deliver_queued_commands:self._deliver_single_command': {
        'owner': 'agent command delivery',
        'lifecycle': LIFECYCLE_BOUNDED_DELIVERY,
        'rationale': 'Delivery attempt is selected from and recorded in the persisted command queue.',
    },
    'app/services/agent_fleet_service.py:process_scheduled_retries:self._deliver_single_command': {
        'owner': 'agent command retry',
        'lifecycle': LIFECYCLE_BOUNDED_DELIVERY,
        'rationale': 'Retry attempt is scheduled and tracked by the persisted command row.',
    },
    'app/services/agent_registry.py:_start_heartbeat_checker:self._check_heartbeats': {
        'owner': 'agent registry',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Long-lived liveness checker for connected agents.',
    },
    'app/services/anomaly_detection_service.py:__init__:self._cleanup_loop': {
        'owner': 'anomaly detector',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Maintains process-local anomaly detector state and retention.',
    },
    'app/services/discovery_service.py:start_scan:self._listen_for_responses': {
        'owner': 'LAN discovery session',
        'lifecycle': LIFECYCLE_REQUEST_STREAM,
        'rationale': 'Bounded UDP listener belongs to one active discovery window.',
    },
    'app/services/environment_health_service.py:_dispatch_health_alert:_send': {
        'owner': 'environment health alerts',
        'lifecycle': LIFECYCLE_DURABLE_CANDIDATE,
        'rationale': 'Alert delivery should move to the notification queue after deduplication is defined.',
    },
    'app/services/linked_panel_agent.py:start:self._run': {
        'owner': 'linked-panel agent',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Long-lived poll loop maintaining the linked-panel connection.',
    },
    'app/services/linked_panel_agent.py:_poll_loop:self._dispatch': {
        'owner': 'linked-panel dispatch',
        'lifecycle': LIFECYCLE_BOUNDED_DELIVERY,
        'rationale': 'Parallel dispatch prevents one remote request from blocking the poll loop.',
    },
    'app/services/log_service.py:start_stream:LogService.tail_log': {
        'owner': 'log stream session',
        'lifecycle': LIFECYCLE_REQUEST_STREAM,
        'rationale': 'Tail lifetime is coupled to a caller-provided stop event.',
    },
    'app/services/metrics_history_service.py:start_collection:collection_loop': {
        'owner': 'metrics history collector',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Long-lived host metrics sampler.',
    },
    'app/services/monitoring_service.py:start_monitoring:cls._monitor_loop': {
        'owner': 'legacy monitoring runtime',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Long-lived monitor loop; periodic migration is separate from one-shot work.',
    },
    'app/services/nonce_service.py:__init__:self._cleanup_loop': {
        'owner': 'nonce store',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Expires process-local nonce state.',
    },
    'app/services/security_service.py:scan_directory:cls._run_directory_scan': {
        'owner': 'legacy ClamAV directory scan',
        'lifecycle': LIFECYCLE_DURABLE_CANDIDATE,
        'rationale': 'Compatibility endpoint remains; new callers should use security.malware_scan jobs.',
    },
    'app/services/test_sandbox_service.py:start_run:cls._execute': {
        'owner': 'test sandbox run',
        'lifecycle': LIFECYCLE_DURABLE_CANDIDATE,
        'rationale': 'Persisted user run should become a job after cancellation is made job-aware.',
    },
    'app/services/test_sandbox_service.py:_execute:cls._run_distro': {
        'owner': 'test sandbox run',
        'lifecycle': LIFECYCLE_BOUNDED_FANOUT,
        'rationale': 'Parallel distro workers are children of one persisted sandbox run.',
    },
    'app/services/uptime_service.py:start_tracking:cls._tracking_loop': {
        'owner': 'uptime tracker',
        'lifecycle': LIFECYCLE_PROCESS_LOOP,
        'rationale': 'Long-lived uptime sampler.',
    },
    'app/sockets.py:handle_subscribe_logs:emit_logs': {
        'owner': 'Socket.IO log subscription',
        'lifecycle': LIFECYCLE_REQUEST_STREAM,
        'rationale': 'Emitter lifetime is coupled to one socket subscription.',
    },
    'app/sockets.py:handle_subscribe_container_logs:stream_logs': {
        'owner': 'Socket.IO container log subscription',
        'lifecycle': LIFECYCLE_REQUEST_STREAM,
        'rationale': 'Emitter lifetime is coupled to one socket subscription.',
    },
    'app/sockets.py:handle_subscribe_metrics:broadcast_metrics': {
        'owner': 'Socket.IO metrics subscription',
        'lifecycle': LIFECYCLE_REQUEST_STREAM,
        'rationale': 'Broadcaster lifetime is coupled to an active socket subscription set.',
    },
    'app/sockets.py:handle_subscribe_container_status:broadcast_container_status': {
        'owner': 'Socket.IO container status subscription',
        'lifecycle': LIFECYCLE_REQUEST_STREAM,
        'rationale': 'Broadcaster lifetime is coupled to an active socket subscription set.',
    },
}


MIGRATED_TO_JOBS = {
    'ImageScannerService.scan_application': 'security.image_scan',
    'SecurityService.run_lynis_scan': 'security.lynis_scan',
}

