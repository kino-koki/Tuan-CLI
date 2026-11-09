"""用户级 Hooks —— 让用户在 Agent 工具执行前/后挂载自己的脚本。

对标 Claude Code 的 Hooks 模型, 但更克制、更贴合青小团的"最小影响半径"哲学:
- 命令强制 list(argv) 形式, 绝不接受裸 shell 字符串 → 杜绝 `; rm -rf` 类注入。
- 超时强杀, 单个 hook 异常不影响主流程 (fail-safe, 不阻断)。
- PreToolUse 的"阻断权"与"改参权"默认需显式声明, 不静默赋予。
- 所有 hook 调用写入审计事件 (kernel.emit("hook.executed"))。
"""

from .manager import (
    HookManager, HookDecision, HookFailure,
    HOOK_EVENTS, CORE_HOOK_EVENTS, EXTENDED_HOOK_EVENTS,
)
from .triggers import HookTrigger, set_default_hooks_provider, \
    get_default_hooks_provider, provider_diagnostics, \
    current_session_hooks, bind_session_hooks, \
    register_session, unregister_session, resolve_session, \
    session_registry_diagnostics, current_session_owner, \
    set_session_owner, reset_session_owner, owner_miss_stats, \
    hooks_for_owner, activate_session, deactivate_session, SessionHandle, \
    session_scope

__all__ = [
    "HookManager", "HookDecision", "HookFailure",
    "HOOK_EVENTS", "CORE_HOOK_EVENTS", "EXTENDED_HOOK_EVENTS",
    "HookTrigger", "set_default_hooks_provider", "get_default_hooks_provider",
    "provider_diagnostics", "current_session_hooks", "bind_session_hooks",
    "register_session", "unregister_session", "resolve_session",
    "session_registry_diagnostics", "current_session_owner",
    "set_session_owner", "reset_session_owner", "owner_miss_stats",
    "hooks_for_owner", "activate_session", "deactivate_session",
    "SessionHandle", "session_scope",
]
