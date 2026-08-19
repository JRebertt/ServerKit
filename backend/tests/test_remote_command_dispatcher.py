"""Conformance tests for the shared remote-agent command boundary."""

import ast
from pathlib import Path

from app.services import remote_command_dispatcher
from app.services.remote_command_dispatcher import dispatch_agent_command


SERVICES_DIR = Path(__file__).parents[1] / "app" / "services"
REMOTE_SERVICE_FILES = tuple(sorted(SERVICES_DIR.glob("remote_*_service.py")))
DISPATCHER_MODULE = "app.services.remote_command_dispatcher"


def test_dispatcher_normalizes_transport_arguments(monkeypatch):
    captured = {}

    def fake_send_command(**kwargs):
        captured.update(kwargs)
        return {"success": True, "data": {"accepted": True}}

    monkeypatch.setattr(
        remote_command_dispatcher.agent_registry,
        "send_command",
        fake_send_command,
    )

    params = {"unit": "nginx.service"}
    result = dispatch_agent_command(
        "server-1",
        "systemd:status",
        params=params,
        user_id=42,
        timeout=12.5,
    )

    assert result == {"success": True, "data": {"accepted": True}}
    assert captured == {
        "server_id": "server-1",
        "action": "systemd:status",
        "params": {"unit": "nginx.service"},
        "user_id": 42,
        "timeout": 12.5,
    }
    assert captured["params"] is not params


def test_dispatcher_supplies_stable_defaults(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        remote_command_dispatcher.agent_registry,
        "send_command",
        lambda **kwargs: captured.update(kwargs) or {"success": True},
    )

    dispatch_agent_command("server-2", "cron:list")

    assert captured["params"] == {}
    assert captured["user_id"] is None
    assert captured["timeout"] == 30.0


def test_remote_feature_services_use_shared_dispatcher():
    """Remote feature services must import the seam they are built on."""
    assert REMOTE_SERVICE_FILES, "expected remote feature services"

    for path in REMOTE_SERVICE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_dispatcher = any(
            isinstance(node, ast.ImportFrom)
            and node.module == DISPATCHER_MODULE
            and any(alias.name == "dispatch_agent_command" for alias in node.names)
            for node in tree.body
        )
        assert imports_dispatcher, f"{path.name} must import the shared dispatcher"


BACKEND = Path(__file__).parents[1]
REPO = BACKEND.parent

# The transport itself and the one door allowed to call it.
SEND_COMMAND_DOOR = {
    BACKEND / "app" / "services" / "agent_registry.py",
    BACKEND / "app" / "services" / "remote_command_dispatcher.py",
}


def _py_files(root):
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        yield path


def test_nothing_but_the_door_calls_send_command():
    """The whole tree, not just remote_* services: every ``*.send_command(...)``
    outside the dispatcher is a bypass of the shared remote command seam.

    ``agent_registry.send_command`` has exactly one definition, so matching the
    attribute name alone is precise — no receiver resolution needed. The scan
    covers ``builtin-extensions/`` too, because the live ``app/plugins`` copies
    of own-repo extensions are synced from there and are git-ignored.
    """
    offenders = []
    for root in (BACKEND / "app", REPO / "builtin-extensions"):
        for path in _py_files(root):
            if path in SEND_COMMAND_DOOR:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                is_call = (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "send_command"
                )
                # A bare ``target=agent_registry.send_command`` reference (e.g.
                # a Thread target) is the same bypass without the parentheses.
                is_ref = (
                    isinstance(node, ast.Attribute)
                    and node.attr == "send_command"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "agent_registry"
                )
                if is_call or is_ref:
                    rel = path.relative_to(REPO).as_posix()
                    offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "these call agent transport directly instead of "
        "dispatch_agent_command():\n  " + "\n  ".join(sorted(set(offenders)))
    )
