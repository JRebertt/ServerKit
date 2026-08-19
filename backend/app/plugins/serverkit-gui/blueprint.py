"""ServerKit Agent GUI plugin — panel-side blueprint.

Acts as a thin proxy between the frontend and the agent's gui:* actions.
No frame data is stored; everything is forwarded through plugins_sdk.agents,
which checks this plugin declared ``agent.command:<action>`` before dispatching
and turns a failed command into an exception carrying the reason.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.middleware.rbac import get_current_user
from app.plugins_sdk import agents, logger
from app.plugins_sdk.permissions import PermissionDenied
from app.models.server import Server

gui_bp = Blueprint("server_gui", __name__)
log = logger(__name__)

PLUGIN_SLUG = "serverkit-gui"

DEFAULT_FRAME_TIMEOUT = 8.0
MAX_FRAME_TIMEOUT = 15.0


def _fleet():
    return agents.for_plugin(PLUGIN_SLUG)


def _server_or_404(server_id: str):
    server = Server.query.get(server_id)
    if not server:
        return None, (jsonify({"error": "Server not found"}), 404)
    return server, None


@gui_bp.route("/<server_id>/capabilities", methods=["GET"])
@jwt_required()
def capabilities(server_id):
    """Ask the agent what it can capture (display server, resolution, fps cap)."""
    user = get_current_user()
    server, err = _server_or_404(server_id)
    if err:
        return err

    if server.status != "online":
        return jsonify({
            "capability": "none",
            "reason": "agent_offline",
            "synthetic_fallback": True,
        })

    try:
        data = _fleet().run(
            server_id, "gui:capabilities",
            timeout=5.0,
            user_id=user.id if user else None,
        )
    except (agents.CommandError, PermissionDenied) as exc:
        # Not an error state: an agent that doesn't implement gui:capabilities
        # is exactly what the synthetic fallback exists for.
        return jsonify({
            "capability": "none",
            "reason": str(exc),
            "synthetic_fallback": True,
        })

    if not isinstance(data, dict):
        data = {}
    data.setdefault("synthetic_fallback", data.get("capability") in (None, "none"))
    return jsonify(data)


@gui_bp.route("/<server_id>/frame", methods=["GET"])
@jwt_required()
def frame(server_id):
    """Capture and return a single frame.

    Query params:
      scale   float 0.1..1.0   server-side downscale before encoding
      quality int   10..95     JPEG quality (PNG ignores this)
      format  png|jpeg         encoding hint
    """
    user = get_current_user()
    server, err = _server_or_404(server_id)
    if err:
        return err

    if server.status != "online":
        return jsonify({"error": "agent offline", "code": "AGENT_OFFLINE"}), 503

    try:
        scale = float(request.args.get("scale", "0.75"))
        quality = int(request.args.get("quality", "70"))
    except ValueError:
        return jsonify({"error": "scale/quality must be numeric"}), 400

    scale = max(0.1, min(scale, 1.0))
    quality = max(10, min(quality, 95))
    fmt = request.args.get("format", "jpeg").lower()
    if fmt not in ("jpeg", "png"):
        fmt = "jpeg"

    try:
        data = _fleet().run(
            server_id, "gui:screenshot",
            {"scale": scale, "quality": quality, "format": fmt},
            timeout=DEFAULT_FRAME_TIMEOUT,
            user_id=user.id if user else None,
        )
    except PermissionDenied as exc:
        # Only reachable if this plugin's manifest lost the permission.
        return jsonify({"error": str(exc), "code": "PERMISSION_DENIED"}), 403
    except agents.CommandError as exc:
        return jsonify({"error": str(exc), "code": exc.code or "CAPTURE_FAILED"}), 502

    # Expected agent shape:
    #   { "image_base64": "...", "format": "jpeg", "width": 1920, "height": 1080,
    #     "captured_at": "2026-05-01T12:34:56Z" }
    if not isinstance(data, dict) or "image_base64" not in data:
        return jsonify({"error": "agent returned no frame"}), 502

    return jsonify(data)


@gui_bp.route("/<server_id>/synthetic", methods=["GET"])
@jwt_required()
def synthetic(server_id):
    """Return data the frontend uses to render the headless 'fake desktop'.

    No new agent action — we reuse data the agent already exposes via
    existing actions. Cheap and always available.
    """
    user = get_current_user()
    server, err = _server_or_404(server_id)
    if err:
        return err

    if server.status != "online":
        return jsonify({
            "windows": [],
            "taskbar": [],
            "drives": [],
            "offline": True,
        })

    user_id = user.id if user else None

    def _best_effort(action, params, default):
        """Ask the agent, but never fail the page over the answer.

        This endpoint renders *something* for a host with no display, so an
        agent that won't answer degrades to an empty panel rather than an
        error. A permission this plugin hasn't been granted lands in the same
        place deliberately: an install whose stored manifest predates these
        actions keeps working instead of 500-ing, and the log line says why.
        """
        try:
            return _fleet().run(server_id, action, params, timeout=5.0,
                                user_id=user_id)
        except PermissionDenied as exc:
            log.warning('%s: %s — update the extension to restore full '
                        'synthetic detail', PLUGIN_SLUG, exc)
            return default
        except agents.CommandError:
            return default

    info = _best_effort("system:info", {}, {})
    plist = _best_effort("system:processes", {"limit": 12}, [])
    if not isinstance(info, dict):
        info = {}
    if not isinstance(plist, list):
        plist = []

    windows = [
        {
            "id": "system",
            "title": f"System — {info.get('hostname', server.name)}",
            "icon": "monitor",
            "body": {
                "OS": f"{info.get('os', 'Unknown')} {info.get('os_version', '')}".strip(),
                "Arch": info.get("architecture", "?"),
                "CPU": info.get("cpu_model", "?"),
                "Cores": info.get("cpu_cores", "?"),
            },
        },
        {
            "id": "processes",
            "title": "Top processes",
            "icon": "activity",
            "body": [
                {"name": p.get("name"), "cpu": p.get("cpu_percent"), "mem": p.get("memory_percent")}
                for p in plist[:8]
            ],
        },
    ]

    taskbar = [
        {"id": p.get("pid"), "name": p.get("name", "?")}
        for p in plist[:6]
    ]

    drives = [
        {"path": d.get("mountpoint"), "used": d.get("used_percent")}
        for d in (info.get("disks") or [])
    ]

    return jsonify({
        "windows": windows,
        "taskbar": taskbar,
        "drives": drives,
        "hostname": info.get("hostname") or server.name,
        "offline": False,
    })
