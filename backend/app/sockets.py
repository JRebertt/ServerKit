from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_jwt_extended import decode_token
from flask import request, current_app
import threading
import time
import queue

from app.services.system_service import SystemService
from app.services.log_service import LogService, LogStreamer
from app.services.docker_service import DockerService

socketio = SocketIO()
log_streamer = LogStreamer()

# Store active metric subscriptions
metric_subscribers = set()
metric_thread = None
metric_stop_event = threading.Event()

# Store active aggregated container-status subscriptions
container_status_subscribers = set()
container_status_thread = None
container_status_stop_event = threading.Event()

# Store active container log streams
container_log_streams = {}  # sid -> {'process': Popen, 'app_id': int, 'thread': Thread, 'stop_event': Event}

# Store active pipeline subscriptions
pipeline_subscribers = {}  # sid -> set of project_ids

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
    join_room(f'user_{user.id}')

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

    # Remove from pipeline subscribers
    pipeline_subscribers.pop(sid, None)

    # Drop the authenticated-identity record for this socket.
    with _connected_clients_lock:
        connected_clients.pop(sid, None)


@socketio.on('subscribe_metrics')
def handle_subscribe_metrics():
    """Subscribe to real-time system metrics."""
    global metric_thread, metric_stop_event

    sid = request.sid
    metric_subscribers.add(sid)

    # Start metric broadcast thread if not running
    if metric_thread is None or not metric_thread.is_alive():
        metric_stop_event.clear()
        metric_thread = threading.Thread(target=broadcast_metrics, daemon=True)
        metric_thread.start()

    emit('subscribed', {'channel': 'metrics'})


@socketio.on('unsubscribe_metrics')
def handle_unsubscribe_metrics():
    """Unsubscribe from system metrics."""
    sid = request.sid
    if sid in metric_subscribers:
        metric_subscribers.remove(sid)
    emit('unsubscribed', {'channel': 'metrics'})


def broadcast_metrics():
    """Broadcast system metrics to all subscribers."""
    global metric_stop_event

    while not metric_stop_event.is_set() and metric_subscribers:
        try:
            metrics = SystemService.get_all_metrics()
            socketio.emit('metrics', metrics, room=None)  # Broadcast to all
        except Exception as e:
            print(f"Error broadcasting metrics: {e}")

        time.sleep(2)  # Update every 2 seconds


# ==================== AGGREGATED CONTAINER STATUS ====================

@socketio.on('subscribe_container_status')
def handle_subscribe_container_status():
    """Subscribe to aggregated container-status change events.

    Mirrors the metrics pattern: a single background thread polls the
    aggregator and broadcasts ONLY the apps whose status changed since the last
    tick (channel 'container_status'). Clients reconcile by app_id.
    """
    global container_status_thread, container_status_stop_event

    sid = request.sid
    container_status_subscribers.add(sid)

    if container_status_thread is None or not container_status_thread.is_alive():
        container_status_stop_event.clear()
        container_status_thread = threading.Thread(
            target=broadcast_container_status,
            args=(current_app._get_current_object(),),
            daemon=True,
        )
        container_status_thread.start()

    emit('subscribed', {'channel': 'container_status'})


@socketio.on('unsubscribe_container_status')
def handle_unsubscribe_container_status():
    """Unsubscribe from aggregated container-status events."""
    sid = request.sid
    if sid in container_status_subscribers:
        container_status_subscribers.remove(sid)
    emit('unsubscribed', {'channel': 'container_status'})


def broadcast_container_status(flask_app):
    """Broadcast changed aggregated container statuses to all subscribers.

    Runs in a background thread for as long as there are subscribers. Each tick
    asks the aggregator for the deltas (it keeps the last-emitted snapshot in
    memory) and emits only those. Defensive: any Docker/DB error is swallowed so
    the loop survives a transient outage. Needs an app context because the
    aggregator touches the ORM.
    """
    global container_status_stop_event

    from app.services import container_status_service as css

    while not container_status_stop_event.is_set() and container_status_subscribers:
        try:
            with flask_app.app_context():
                changed = css.get_changed_app_statuses()
            if changed:
                socketio.emit('container_status', {
                    'statuses': changed,
                    'timestamp': time.time(),
                }, room=None)
        except Exception as e:
            print(f"Error broadcasting container status: {e}")

        time.sleep(5)  # Re-evaluate every 5 seconds


@socketio.on('subscribe_terminal')
def handle_subscribe_terminal(data):
    """Join the stream room for a remote terminal session (agent PTY output).

    The agent streams base64 PTY output on channel `terminal:<session_id>`;
    the agent gateway rebroadcasts it as `server_stream` events into the room
    `server_<server_id>_terminal:<session_id>`. This handler is what lets a
    browser join that room — without it the output never reaches the UI.
    Session ids are unguessable uuids minted by TerminalService for the
    authenticated creator.
    """
    from app.services.terminal_service import TerminalService

    # Attaching to a live PTY stream exposes everything typed and printed in
    # that shell (often running as root on the agent host). Creating a terminal
    # is @developer_required on the REST side, so observing one must demand the
    # same role — otherwise a read-only viewer could join the stream room and
    # watch a privileged session.
    if not _client_is_privileged(request.sid):
        emit('error', {'message': 'Developer role required for terminal access'})
        return

    session_id = (data or {}).get('session_id')
    if not session_id:
        emit('error', {'message': 'session_id required'})
        return

    session = TerminalService.get_session(session_id)
    if not session:
        emit('error', {'message': 'Unknown terminal session'})
        return

    join_room(f"server_{session['server_id']}_terminal:{session_id}")
    emit('subscribed', {'channel': f'terminal:{session_id}'})


@socketio.on('unsubscribe_terminal')
def handle_unsubscribe_terminal(data):
    """Leave a terminal session's stream room."""
    from app.services.terminal_service import TerminalService

    session_id = (data or {}).get('session_id')
    if not session_id:
        return
    session = TerminalService.get_session(session_id)
    if session:
        leave_room(f"server_{session['server_id']}_terminal:{session_id}")


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

    if '_terminal:' in room and not _client_is_privileged(request.sid):
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

@socketio.on('subscribe_deploy')
def handle_subscribe_deploy(data):
    """Subscribe to live Deploy Console updates for a deployment job.

    Auth mirrors the read API (D3/§8): any authenticated user may watch — job
    ids are unguessable UUIDs and the REST read endpoint exposes them the same
    way. The connect handler already verified the JWT and recorded identity in
    `connected_clients`; a socket missing from that set is not authenticated.
    """
    sid = request.sid
    if sid not in connected_clients:
        emit('error', {'message': 'Authentication required'})
        return

    job_id = (data or {}).get('job_id')
    if not job_id:
        emit('error', {'message': 'job_id required'})
        return

    join_room(f'deploy_{job_id}')
    emit('subscribed', {'channel': 'deploy', 'job_id': job_id})


@socketio.on('unsubscribe_deploy')
def handle_unsubscribe_deploy(data=None):
    """Leave a deployment job's live room."""
    job_id = (data or {}).get('job_id')
    if job_id:
        leave_room(f'deploy_{job_id}')
    emit('unsubscribed', {'channel': 'deploy', 'job_id': job_id})


def emit_deploy_log(job_id: str, lines: list):
    """Emit a batch of persisted deploy log lines to a job's room.

    Called from RunLogStream on each flush. `lines` is a list of
    {id, step_index, level, message, ts} dicts (already persisted, carrying
    real DB ids so the client can dedupe + after_id re-sync).
    """
    socketio.emit('deploy_log', {
        'job_id': job_id,
        'lines': lines,
    }, room=f'deploy_{job_id}')


def emit_deploy_status(job_id: str, status: dict):
    """Emit a deployment job status summary (same shape as
    GET /deployment-jobs/<id>, without logs) to the job's room."""
    socketio.emit('deploy_status', {
        'job_id': job_id,
        'status': status,
    }, room=f'deploy_{job_id}')


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
    join_room(f'logs_{app_id}')

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
                        }, room=f'logs_{app_id}')
                    break

                # Parse the log line
                parsed = DockerService.parse_log_line(line.rstrip('\n'))

                socketio.emit('container_log', {
                    'app_id': app_id,
                    'line': line.rstrip('\n'),
                    'parsed': parsed,
                    'timestamp': time.time()
                }, room=f'logs_{app_id}')
        except Exception as e:
            if not stop_event.is_set():
                socketio.emit('container_log_error', {
                    'app_id': app_id,
                    'message': f'Stream error: {str(e)}'
                }, room=f'logs_{app_id}')
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
        leave_room(f'logs_{app_id}')
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
    }, room=f'logs_{app_id}')


# ==================== PIPELINE EVENT STREAMING ====================

@socketio.on('subscribe_pipeline')
def handle_subscribe_pipeline(data):
    """Subscribe to real-time pipeline events for a WordPress project.

    data: {
        'project_id': int  (production site ID)
    }

    Emits 'pipeline_event' with:
        - project_id: int
        - event: string (e.g. 'promotion_started', 'sync_completed')
        - data: dict with event-specific details
        - timestamp: float
    """
    sid = request.sid
    project_id = data.get('project_id')

    if not project_id:
        emit('error', {'message': 'project_id required'})
        return

    room = f'pipeline_{project_id}'
    join_room(room)

    if sid not in pipeline_subscribers:
        pipeline_subscribers[sid] = set()
    pipeline_subscribers[sid].add(project_id)

    emit('subscribed', {'channel': 'pipeline', 'project_id': project_id})


@socketio.on('unsubscribe_pipeline')
def handle_unsubscribe_pipeline(data):
    """Unsubscribe from pipeline events for a project."""
    sid = request.sid
    project_id = data.get('project_id')

    if project_id:
        leave_room(f'pipeline_{project_id}')
        if sid in pipeline_subscribers:
            pipeline_subscribers[sid].discard(project_id)
            if not pipeline_subscribers[sid]:
                del pipeline_subscribers[sid]

    emit('unsubscribed', {'channel': 'pipeline', 'project_id': project_id})


def emit_pipeline_event(project_id: int, event: str, data: dict = None):
    """Emit a pipeline event to all subscribers of a project.

    Called from EnvironmentPipelineService or API endpoints to notify
    the frontend about long-running operations (promote, sync, create).

    Args:
        project_id: Production site ID
        event: Event type (e.g. 'promotion_started', 'sync_completed',
               'environment_created', 'environment_deleted')
        data: Event-specific payload
    """
    socketio.emit('pipeline_event', {
        'project_id': project_id,
        'event': event,
        'data': data or {},
        'timestamp': time.time()
    }, room=f'pipeline_{project_id}')
