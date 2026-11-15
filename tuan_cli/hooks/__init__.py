"""B3 hooks 子系统公共入口。

导出 manager / triggers 中已存在的符号；session / diagnostics / provider
等公共 API 从 triggers 汇总以便外部直接 ``from tuan_cli.hooks import ...``。
"""
from __future__ import annotations

from .manager import (
    HookManager, HookDecision, HOOK_EVENTS,
    CORE_HOOK_EVENTS, EXTENDED_HOOK_EVENTS, OFFICIAL_EXTRA_EVENTS,
    ON_FAILURE_POLICIES, DEFAULT_ON_FAILURE,
)
from .triggers import (
    HookTrigger, SessionHandle,
    set_default_hooks_provider, get_default_hooks_provider,
    current_session_hooks, default_hooks_resolver,
    register_session, unregister_session, resolve_session,
    current_session_owner, set_session_owner, reset_session_owner,
    owner_miss_stats, hooks_for_owner,
    session_registry_diagnostics, bind_session_hooks,
    activate_session, deactivate_session, session_scope,
    close_agent_session, provider_diagnostics,
)

__all__ = [
    "HookManager", "HookDecision", "HOOK_EVENTS",
    "CORE_HOOK_EVENTS", "EXTENDED_HOOK_EVENTS", "OFFICIAL_EXTRA_EVENTS",
    "ON_FAILURE_POLICIES", "DEFAULT_ON_FAILURE",
    "HookTrigger", "SessionHandle",
    "set_default_hooks_provider", "get_default_hooks_provider",
    "current_session_hooks", "default_hooks_resolver",
    "register_session", "unregister_session", "resolve_session",
    "current_session_owner", "set_session_owner", "reset_session_owner",
    "owner_miss_stats", "hooks_for_owner",
    "session_registry_diagnostics", "bind_session_hooks",
    "activate_session", "deactivate_session", "session_scope",
    "close_agent_session", "provider_diagnostics",
]
