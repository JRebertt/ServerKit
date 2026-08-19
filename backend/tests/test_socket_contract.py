"""Plan 77 E3 — the socket wire protocol has one definition per side, mirrored.

Room names come only from app/sockets_rooms.py; event names only from
app/constants.py, mirrored verbatim by frontend/src/constants/events.js.
The mirror test parses the JS file so a renamed event fails HERE instead of
silently killing a stream in production.
"""
import re
from pathlib import Path

from app import sockets_rooms as rooms
from app.constants import SOCKET_EVENTS

REPO = Path(__file__).resolve().parents[2]
EVENTS_JS = REPO / 'frontend' / 'src' / 'constants' / 'events.js'


def _parse_js_events():
    text = EVENTS_JS.read_text(encoding='utf-8')
    block = re.search(r'export const SOCKET_EVENTS = \{(.*?)\n\};', text, re.S)
    assert block, 'SOCKET_EVENTS block missing from events.js'
    return dict(re.findall(r"^\s*([A-Z_]+):\s*'([a-z_]+)',", block.group(1), re.M))


def test_event_tables_are_identical():
    js = _parse_js_events()
    assert js == SOCKET_EVENTS, (
        'backend/app/constants.py and frontend/src/constants/events.js drifted. '
        f'Only in backend: {sorted(set(SOCKET_EVENTS) - set(js))}; '
        f'only in frontend: {sorted(set(js) - set(SOCKET_EVENTS))}; '
        f'value mismatches: '
        f'{ {k: (SOCKET_EVENTS[k], js[k]) for k in set(js) & set(SOCKET_EVENTS) if js[k] != SOCKET_EVENTS[k]} }'
    )


def test_room_grammar():
    assert rooms.user_room(7) == 'user_7'
    assert rooms.deploy_room('j1') == 'deploy_j1'
    assert rooms.run_room('sandbox', 42) == 'run_sandbox_42'
    assert rooms.app_logs_room(3) == 'logs_3'
    assert rooms.server_channel_room('s1', 'jobs') == 'server_s1_jobs'
    assert rooms.server_metrics_room('s1') == 'server_s1_metrics'
    assert rooms.server_container_logs_room('s1', 'abc') == 'server_s1_container_abc_logs'
    assert rooms.server_terminal_room('s1', 'sess') == 'server_s1_terminal:sess'


def test_terminal_room_gate_agrees_with_builder():
    assert rooms.is_terminal_room(rooms.server_terminal_room('s1', 'x'))
    assert not rooms.is_terminal_room(rooms.server_metrics_room('s1'))
    assert not rooms.is_terminal_room(None)


def test_no_room_fstrings_outside_the_rooms_module():
    """Ratchet: no hand-assembled room name f-strings in the realtime layer."""
    offenders = []
    pattern = re.compile(
        r"f['\"](?:user_\{|deploy_\{|run_\{|logs_\{|server_\{)")
    for rel in ('app/sockets.py', 'app/agent_gateway.py',
                'app/notifications/service.py', 'app/services/run_log_service.py'):
        text = (REPO / 'backend' / rel).read_text(encoding='utf-8')
        for i, line in enumerate(text.split('\n'), 1):
            if pattern.search(line) and 'sockets_rooms' not in line:
                offenders.append(f'{rel}:{i}')
    assert not offenders, (
        f'Hand-assembled room names at {offenders} — use app/sockets_rooms.py '
        '(plan 77 E3).'
    )
