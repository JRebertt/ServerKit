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
    """New transport calls cannot bypass the single remote command seam."""
    assert REMOTE_SERVICE_FILES, "expected remote feature services"

    for path in REMOTE_SERVICE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_dispatcher = any(
            isinstance(node, ast.ImportFrom)
            and node.module == DISPATCHER_MODULE
            and any(alias.name == "dispatch_agent_command" for alias in node.names)
            for node in tree.body
        )
        direct_sends = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_command"
        ]

        assert imports_dispatcher, f"{path.name} must import the shared dispatcher"
        assert not direct_sends, f"{path.name} bypasses the shared dispatcher"
