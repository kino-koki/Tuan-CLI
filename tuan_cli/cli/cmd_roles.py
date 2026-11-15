"""`tuan roles` —— 专业化角色系统查询 (第 45 个独特功能)。

Claude Code 只有单一 agent, 没有「角色」概念。Tuan-CLI 的 specialized_roles
(core/specialized_roles.py) 预注册 7 个专业化角色 (reviewer/tester/debugger/
architect/security_auditor/documenter/implementer), 每个角色有专属系统提示、
推荐工具集、质量标准、协作协议。本命令把这套角色系统变成可查询的第一方视图:

    tuan roles list                        # 列出全部角色 (id/名称/描述/档位)
    tuan roles get <id>                    # 查看单个角色详情 (系统提示/质量标准/工具)
    tuan roles suggest <任务描述>          # 按关键词推荐角色 (差异化)
    tuan roles list --json                 # 机器可读

差异化价值:
- 角色透明化: 用户能看到每个角色的系统提示/质量标准/协作协议, 而非黑盒。
- 角色推荐: suggest 用关键词匹配推荐角色 (Claude Code 无此概念)。
- 只读查询, 零副作用; 未来可挂 agents (角色委派) 复用同一注册表。
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

from ..ui.plain_console import console


def _role_brief(r: Any) -> Dict[str, Any]:
    """角色 → 摘要 dict (JSON 友好)。"""
    return {
        "role_id": r.role_id,
        "name": r.name,
        "description": r.description,
        "recommended_tools": sorted(r.recommended_tools),
        "excluded_tools": sorted(r.excluded_tools),
        "quality_criteria": list(r.quality_criteria),
        "collaboration_hints": list(r.collaboration_hints),
        "max_iterations": r.max_iterations,
        "preferred_model_tier": r.preferred_model_tier,
    }


def _cmd_roles_list(args: Any, json_mode: bool) -> int:
    """roles list: 列出全部角色。"""
    from ..core.specialized_roles import list_roles

    roles = list_roles()
    if json_mode:
        sys.stdout.write(__import__("json").dumps(
            {"count": len(roles), "roles": [_role_brief(r) for r in roles]},
            ensure_ascii=False, indent=2,
        ) + "\n")
        return 0

    console.print(f"[bold]专业化角色[/bold] ({len(roles)} 个)\n")
    for r in roles:
        tier_map = {"strong": "强模型", "weak": "弱模型", "any": "任意"}
        tier = tier_map.get(r.preferred_model_tier, r.preferred_model_tier)
        console.print(
            f"  [cyan]{r.role_id:<18}[/cyan] {r.name:<6}  "
            f"[dim]({tier}, 迭代≤{r.max_iterations})[/dim]"
        )
        console.print(f"    [dim]{r.description[:60]}{'…' if len(r.description) > 60 else ''}[/dim]")
    console.print("\n提示: tuan roles get <id> 看详情; tuan roles suggest <任务> 推荐角色")
    return 0


def _cmd_roles_get(args: Any, json_mode: bool) -> int:
    """roles get: 查看单个角色详情。"""
    import json

    from ..core.specialized_roles import get_role

    role_id = getattr(args, "role_id", "") or ""
    r = get_role(role_id)
    if r is None:
        from ..core.specialized_roles import list_roles
        avail = ", ".join(x.role_id for x in list_roles())
        console.print(f"[red]未找到角色: {role_id}[/red] (可用: {avail})")
        return 1

    brief = _role_brief(r)
    if json_mode:
        sys.stdout.write(json.dumps(brief, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print(f"[bold]{r.name}[/bold] ([cyan]{r.role_id}[/cyan])")
    console.print(f"  描述: {r.description}")
    console.print(f"  模型档位: {r.preferred_model_tier}  迭代上限: {r.max_iterations}")
    console.print("\n[bold]系统提示[/bold]:")
    for line in r.system_prompt.splitlines():
        console.print(f"  {line}")
    if r.recommended_tools:
        console.print(f"\n[bold]推荐工具 ({len(r.recommended_tools)})[/bold]: {', '.join(sorted(r.recommended_tools))}")
    if r.excluded_tools:
        console.print(f"[bold]排除工具[/bold]: {', '.join(sorted(r.excluded_tools))}")
    if r.quality_criteria:
        console.print("\n[bold]质量标准[/bold]:")
        for c in r.quality_criteria:
            console.print(f"  - {c}")
    if r.collaboration_hints:
        console.print("\n[bold]协作协议[/bold]:")
        for h in r.collaboration_hints:
            console.print(f"  - {h}")
    return 0


def _cmd_roles_suggest(args: Any, json_mode: bool) -> int:
    """roles suggest: 按关键词推荐角色。"""
    import json

    from ..core.specialized_roles import get_role, suggest_role

    task = getattr(args, "task", "") or ""
    if not task.strip():
        console.print("[dim]请提供任务描述: tuan roles suggest <任务>[/dim]")
        return 1
    role_id = suggest_role(task)
    r = get_role(role_id)
    if json_mode:
        sys.stdout.write(json.dumps({
            "task": task,
            "suggested_role": role_id,
            "name": r.name if r else role_id,
            "description": r.description if r else "",
        }, ensure_ascii=False, indent=2) + "\n")
        return 0
    if r:
        console.print(f"任务: [dim]{task}[/dim]")
        console.print(f"推荐角色: [bold cyan]{r.name}[/bold cyan] ([cyan]{role_id}[/cyan])")
        console.print(f"  [dim]{r.description[:80]}{'…' if len(r.description) > 80 else ''}[/dim]")
    return 0


def cmd_roles(args: Any) -> int:
    """`tuan roles` 入口: 专业化角色系统查询。"""
    sub = getattr(args, "roles_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))

    if sub == "get":
        return _cmd_roles_get(args, json_mode)
    if sub == "suggest":
        return _cmd_roles_suggest(args, json_mode)
    # 默认 list
    return _cmd_roles_list(args, json_mode)


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_roles", ".cmd_roles")
