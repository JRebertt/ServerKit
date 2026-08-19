from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_jwt_extended import decode_token
from flask import request, current_app
import threading
import time
import queue

from app.services.system_service import SystemService
from app.services.log_service import LogService, LogStreamer
from app.services.docker_service import DockerService
from app import sockets_rooms as rooms
from app.utils.background_loop import BackgroundLoop

socketio = SocketIO()
log_streamer = LogStreamer()

# Store active metric subscriptions
metric_subscribers = set()

# Store active aggregated container-status subscriptions
container_status_subscribers = set()

# Store active container log streams
container_log_streams = {}  # sid -> {'process': Popen, 'app_id': int, 'thread': Thread, 'stop_event': Event}

# Authenticated identity per connected client. Populated at connect time
# (after the JWT is verified AND the user is confirmed active) and read by
# the room/subscription handlers to make authorization decisions. Without
# this, every handler only knew "the token decoded" — not who the user is or
# what role they hold — so a viewer could join a developer's live terminal
# room. Keyed by request.sid; cleaned up on disconnect. Guarded by a lock
# because async_mode='threading' runs handlers across worker threads.
connected_clients = {}  # sid -> {'user_id': ..., 'role': ...}
_connected_clients_lock = threading.Lock()

# Roles permitted to drive/observe privileged server surfaces (remote
# terminals). Mirrors the REST side, where terminal create/input/kill are
# @developer_required — viewing the live PTY stream must require the same.
_PRIVILEGED_ROLES = ('admin', 'developer')


def _client_role(sid):
    """Return the authenticated role for a connected socket, or None if the
    socket isn't in our authenticated set (shouldn't happen post-connect)."""
    with _connected_clients_lock:
        info = connected_clients.get(sid)
        return info['role'] if info else None


def _client_is_privileged(sid):
    """True when the connected socket belongs to an admin/developer — the
    roles allowed to attach to remote terminal streams."""
    return _client_role(sid) in _PRIVILEGED_ROLES


# ==================== DECLARATIVE CHANNEL REGISTRY (plan 77 E2) ====================
#
# Eight hand-rolled subscribe/unsubscribe pairs used four different registry
# shapes and re-checked auth inconsistently. register_channel() generates the
# pair with ONE auth model:
#   1. the socket must be in connected_clients (JWT verified at connect);
#   2. an optional per-channel `auth(sid, data)` gate returning an error
#      string (e.g. the terminal role gate) — None means allowed.
# Room names come from room_fn (built on app/sockets_rooms.py); channels with
# process-wide side effects (subscriber sets, broadcast loops) use
# on_subscribe/on_unsubscribe. The two remaining raw handlers
# (subscribe_logs / subscribe_container_logs, which own per-sid OS resources)
# are frozen by tests/test_socket_contract.py.


class ChannelError(Exception):
    """Raised by a room_fn to reject a subscribe with a client-visible message."""


CHANNELS = {}


def register_channel(name, *, room_fn=None, auth=None, on_subscribe=None,
                     on_unsubscribe=None, ack=None, ack_unsubscribe=True):
    """Register `subscribe_<name>` / `unsubscribe_<name>` handlers.

    Args:
        name: channel name; also the default ack payload's `channel` value.
        room_fn: callable(data) -> room name to join/leave (may raise
            ChannelError). None for broadcast channels with no room.
        auth: callable(sid, data) -> error string or None.
        on_subscribe / on_unsubscribe: callable(sid, data) side effects.
        ack: callable(data) -> extra dict merged into the subscribed /
            unsubscribed payloads.
        ack_unsubscribe: emit the `unsubscribed` ack (a couple of legacy
            channels never did — keep their wire behavior).
    """
    def _payload(data):
        payload = {'channel': name}
        if ack:
            payload.update(ack(data))
        return payload

    def _subscribe(data=None):
        data = data or {}
        sid = request.sid
        if sid not in connected_clients:
            emit('error', {'message': 'Authentication required'})
            return
        if auth:
            error = auth(sid, data)
            if error:
                emit('error', {'message': error})
                return
        room = None
        if room_fn:
            try:
                room = room_fn(data)
            except ChannelError as exc:
                emit('error', {'message': str(exc)})
                return
        if room:
            join_room(room)
        if on_subscribe:
            on_subscribe(sid, data)
        emit('subscribed', _payload(data))

    def _unsubscribe(data=None):
        data = data or {}
        sid = request.sid
        if room_fn:
            try:
                room = room_fn(data)
            except ChannelError:
                room = None
            if room:
                leave_room(room)
        if on_unsubscribe:
            on_unsubscribe(sid, data)
        if ack_unsubscribe:
            emit('unsubscribed', _payload(data))

    # Handlers are exposed on the registry so the contract tests can drive
    # them directly (the flask-socketio test client is incompatible with the
    # pinned Flask's immutable request context).
    CHANNELS[name] = {
        'room_fn': room_fn,
        'auth': auth,
        'subscribe': _subscribe,
        'unsubscribe': _unsubscribe,
    }
    socketio.on_event(f'subscribe_{name}', _subscribe)
    socketio.on_event(f'unsubscribe_{name}', _unsubscribe)


def init_socketio(app):
    """Initialize SocketIO with the Flask app."""
    socketio.init_app(
        app,
        cors_allowed_origins=app.config.get('CORS_ORIGINS', '*'),
        async_mode='threading'
    )
    return socketio


@socketio.on('connect')
def handle_connect(auth):
    """Handle client connection.

    Authenticates the socket and records the caller's identity + role so the
    per-room handlers can authorize. A token that merely decodes is NOT enough:
    we also confirm the user still exists and is active, then stash the role.
    A deactivated/deleted account whose JWT hasn't expired yet is rejected here
    rather than being allowed to keep streaming.
    """
    # Verify JWT token from auth payload (not query string, to avoid token leakage in logs)
    token = None
    if auth and isinstance(auth, dict):
        token = auth.get('token')

    if not token:
        emit('error', {'message': 'Token required'})
        return False

    try:
        decoded = decode_token(token)
    except Exception:
        emit('error', {'message': 'Invalid token'})
        return False

    # Resolve the identity to a live, active user. decode_token only proves the
    # token is well-formed and unexpired — it says nothing about whether the
    # account is still allowed in.
    from app.models import User
    user_id = decoded.get('sub')
    user = User.query.get(user_id) if user_id is not None else None
    if not user or not user.is_active:
        emit('error', {'message': 'Account not found or deactivated'})
        return False

    with _connected_clients_lock:
        connected_clients[request.sid] = {'user_id': user.id, 'role': user.role}

    # Join a per-user room so the Notification Bus can push in-app notifications
    # to every tab/device this user has open.
    join_room(rooms.user_room(user.id))

    emit('connected', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    sid = request.sid

    # Remove from metric subscribers
    if sid in metric_subscribers:
        metric_subscribers.remove(sid)

    # Remove from container-status subscribers
    if sid in container_status_subscribers:
        container_status_subscribers.remove(sid)

    # Stop any log streams for this client
    log_streamer.stop_stream(sid)

    # Stop any container log streams for this client
    stop_container_log_stream(sid)

    # Drop the authenticated-identity record for this socket.
    with _connected_clients_lock:
        connected_clients.pop(sid, None)


def _metrics_tick():
    metrics = SystemService.get_all_metrics()
    socketio.emit('metrics', metrics, room=None)  # Broadcast to all


# Ends itself when the last subscriber leaves; restarted by the next
# subscribe. Errors go to the logger and never kill the loop (E5).
metrics_loop = BackgroundLoop(
    'socket-metrics', 2, _metrics_tick,
    run_while=lambda: bool(metric_subscribers),
)


def _metrics_on_subscribe(sid, data):
    metric_subscribers.add(sid)
    metrics_loop.start()


def _metrics_on_unsubscribe(sid, data):
    metric_subscribers.discard(sid)


register_channel(
    'metrics',
    on_subscribe=_metrics_on_subscribe,
    on_unsubscribe=_metrics_on_unsubscribe,
)


# ==================== AGGREGATED CONTAINER STATUS ====================

def _container_status_tick():
    """Emit only the apps whose aggregated status changed since last tick.

    The aggregator keeps the last-emitted snapshot in memory; needs an app
    context because it touches the ORM (BackgroundLoop provides it).
    """
    from app.services import container_status_service as css
    changed = css.get_changed_app_statuses()
    if changed:
        socketio.emit('container_status', {
            'statuses': changed,
            'timestamp': time.time(),
        }, room=None)


container_status_loop = BackgroundLoop(
    'socket-container-status', 5, _container_status_tick,
    run_while=lambda: bool(container_status_subscribers),
)


def _container_status_on_subscribe(sid, data):
    container_status_subscribers.add(sid)
    container_status_loop.start(app=current_app._get_current_object())


def _container_status_on_unsubscribe(sid, data):
    container_status_subscribers.discard(sid)


register_channel(
    'container_status',
    on_subscribe=_container_status_on_subscribe,
    on_unsubscribe=_container_status_on_unsubscribe,
)


# Remote terminal streams (agent PTY output). The agent streams base64 PTY
# output on channel `terminal:<session_id>`; the gateway rebroadcasts it as
# `server_stream` events into server_<id>_terminal:<session_id>. Attaching
# exposes everything typed/printed in that shell (often root on the agent
# host); creating a terminal is @developer_required on the REST side, so
# observing one demands the same role. Session ids are unguessable uuids
# minted by TerminalService for the authenticated creator.

def _terminal_auth(sid, data):
    if not _client_is_privileged(sid):
        return 'Developer role required for terminal access'
    return None


def _terminal_room(data):
    from app.services.terminal_service import TerminalService
    session_id = data.get('session_id')
    if not session_id:
        raise ChannelError('session_id required')
    session = TerminalService.get_session(session_id)
    if not session:
        raise ChannelError('Unknown terminal session')
    return rooms.server_terminal_room(session['server_id'], session_id)


register_channel(
    'terminal',
    room_fn=_terminal_room,
    auth=_terminal_auth,
    ack=lambda data: {'channel': f"terminal:{data.get('session_id')}"},
    ack_unsubscribe=False,  # the legacy handler never acked the leave
)


@socketio.on('subscribe_logs')
def handle_subscribe_logs(data):
    """Subscribe to real-time log streaming."""
    sid = request.sid
    filepath = data.get('path')

    if not filepath:
        emit('error', {'message': 'Log path required'})
        return

    # Start log stream
    log_queue = log_streamer.start_stream(sid, filepath)

    # Create thread to emit log updates
    def emit_logs():
        while True:
            try:
                log_data = log_queue.get(timeout=30)
                if 'error' in log_data:
                    socketio.emit('log_error', log_data, room=sid)
                    break
                socketio.emit('log_line', log_data, room=sid)
            except:
                break

    thread = threading.Thread(target=emit_logs, daemon=True)
    thread.start()

    emit('subscribed', {'channel': 'logs', 'path': filepath})


@socketio.on('unsubscribe_logs')
def handle_unsubscribe_logs():
    """Unsubscribe from log streaming."""
    sid = request.sid
    log_streamer.stop_stream(sid)
    emit('unsubscribed', {'channel': 'logs'})


@socketio.on('join_room')
def handle_join_room(data):
    """Join a specific room for targeted broadcasts.

    This is the generic join used by job-progress and cloudflared-login
    streaming (rooms shaped `server_<id>_<channel>`). It is deliberately
    permissive for those — the data mirrors what any authenticated user can
    already pull over REST — but it must NOT become a side door into the
    privileged terminal stream rooms (`server_<id>_terminal:<session>`), which
    `subscribe_terminal` gates by role. Enforce that gate here too so the
    generic primitive can't be used to bypass it.
    """
    room = data.get('room')
    if not room or not isinstance(room, str):
        emit('error', {'message': 'room required'})
        return

    if rooms.is_terminal_room(room) and not _client_is_privileged(request.sid):
        emit('error', {'message': 'Developer role required for terminal access'})
        return

    join_room(room)
    emit('joined', {'room': room})


@socketio.on('leave_room')
def handle_leave_room(data):
    """Leave a specific room."""
    room = data.get('room')
    if room:
        leave_room(room)
        emit('left', {'room': room})


# ==================== DEPLOY CONSOLE STREAMING ====================
#
# Live push for the Deploy Console (plan 51). Room is per DeploymentJob
# (`deploy_{job_id}`); the RunLogStream seam batches writes and emits one
# `deploy_log` (a batch of persisted lines) per flush plus `deploy_status`
# (the job summary dict) on step/terminal transitions. This is an ACCELERATOR
# on top of the `GET /deployment-jobs/<id>/logs?after_id=` polling endpoint —
# the console stays 100% functional with sockets disabled (D2).

# Deploy Console: any authenticated user may watch (mirrors the read API —
# job ids are unguessable UUIDs and the REST read endpoint exposes them the
# same way).

def _deploy_room(data):
    job_id = data.get('job_id')
    if not job_id:
        raise ChannelError('job_id required')
    return rooms.deploy_room(job_id)


register_channel(
    'deploy',
    room_fn=_deploy_room,
    ack=lambda data: {'job_id': data.get('job_id')},
)


def emit_deploy_log(job_id: str, lines: list):
    """Emit a batch of persisted deploy log lines to a job's room.

    Called from RunLogStream on each flush. `lines` is a list of
    {id, step_index, level, message, ts} dicts (already persisted, carrying
    real DB ids so the client can dedupe + after_id re-sync).
    """
    socketio.emit('deploy_log', {
        'job_id': job_id,
        'lines': lines,
    }, room=rooms.deploy_room(job_id))


def emit_deploy_status(job_id: str, status: dict):
    """Emit a deployment job status summary (same shape as
    GET /deployment-jobs/<id>, without logs) to the job's room."""
    socketio.emit('deploy_status', {
        'job_id': job_id,
        'status': status,
    }, room=rooms.deploy_room(job_id))


# ==================== GENERALIZED RUN ENVELOPE (plan 77 E1) ====================
#
# One event pair for every run kind, keyed by (run_kind, run_id) in the room
# run_<kind>_<id>. The deploy kind dual-emits the legacy deploy_log /
# deploy_status pair above during the migration window so existing Deploy
# Console listeners keep working.

def emit_run_log(run_kind: str, run_id, lines: list):
    """Emit a batch of persisted run log lines to the run's envelope room."""
    socketio.emit('run_log', {
        'run_kind': run_kind,
        'run_id': run_id,
        'lines': lines,
    }, room=rooms.run_room(run_kind, run_id))
    if run_kind == 'deploy':
        emit_deploy_log(run_id, lines)


def emit_run_status(run_kind: str, run_id, status: dict):
    """Emit a run's status summary to the run's envelope room."""
    socketio.emit('run_status', {
        'run_kind': run_kind,
        'run_id': run_id,
        'status': status,
    }, room=rooms.run_room(run_kind, run_id))
    if run_kind == 'deploy':
        emit_deploy_status(run_id, status)


def _run_channel_room(data):
    run_kind = data.get('run_kind')
    run_id = data.get('run_id')
    if not run_kind or run_id in (None, ''):
        raise ChannelError('run_kind and run_id required')
    return rooms.run_room(run_kind, run_id)


# Auth mirrors the deploy channel: any authenticated user may watch — run ids
# are unguessable and the REST twin exposes the same data the same way.
register_channel(
    'run',
    room_fn=_run_channel_room,
    ack=lambda data: {'run_kind': data.get('run_kind'), 'run_id': data.get('run_id')},
)


# ==================== CONTAINER LOG STREAMING ====================

@socketio.on('subscribe_container_logs')
def handle_subscribe_container_logs(data):
    """Subscribe to real-time container log streaming.

    data: {
        'app_id': int,
        'tail': int (optional, default 100),
        'since': str (optional),
        'service': str (optional, for compose apps)
    }

    Emits:
        - 'subscribed': Confirmation with app_id and container info
        - 'container_log': Log lines as they arrive
        - 'container_log_error': If streaming fails
        - 'container_log_ended': When stream ends (container stopped)
    """
    from app.models import Application, User
    from app import db

    sid = request.sid
    app_id = data.get('app_id')
    tail = data.get('tail', 100)
    since = data.get('since')
    service = data.get('service')

    if not app_id:
        emit('error', {'message': 'app_id required'})
        return

    # Stop any existing stream for this client
    stop_container_log_stream(sid)

    # Get app and verify access
    try:
        app = Application.query_active().filter_by(id=app_id).first()
        if not app:
            emit('container_log_error', {'message': 'Application not found', 'app_id': app_id})
            return
    except Exception as e:
        emit('container_log_error', {'message': f'Database error: {str(e)}', 'app_id': app_id})
        return

    # Get container ID
    all_containers = DockerService.get_all_app_containers(app)

    container_id = None
    container_name = None

    if service:
        for c in all_containers:
            if c.get('service') == service or c.get('name') == service:
                container_id = c.get('id') or c.get('name')
                container_name = c.get('name')
                break
    else:
        container_id = DockerService.get_app_container_id(app)
        if all_containers:
            container_name = all_containers[0].get('name')

    if not container_id:
        emit('container_log_error', {
            'message': 'No container found for this application',
            'app_id': app_id,
            'hint': 'The application may not have been started yet'
        })
        return

    # Check container state
    container_state = DockerService.get_container_state(container_id)
    if not container_state:
        emit('container_log_error', {
            'message': 'Container not found or no longer exists',
            'app_id': app_id
        })
        return

    # Join room for this app's logs
    join_room(rooms.app_logs_room(app_id))

    # Start streaming process
    process = DockerService.stream_container_logs(
        container_id,
        tail=tail,
        since=since,
        timestamps=True
    )

    if not process:
        emit('container_log_error', {
            'message': 'Failed to start log stream',
            'app_id': app_id
        })
        return

    # Create stop event for this stream
    stop_event = threading.Event()

    # Create thread to read and emit logs
    def stream_logs():
        try:
            while not stop_event.is_set():
                line = process.stdout.readline()
                if not line:
                    # Process ended (container stopped or exited)
                    if not stop_event.is_set():
                        socketio.emit('container_log_ended', {
                            'app_id': app_id,
                            'message': 'Container log stream ended'
                        }, room=rooms.app_logs_room(app_id))
                    break

                # Parse the log line
                parsed = DockerService.parse_log_line(line.rstrip('\n'))

                socketio.emit('container_log', {
                    'app_id': app_id,
                    'line': line.rstrip('\n'),
                    'parsed': parsed,
                    'timestamp': time.time()
                }, room=rooms.app_logs_room(app_id))
        except Exception as e:
            if not stop_event.is_set():
                socketio.emit('container_log_error', {
                    'app_id': app_id,
                    'message': f'Stream error: {str(e)}'
                }, room=rooms.app_logs_room(app_id))
        finally:
            # Clean up
            try:
                process.terminate()
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass

    thread = threading.Thread(target=stream_logs, daemon=True)
    thread.start()

    # Store stream info for cleanup
    container_log_streams[sid] = {
        'process': process,
        'app_id': app_id,
        'thread': thread,
        'stop_event': stop_event,
        'container_id': container_id
    }

    emit('subscribed', {
        'channel': 'container_logs',
        'app_id': app_id,
        'container_id': container_id,
        'container_name': container_name,
        'container_state': container_state,
        'containers': all_containers
    })


@socketio.on('unsubscribe_container_logs')
def handle_unsubscribe_container_logs():
    """Unsubscribe from container log streaming."""
    sid = request.sid
    stream_info = container_log_streams.get(sid)

    if stream_info:
        app_id = stream_info.get('app_id')
        leave_room(rooms.app_logs_room(app_id))
        stop_container_log_stream(sid)

    emit('unsubscribed', {'channel': 'container_logs'})


def stop_container_log_stream(sid: str):
    """Stop a container log stream for a specific session.

    Args:
        sid: Socket session ID
    """
    stream_info = container_log_streams.pop(sid, None)
    if stream_info:
        # Signal thread to stop
        stop_event = stream_info.get('stop_event')
        if stop_event:
            stop_event.set()

        # Terminate the process
        process = stream_info.get('process')
        if process:
            try:
                process.terminate()
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass


def emit_container_log(app_id: int, line: str, level: str = 'info'):
    """Emit a container log line to all subscribers.

    This function can be called externally to inject log messages.
    """
    socketio.emit('container_log', {
        'app_id': app_id,
        'line': line,
        'parsed': {
            'timestamp': None,
            'message': line,
            'level': level
        },
        'timestamp': time.time()
    }, room=rooms.app_logs_room(app_id))
