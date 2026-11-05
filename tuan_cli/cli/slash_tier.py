"""Slash command tiering — core/expert/hidden layers (§2.3).

分层不影响 list_slash_commands() 的全集 (55 个)，
只影响 TUI 补全菜单的显示层。
"""

from __future__ import annotations

# 核心层 (≤20): / 菜单直接显示
CORE_SLASH_COMMANDS: frozenset[str] = frozenset({
    "/help", "/model", "/mode", "/memory", "/clear",
    "/compact", "/context", "/cost", "/usage", "/undo",
    "/diff", "/export", "/exit", "/status", "/tools",
    "/skills", "/mcp", "/permissions", "/web", "/plan",
})

# 专家层: 折叠，需第二字符或 /more 展开
EXPERT_SLASH_COMMANDS: frozenset[str] = frozenset({
    "/audit", "/blast", "/budget", "/checkpoint", "/effort",
    "/gh-borrow", "/goal", "/hooks", "/image", "/images",
    "/impact", "/import", "/log", "/mcp-tools", "/more",
    "/offline", "/provider", "/route", "/sandbox", "/stats",
    "/subagent", "/swarm", "/verify", "/rewind", "/handoff",
    "/worktree", "/workflow", "/code", "/commands", "/personality",
    "/add-dir", "/init", "/resume", "/language",
})


def slash_command_tier(name: str) -> str:
    """返回 slash 命令的层级: core / expert / hidden."""
    if name in CORE_SLASH_COMMANDS:
        return "core"
    if name in EXPERT_SLASH_COMMANDS:
        return "expert"
    return "hidden"


def filter_slash_commands(names: list[str], *, include_expert: bool = False) -> list[str]:
    """按层级过滤 slash 命令列表。

    默认只返回核心层命令。include_expert=True 时包含专家层。
    隐藏层永远不返回（仅 /help 全量列出）。
    """
    result = []
    for name in names:
        tier = slash_command_tier(name)
        if tier == "core":
            result.append(name)
        elif tier == "expert" and include_expert:
            result.append(name)
    return result


def slash_command_tiers() -> dict[str, str]:
    """枚举内置命令 -> tier 的映射表 (供 TUI 补全过滤器使用)。

    从 cmd_slash.SLASH_COMMAND_NAMES 获取命令全集，确保补全菜单与
    可执行命令列表一致。用户自定义热插拔命令归入 expert。
    """
    try:
        from .cmd_slash import SLASH_COMMAND_NAMES
        names = list(SLASH_COMMAND_NAMES)
    except Exception:  # noqa: BLE001
        names = []
    tiers = {n: slash_command_tier(n) for n in names}
    # 尝试加载用户自定义命令 (归入 expert)
    try:
        from . import user_commands as _uc
        for item in _uc.describe_commands():
            n = f"/{item['name']}"
            if n not in tiers:
                tiers[n] = "expert"
    except Exception:  # noqa: BLE001
        pass
    return tiers
