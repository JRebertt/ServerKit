"""Every Socket.IO room name is built HERE (plan 77 E3).

The room grammar used to live in ~25 scattered f-strings across sockets.py,
agent_gateway.py and the notification bus — and was re-derived by hand in
frontend template literals. One typo'd segment means a silently dead stream,
so the builders below are the single source of truth; the frontend mirrors
the same grammar in ``src/constants/events.js`` (kept in lockstep by
``tests/test_socket_contract.py``).

Grammar:

    user_<user_id>                      per-user notification fan-out
    deploy_<job_id>                     Deploy Console (legacy run envelope)
    run_<kind>_<run_id>                 generalized run envelope (plan 77 E1)
    logs_<app_id>                       container log streaming for an app
    server_<id>_<channel>               generic agent-stream rebroadcast
    server_<id>_metrics                 agent metrics fan-out
    server_<id>_container_<cid>_logs    agent container logs
    server_<id>_terminal:<session_id>   remote PTY (role-gated!)
"""


def user_room(user_id) -> str:
    return f'user_{user_id}'


def deploy_room(job_id) -> str:
    return f'deploy_{job_id}'


def run_room(run_kind, run_id) -> str:
    """The plan 77 E1 run envelope room — one grammar for every run kind."""
    return f'run_{run_kind}_{run_id}'


def app_logs_room(app_id) -> str:
    return f'logs_{app_id}'


def server_channel_room(server_id, channel) -> str:
    return f'server_{server_id}_{channel}'


def server_metrics_room(server_id) -> str:
    return server_channel_room(server_id, 'metrics')


def server_container_logs_room(server_id, container_id) -> str:
    return server_channel_room(server_id, f'container_{container_id}_logs')


def server_terminal_room(server_id, session_id) -> str:
    return server_channel_room(server_id, f'terminal:{session_id}')


def is_terminal_room(room: str) -> bool:
    """True for the privileged PTY stream rooms — the role gate keys off this
    (both subscribe_terminal and the generic join_room must agree)."""
    return isinstance(room, str) and '_terminal:' in room
