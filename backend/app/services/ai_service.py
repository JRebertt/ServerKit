"""Core AI assistant service (powered by Prompture).

Owns all Prompture wiring for the in-panel assistant:
- provider/key configuration via Prompture ``ProviderEnvironment`` (per-instance,
  never via ``os.environ``);
- system-prompt assembly (rebuilt every turn with the current page context and
  any plugin-contributed context providers);
- per-request Prompture ``ToolRegistry`` built from ``ai_tool_registry`` with
  read wrappers (RBAC re-check + optional PII redaction) and write wrappers
  (the human-in-the-loop confirmation gate);
- ``Conversation`` create/resume + persistence (``export()``/``from_export``);
- guardrails (prompt-injection refusal, PII redaction);
- the ``ConfirmationGate`` that lets a guarded write tool pause the streaming
  worker thread until the user approves/denies over ``/chat/confirm``.

Stateless module functions (ServerKit's three-layer convention) plus two small
helpers (the gate and an in-memory gate registry) that live in the single gevent
worker, consistent with ``agent_registry``.
"""
from __future__ import annotations

import dataclasses
import logging
import secrets
import threading
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional

# Prompture is imported lazily, inside the functions that build a Conversation,
# a ToolRegistry or a ProviderEnvironment — never at module scope.
#
# `import prompture` costs ~69 MB of RSS: it pulls ~300 prompture modules plus
# pydantic, rich, httpx, pygments and jsonschema. This module is reachable from
# app/api/ai.py, which create_app() registers like every other blueprint, so an
# eager import made every panel process pay for the assistant at boot whether or
# not anyone ever opened it — about a third of the panel's idle footprint.
#
# `from __future__ import annotations` (above) makes every annotation a string,
# so the names below are needed only for type checkers and readers, never at
# runtime. Keep it that way: a new module-level `from prompture import ...`
# silently puts the 69 MB back. Guarded by
# backend/tests/test_ai_lazy_import.py.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from prompture import Conversation, ProviderEnvironment
    from prompture.agents.tools_schema import ToolRegistry

from app import db
from app.services.ai_tool_registry import ai_tool_registry
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider catalog (curated; the user may also type a free-form provider/model)
# ---------------------------------------------------------------------------
# Maps provider -> the ProviderEnvironment attribute that carries its API key.
# `prompture-hub` is a self-hosted, OpenAI-compatible gateway; it reuses Prompture's
# `cachibot` driver (same dialect) so the panel can call a local hub with a scoped
# hub key instead of holding raw provider keys.
_KEY_ATTR = {
    "prompture-hub": "cachibot_api_key",
    "openai": "openai_api_key",
    "claude": "claude_api_key",
    "google": "google_api_key",
    "groq": "groq_api_key",
    "openrouter": "openrouter_api_key",
    "lmstudio": "lmstudio_api_key",
}
# Providers that take a custom endpoint instead of (or alongside) a key.
_ENDPOINT_ATTR = {
    "prompture-hub": "cachibot_endpoint",
    "ollama": "ollama_endpoint",
    "lmstudio": "lmstudio_endpoint",
}
# Curated providers whose model specs resolve through a *different* underlying
# Prompture driver than their id (e.g. the hub speaks the OpenAI-compatible
# `cachibot` dialect). Identity for everything else.
_DRIVER_PROVIDER = {"prompture-hub": "cachibot"}

CURATED_PROVIDERS = [
    {"id": "prompture-hub", "label": "Prompture Hub (self-hosted)", "needs_key": True, "supports_endpoint": True,
     "models": []},
    {"id": "openai", "label": "OpenAI", "needs_key": True, "supports_endpoint": False,
     "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"]},
    {"id": "claude", "label": "Anthropic (Claude)", "needs_key": True, "supports_endpoint": False,
     "models": ["claude-sonnet-4-6", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"]},
    {"id": "google", "label": "Google (Gemini)", "needs_key": True, "supports_endpoint": False,
     "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]},
    {"id": "groq", "label": "Groq", "needs_key": True, "supports_endpoint": False,
     "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]},
    {"id": "openrouter", "label": "OpenRouter", "needs_key": True, "supports_endpoint": False,
     "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-70b-instruct"]},
    {"id": "ollama", "label": "Ollama (local)", "needs_key": False, "supports_endpoint": True,
     "models": ["llama3.1:8b", "qwen2.5:7b", "mistral"]},
    {"id": "lmstudio", "label": "LM Studio (local)", "needs_key": False, "supports_endpoint": True,
     "models": []},
]
_PROVIDER_BY_ID = {p["id"]: p for p in CURATED_PROVIDERS}


def _driver_provider(provider: str) -> str:
    """Map a curated provider id to the Prompture driver prefix that resolves it."""
    return _DRIVER_PROVIDER.get((provider or "").strip(), (provider or "").strip())

SYSTEM_BASE = (
    "You are ServerKit AI, an assistant embedded in the ServerKit server control "
    "panel, powered by Prompture. You help operators understand and manage their "
    "servers, applications, Docker containers, and databases. Prefer calling tools "
    "to get LIVE data over guessing, and cite concrete numbers from tool results. "
    "Be concise and practical. For any state-changing action you MUST call the "
    "corresponding tool — it will pause for explicit human confirmation before "
    "anything actually runs. Never claim you performed an action unless a tool "
    "result confirms it."
)

# Guardrail detectors (cheap, regex-based) — built once, on first use. They are
# the only Prompture objects the module would otherwise need at import time;
# constructing them lazily is what keeps `import ai_service` free. Same
# double-checked pattern as ensure_initialized() below.
_injection_detector = None
_pii_redactor = None
_guardrails_lock = threading.Lock()


def _get_injection_detector():
    global _injection_detector
    if _injection_detector is None:
        with _guardrails_lock:
            if _injection_detector is None:
                from prompture import PromptInjectionDetector
                _injection_detector = PromptInjectionDetector(min_confidence=0.7)
    return _injection_detector


def _get_pii_redactor():
    global _pii_redactor
    if _pii_redactor is None:
        with _guardrails_lock:
            if _pii_redactor is None:
                from prompture import PIIRedactor
                _pii_redactor = PIIRedactor()
    return _pii_redactor

# In-memory registry of live confirmation gates, keyed by conversation id.
# Lives in the single gevent worker (like agent_registry).
_active_gates: dict[str, "ConfirmationGate"] = {}
_gates_lock = threading.Lock()

_init_lock = threading.Lock()
_initialized = False


# ===========================================================================
# Initialization / discovery
# ===========================================================================
def ensure_initialized() -> None:
    """Register built-in tools and discover plugin AI contributions (once)."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        from app.services.ai_tools_builtin import register_builtin_tools
        register_builtin_tools()
        from app.services.ai_attachment_registry import (
            register_builtin_attachment_resolvers,
        )
        register_builtin_attachment_resolvers()
        try:
            ai_tool_registry.discover_plugins()
        except Exception:
            logger.warning("AI plugin discovery failed during init", exc_info=True)
        _initialized = True


# ===========================================================================
# Settings / provider configuration
# ===========================================================================
def _setting(key: str, default=None):
    return SettingsService.get(key, default)


def is_enabled() -> bool:
    return bool(_setting("ai_enabled", False))


def is_configured() -> bool:
    """A provider + model are set and any required key is present."""
    provider = (_setting("ai_provider", "") or "").strip()
    model = (_setting("ai_model", "") or "").strip()
    if not provider or not model:
        return False
    meta = _PROVIDER_BY_ID.get(provider)
    needs_key = meta["needs_key"] if meta else True
    if needs_key and not _setting("ai_api_key_encrypted", ""):
        return False
    return True


def current_model_name() -> str:
    provider = (_setting("ai_provider", "") or "").strip()
    model = (_setting("ai_model", "") or "").strip()
    return f"{_driver_provider(provider)}/{model}" if provider and model else ""


def _decrypted_key() -> Optional[str]:
    enc = _setting("ai_api_key_encrypted", "")
    if not enc:
        return None
    try:
        from app.utils.crypto import decrypt_secret
        return decrypt_secret(enc)
    except Exception:
        logger.error("Failed to decrypt AI API key", exc_info=True)
        return None


def build_provider_env(*, provider: Optional[str] = None, api_key: Optional[str] = None,
                       endpoint: Optional[str] = None) -> ProviderEnvironment:
    """Build a per-instance ProviderEnvironment from stored (or supplied) config."""
    from prompture import ProviderEnvironment

    provider = (provider or _setting("ai_provider", "") or "").strip()
    if api_key is None:
        api_key = _decrypted_key()
    if endpoint is None:
        endpoint = (_setting("ai_endpoint", "") or "").strip() or None

    kwargs: dict[str, Any] = {}
    key_attr = _KEY_ATTR.get(provider)
    if key_attr and api_key:
        kwargs[key_attr] = api_key
    endpoint_attr = _ENDPOINT_ATTR.get(provider)
    if endpoint_attr and endpoint:
        kwargs[endpoint_attr] = endpoint
    return ProviderEnvironment(**kwargs)


def list_providers() -> list[dict]:
    """Provider catalog for the settings dropdown (models = fallback suggestions)."""
    return [
        {"id": p["id"], "label": p["label"], "needs_key": p["needs_key"],
         "supports_endpoint": p["supports_endpoint"]}
        for p in CURATED_PROVIDERS
    ]


def list_models(provider: str) -> dict:
    """Best-effort live model list for *provider*, falling back to curated suggestions."""
    provider = (provider or "").strip()
    fallback = _PROVIDER_BY_ID.get(provider, {}).get("models", [])
    try:
        from prompture.drivers import get_driver_for_model
        driver = get_driver_for_model(f"{_driver_provider(provider)}/", env=build_provider_env(provider=provider))
        lister = getattr(driver, "list_models", None)
        if callable(lister):
            models = lister()
            if models:
                return {"models": list(models), "source": "live"}
    except Exception:
        logger.debug("list_models(%s): live lookup failed, using fallback", provider, exc_info=True)
    return {"models": fallback, "source": "fallback"}


def test_settings(provider: str, model: str, api_key: Optional[str] = None,
                  endpoint: Optional[str] = None) -> dict:
    """Validate a provider/model/key by constructing the driver and probing models."""
    try:
        from prompture.drivers import get_driver_for_model
        env = build_provider_env(provider=provider, api_key=api_key, endpoint=endpoint)
        driver = get_driver_for_model(f"{_driver_provider(provider)}/{model}", env=env)
        lister = getattr(driver, "list_models", None)
        if callable(lister):
            try:
                lister()
            except Exception:
                pass  # not all providers support listing; driver constructed = good enough
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ===========================================================================
# Guardrails
# ===========================================================================
def injection_flagged(text: str) -> bool:
    if not _setting("ai_injection_detection", True):
        return False
    try:
        return bool(_get_injection_detector().is_injection(text))
    except Exception:
        return False


def _pii_enabled() -> bool:
    return bool(_setting("ai_pii_redaction", True))


def redact_input(text: str) -> str:
    if not _pii_enabled():
        return text
    try:
        return _get_pii_redactor().redact(text).text
    except Exception:
        return text


def _maybe_redact_result(result: Any) -> Any:
    if not _pii_enabled() or not isinstance(result, str):
        return result
    try:
        return _get_pii_redactor().redact(result).text
    except Exception:
        return result


# ===========================================================================
# System prompt
# ===========================================================================
def build_system_prompt(user, mode: str, page_context: Optional[dict]) -> str:
    parts = [SYSTEM_BASE]
    instance = _setting("instance_name", "ServerKit")
    parts.append(f"\nThis panel instance is named '{instance}'.")
    if mode == "assistant" and page_context:
        route = page_context.get("route") or page_context.get("path") or ""
        label = page_context.get("label") or ""
        ids = page_context.get("ids") or page_context.get("params") or {}
        parts.append(
            f"\nCURRENT PAGE: {route} ({label}). Relevant ids: {ids}. "
            "When the user says 'this server/app/container/database', resolve it from these ids."
        )
        # Plugin-contributed context providers for this route.
        if route:
            for cp in ai_tool_registry.context_providers_for(route):
                try:
                    extra = cp.func(user, route, ids)
                    if extra:
                        parts.append(f"\n[plugin:{cp.plugin_slug}] {extra}")
                except Exception:
                    logger.debug("context provider failed for %s", cp.route_pattern, exc_info=True)
    role = getattr(user, "role", "viewer")
    parts.append(
        f"\nThe operator's role is '{role}'. Do not offer or attempt actions they "
        "lack permission for; tools you cannot see are unavailable to this user."
    )
    return "".join(parts)


# ===========================================================================
# Per-request tool registry (read/write wrappers)
# ===========================================================================
def build_tool_registry(user, mode: str, gate: Optional["ConfirmationGate"]) -> Optional[ToolRegistry]:
    descriptors = ai_tool_registry.list_for(user, mode)
    if not descriptors:
        return None
    from prompture.agents.tools_schema import ToolDefinition, ToolRegistry

    reg = ToolRegistry()
    for d in descriptors:
        fn = _make_write_wrapper(d, user, gate) if d.is_write else _make_read_wrapper(d, user)
        reg.add(ToolDefinition(name=d.qualified_name, description=d.description,
                               parameters=d.parameters, function=fn))
    return reg


def _make_read_wrapper(descriptor, user) -> Callable[..., Any]:
    def wrapper(**kwargs):
        if not descriptor.allowed_for(user):
            return f"Permission denied: you lack {descriptor.rbac_feature} {descriptor.rbac_level} access."
        result = descriptor.func(**kwargs)
        return _maybe_redact_result(result)
    return wrapper


def _make_write_wrapper(descriptor, user, gate: Optional["ConfirmationGate"]) -> Callable[..., Any]:
    def wrapper(**kwargs):
        if not descriptor.allowed_for(user):
            return f"Permission denied: you lack {descriptor.rbac_feature} write access."
        if gate is None:
            return ("This is a state-changing action and needs explicit confirmation. "
                    "Ask the user to run it from the streaming assistant so they can approve it.")
        decision, token = gate.request_confirmation(descriptor, kwargs)
        if decision != "approve":
            return f"The user declined to run '{descriptor.name}'."
        try:
            result = descriptor.func(**kwargs)
            gate.mark_executed(token, result)
            _audit_tool_execute(descriptor, kwargs, user, ok=True)
            return result
        except Exception as exc:
            gate.mark_failed(token, str(exc))
            _audit_tool_execute(descriptor, kwargs, user, ok=False, error=str(exc))
            return f"Action '{descriptor.name}' failed: {exc}"
    return wrapper


def _audit_tool_execute(descriptor, params, user, *, ok: bool, error: Optional[str] = None) -> None:
    try:
        from app.services.audit_service import AuditService
        AuditService.log(
            action="ai.tool.execute" if ok else "ai.tool.failed",
            user_id=getattr(user, "id", None),
            target_type="ai_tool",
            target_id=descriptor.qualified_name,
            details={"params": params, "plugin_slug": descriptor.plugin_slug, "error": error},
        )
    except Exception:
        logger.debug("audit log failed for tool %s", descriptor.qualified_name, exc_info=True)


def summarize_action(descriptor, params: dict) -> str:
    first_line = (descriptor.description or descriptor.name).split("\n")[0].rstrip(".")
    if params:
        kv = ", ".join(f"{k}={v}" for k, v in params.items())
        return f"{first_line} ({kv})"
    return first_line


# ===========================================================================
# Conversation factory + persistence
# ===========================================================================
def build_conversation(row, user, mode: str, page_context: Optional[dict],
                       gate: Optional["ConfirmationGate"]) -> Conversation:
    """Create a fresh Conversation or resume from the stored export (re-supplying tools)."""
    from prompture import Conversation

    registry = build_tool_registry(user, mode, gate)
    system = build_system_prompt(user, mode, page_context)
    export = row.export
    if export:
        conv = Conversation.from_export(export, tools=registry)
        conv.system_prompt = system  # refresh page context each turn
        return conv
    return Conversation(
        model_name=row.model_name or current_model_name(),
        system_prompt=system,
        tools=registry,
        env=build_provider_env(),
        max_tool_rounds=(6 if mode == "assistant" else 0),
        max_tool_result_length=4000,
        max_cost=_max_cost(),
        budget_policy="degrade" if _fallback_models() else None,
        fallback_models=_fallback_models() or None,
        simulated_tools="auto",
        conversation_id=row.id,
    )


def _max_cost() -> Optional[float]:
    raw = _setting("ai_max_cost_usd", None)
    try:
        return float(raw) if raw not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        return None


def _fallback_models() -> list[str]:
    fb = _setting("ai_fallback_models", []) or []
    return [m for m in fb if m] if isinstance(fb, list) else []


def persist_conversation(row, conv: Conversation, *, page_context: Optional[dict] = None) -> None:
    """Persist the Prompture export + last page after a completed turn."""
    try:
        row.export = conv.export(strip_images=True)
    except Exception:
        logger.warning("Failed to export conversation %s", row.id, exc_info=True)
    if page_context and page_context.get("route"):
        row.last_page = page_context["route"][:256]
    db.session.add(row)
    db.session.commit()


def derive_title(message: str) -> str:
    text = (message or "").strip().replace("\n", " ")
    return (text[:60] + "…") if len(text) > 60 else (text or "New chat")


# ===========================================================================
# In-process invocation (used by plugins via app.plugins_sdk.ai)
# ===========================================================================
def _oneshot_conversation(user, mode: str, page_context: Optional[dict]) -> Conversation:
    from prompture import Conversation

    ensure_initialized()
    registry = build_tool_registry(user, mode, gate=None)
    system = build_system_prompt(user, mode, page_context)
    return Conversation(
        model_name=current_model_name(),
        system_prompt=system,
        tools=registry,
        env=build_provider_env(),
        max_tool_rounds=(6 if mode == "assistant" else 0),
        max_tool_result_length=4000,
        simulated_tools="auto",
    )


def oneshot_ask(user, prompt: str, *, mode: str = "simple",
                page_context: Optional[dict] = None) -> str:
    """Single-shot assistant call (no persistence) for in-process callers."""
    conv = _oneshot_conversation(user, mode, page_context)
    return conv.ask(redact_input(prompt))


def oneshot_stream(user, prompt: str, *, mode: str = "simple",
                   page_context: Optional[dict] = None) -> Iterator[str]:
    """Single-shot streaming assistant call yielding text chunks."""
    conv = _oneshot_conversation(user, mode, page_context)
    yield from conv.ask_stream(redact_input(prompt))


# ===========================================================================
# Live event mapping
# ===========================================================================
def live_event_to_frame(event) -> tuple[str, dict]:
    """Map a Prompture LiveEvent to an (sse_event_name, data) pair."""
    data = dataclasses.asdict(event) if dataclasses.is_dataclass(event) else dict(getattr(event, "__dict__", {}))
    name = data.pop("event_type", None) or getattr(event, "event_type", "message")
    return name, data


# ===========================================================================
# Confirmation gate (human-in-the-loop for write tools)
# ===========================================================================
class ConfirmationGate:
    """Pauses the streaming worker thread on a write tool until the user decides.

    The write-tool wrapper calls :meth:`request_confirmation`, which persists an
    ``AiPendingAction`` row, emits a ``pending_action`` SSE frame, and blocks on a
    ``threading.Event``. ``/chat/confirm`` calls :meth:`resolve` (in-memory) to
    unblock it. Because this runs in a dedicated worker thread (not the gevent
    hub), blocking here doesn't stall the rest of the panel.
    """

    def __init__(self, conversation_id: str, user_id: int, emit: Callable[[str, dict], None],
                 cancel_event: threading.Event, ttl_seconds: int):
        self.conversation_id = conversation_id
        self.user_id = user_id
        self._emit = emit
        self._cancel = cancel_event
        self._ttl = ttl_seconds
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()

    def request_confirmation(self, descriptor, params: dict) -> tuple[str, str]:
        """Block until the user approves/denies. Returns ('approve'|'deny', token)."""
        from app.models.ai import AiPendingAction

        token = secrets.token_urlsafe(16)
        summary = summarize_action(descriptor, params)
        row = AiPendingAction(
            id=token, conversation_id=self.conversation_id, user_id=self.user_id,
            tool_name=descriptor.qualified_name, plugin_slug=descriptor.plugin_slug,
            summary=summary, status=AiPendingAction.STATUS_PENDING,
            expires_at=AiPendingAction.make_expiry(self._ttl),
        )
        row.params = params
        try:
            db.session.add(row)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.warning("Failed to persist pending action", exc_info=True)

        ev = threading.Event()
        with self._lock:
            self._pending[token] = {"event": ev, "decision": None}
        self._emit("pending_action", {
            "action_token": token, "tool_name": descriptor.qualified_name,
            "name": descriptor.name, "plugin_slug": descriptor.plugin_slug,
            "summary": summary, "params": params, "is_write": True,
        })

        signaled = ev.wait(timeout=self._ttl)
        with self._lock:
            info = self._pending.pop(token, {})

        if self._cancel.is_set():
            decision = "deny"
        elif not signaled:
            decision = "expired"
        else:
            decision = info.get("decision") or "deny"

        self._update_status(token, decision)
        return ("approve" if decision == "approve" else "deny"), token

    def resolve(self, token: str, decision: str) -> bool:
        """Called from /chat/confirm (in-memory). Returns True if the token was pending."""
        with self._lock:
            info = self._pending.get(token)
            if not info:
                return False
            info["decision"] = "approve" if decision == "approve" else "deny"
            info["event"].set()
        return True

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def mark_executed(self, token: str, result: Any) -> None:
        self._update_status(token, "executed", result=result)

    def mark_failed(self, token: str, error: str) -> None:
        self._update_status(token, "failed", result={"error": error})

    def _update_status(self, token: str, decision: str, result: Any = None) -> None:
        from app.models.ai import AiPendingAction
        status_map = {
            "approve": AiPendingAction.STATUS_APPROVED,
            "deny": AiPendingAction.STATUS_DENIED,
            "expired": AiPendingAction.STATUS_EXPIRED,
            "executed": AiPendingAction.STATUS_EXECUTED,
            "failed": AiPendingAction.STATUS_FAILED,
        }
        try:
            row = db.session.get(AiPendingAction, token)
            if row:
                row.status = status_map.get(decision, row.status)
                if result is not None:
                    row.result = result
                db.session.add(row)
                db.session.commit()
        except Exception:
            db.session.rollback()


def register_gate(conversation_id: str, gate: ConfirmationGate) -> None:
    with _gates_lock:
        _active_gates[conversation_id] = gate


def unregister_gate(conversation_id: str) -> None:
    with _gates_lock:
        _active_gates.pop(conversation_id, None)


def resolve_pending(conversation_id: str, token: str, decision: str) -> bool:
    with _gates_lock:
        gate = _active_gates.get(conversation_id)
    if gate is None:
        return False
    return gate.resolve(token, decision)
