"""Process-global registry of AI tools (core primitive — powered by Prompture).

This is the aggregation point that makes the assistant *extensible*: built-in
``core.*`` tools plus tools contributed by installed plugins all live here. The
assistant builds a fresh Prompture ``ToolRegistry`` per request from these
descriptors, filtered by the requesting user's RBAC and the chat mode.

Singleton shape mirrors ``agent_registry`` (``__new__`` + ``_lock`` +
module-level instance) so all in-memory tool state lives in the one gevent
worker process — consistent with the rest of ServerKit.

Plugins register through ``app.plugins_sdk.ai`` (see plugins_sdk/ai.py); the
qualified tool name is always ``<plugin-slug>__<name>`` (or ``core__<name>``)
so plugin tools can never collide with each other or with built-ins. The double
underscore keeps names within the ``^[A-Za-z0-9_-]+$`` shape required by OpenAI
and Anthropic function-calling (dots are NOT allowed there).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Optional

# `tool_from_function` is imported inside register() rather than here: this
# module is reachable at import time from app/api/ai.py and app/plugins_sdk/ai.py,
# and pulling prompture costs ~69 MB of RSS in every panel process. Registration
# only happens once someone actually uses the assistant. See ai_service.py's
# import note and backend/tests/test_ai_lazy_import.py.

logger = logging.getLogger(__name__)

CORE_PREFIX = "core"
# OpenAI caps function names at 64 chars; keep qualified names within that.
MAX_TOOL_NAME_LEN = 64


@dataclass
class ToolDescriptor:
    """Metadata + callable for one registered tool."""
    name: str                       # bare name as registered by the author
    qualified_name: str             # '<slug-or-core>__<name>' — the LLM-facing name
    func: Callable[..., Any]
    description: str
    parameters: dict                # JSON Schema (derived once via tool_from_function)
    plugin_slug: Optional[str] = None   # None => built-in
    rbac_feature: Optional[str] = None  # e.g. 'docker'; None => any authenticated user
    rbac_level: str = "read"            # 'read' | 'write'
    is_write: bool = False              # write tools go through the confirmation handshake
    admin_only: bool = False            # raw host operations mirror REST's admin gate

    def allowed_for(self, user) -> bool:
        """True if *user* may use this tool given its RBAC tagging."""
        if user is None or not getattr(user, 'is_active', True):
            return False
        if self.admin_only and not getattr(user, 'is_admin', False):
            return False
        if self.rbac_feature is None:
            return True
        try:
            return bool(user.has_permission(self.rbac_feature, self.rbac_level))
        except Exception:
            return False


@dataclass
class ContextProvider:
    """A plugin-registered callable that augments the system prompt for a route."""
    plugin_slug: Optional[str]
    route_pattern: str
    func: Callable[..., Any]   # fn(user, route, params) -> str | dict | None


class AiToolRegistry:
    """Singleton registry of built-in + plugin-contributed AI tools."""

    _instance: Optional["AiToolRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tools: dict[str, ToolDescriptor] = {}          # keyed by qualified_name
        self._by_plugin: dict[str, set[str]] = {}            # prefix -> {qualified_name}
        self._context_providers: list[ContextProvider] = []
        self._mutex = threading.Lock()
        self._discovered = False                             # plugin discovery has run?

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(
        self,
        *,
        name: str,
        func: Callable[..., Any],
        description: Optional[str] = None,
        plugin_slug: Optional[str] = None,
        rbac_feature: Optional[str] = None,
        rbac_level: str = "read",
        is_write: bool = False,
        admin_only: bool = False,
    ) -> ToolDescriptor:
        """Register a tool callable. Idempotent per qualified name (re-register overwrites)."""
        prefix = plugin_slug or CORE_PREFIX
        qualified = f"{prefix}__{name}"
        if len(qualified) > MAX_TOOL_NAME_LEN:
            logger.warning("AI tool name too long, truncating: %s", qualified)
            qualified = qualified[:MAX_TOOL_NAME_LEN]
        # Derive the JSON-Schema parameters + description once, from the real signature.
        from prompture.agents.tools_schema import tool_from_function

        td = tool_from_function(func, name=qualified, description=description)
        descriptor = ToolDescriptor(
            name=name,
            qualified_name=qualified,
            func=func,
            description=td.description,
            parameters=td.parameters,
            plugin_slug=plugin_slug,
            rbac_feature=rbac_feature,
            rbac_level=("write" if is_write else rbac_level),
            is_write=is_write,
            admin_only=admin_only,
        )
        with self._mutex:
            self._tools[qualified] = descriptor
            self._by_plugin.setdefault(prefix, set()).add(qualified)
        logger.debug("Registered AI tool %s (write=%s, rbac=%s/%s)",
                     qualified, is_write, rbac_feature, descriptor.rbac_level)
        return descriptor

    def register_context_provider(self, route_pattern: str, func: Callable[..., Any],
                                  plugin_slug: Optional[str] = None) -> None:
        """Register a callable that contributes page context for matching routes."""
        with self._mutex:
            self._context_providers.append(ContextProvider(plugin_slug, route_pattern, func))

    # ------------------------------------------------------------------
    # Lifecycle (called by plugin_service on install/enable/disable/uninstall)
    # ------------------------------------------------------------------
    def unregister_plugin(self, slug: str) -> None:
        """Drop all AI contributions supplied by a plugin."""
        with self._mutex:
            for qn in self._by_plugin.pop(slug, set()):
                self._tools.pop(qn, None)
            self._context_providers = [
                cp for cp in self._context_providers if cp.plugin_slug != slug
            ]
        from app.services.ai_attachment_registry import ai_attachment_registry
        ai_attachment_registry.unregister_plugin(slug)
        logger.info("Unregistered AI tools for plugin '%s'", slug)

    def reload_plugin(self, slug: str) -> None:
        """Re-import and re-register a plugin's AI contributions (install/enable)."""
        self.unregister_plugin(slug)
        try:
            self._import_plugin_ai(slug)
        except Exception:
            logger.warning("Failed to (re)load AI tools for plugin '%s'", slug, exc_info=True)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover_plugins(self) -> None:
        """Import + register AI contributions from every active plugin (once)."""
        if self._discovered:
            return
        try:
            from app.models.plugin import InstalledPlugin
            rows = InstalledPlugin.query.filter_by(status=InstalledPlugin.STATUS_ACTIVE).all()
        except Exception:
            logger.warning("AI plugin discovery: could not query installed plugins", exc_info=True)
            self._discovered = True
            return
        for plugin in rows:
            manifest = plugin.manifest or {}
            if not isinstance(manifest.get("ai"), dict):
                continue
            try:
                self._import_plugin_ai(plugin.slug, manifest=manifest)
            except Exception:
                # One broken plugin must never kill discovery (mirrors load_all_plugins).
                logger.warning("AI discovery failed for plugin '%s'", plugin.slug, exc_info=True)
        self._discovered = True

    def _import_plugin_ai(self, slug: str, manifest: Optional[dict] = None) -> None:
        """Import a single plugin's AI entry point and call its register(binder)."""
        import importlib

        from app.models.plugin import InstalledPlugin

        if manifest is None:
            plugin = InstalledPlugin.query.filter_by(slug=slug).first()
            manifest = (plugin.manifest if plugin else {}) or {}
        ai_block = manifest.get("ai")
        if not isinstance(ai_block, dict):
            return
        entry_point = ai_block.get("entry_point")
        if not entry_point:
            return
        module_name, _, attr = entry_point.partition(":")
        attr = attr or "register"
        full_module = f"app.plugins.{slug}.{module_name}"
        mod = importlib.import_module(full_module)
        register_fn = getattr(mod, attr)

        # Bind registration to this plugin's slug. Imported lazily to avoid a
        # circular import (plugins_sdk.ai imports this registry).
        from app.plugins_sdk.ai import PluginToolBinder
        register_fn(PluginToolBinder(slug))
        logger.info("Registered AI contributions for plugin '%s'", slug)

    # ------------------------------------------------------------------
    # Query (used by ai_service per request)
    # ------------------------------------------------------------------
    def list_for(self, user, mode: str) -> list[ToolDescriptor]:
        """Tools available to *user* in *mode* (simple mode → none)."""
        if mode != "assistant":
            return []
        with self._mutex:
            descriptors = list(self._tools.values())
        return [d for d in descriptors if d.allowed_for(user)]

    def get(self, qualified_name: str) -> Optional[ToolDescriptor]:
        with self._mutex:
            return self._tools.get(qualified_name)

    def all_descriptors(self) -> list[ToolDescriptor]:
        with self._mutex:
            return list(self._tools.values())

    def context_providers_for(self, route: str) -> list[ContextProvider]:
        """Context providers whose route pattern matches *route* (fnmatch)."""
        with self._mutex:
            providers = list(self._context_providers)
        return [cp for cp in providers if _route_matches(cp.route_pattern, route)]


def _route_matches(pattern: str, route: str) -> bool:
    if not pattern or not route:
        return False
    if pattern == route:
        return True
    # Support fnmatch globs ('/git/*') and a trailing-segment convenience match.
    return fnmatch(route, pattern) or route.startswith(pattern.rstrip("/*") + "/")


# Module-level singleton — import as: from app.services.ai_tool_registry import ai_tool_registry
ai_tool_registry = AiToolRegistry()
