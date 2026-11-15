"""subagent 命令 —— 子代理类型注册表可观测性 (第 90 个独特功能)。

暴露 :mod:`tuan_cli.core.agent_types` 的只读查询面:
- **类型清单**: 内置 (general-purpose/explore/plan/coder) + 自定义
  (用户放在 <TUAN_HOME>/agents/*.md) 全部可委派类型;
- **能力边界**: 每种类型的只读护栏 (read_only=True 物理防写)、
  角色指令 (system_extra)、自定义来源标注;
- **注册表状态**: 自定义文件路径、加载状态、与内置同名的被忽略项。

差异化价值: Claude Code 的 subagent 类型只在 task 工具的 enum 里黑箱出现,
用户无法独立查询"有哪些可委派类型、各自的只读/能力边界是什么、自定义
类型从哪里来"。本命令把 agent_types 注册表开放为可查询, 纯只读。

  tuan subagent types [--json]         # 全部类型 + 能力边界
  tuan subagent types <name> [--json]  # 单个类型的详情
  tuan subagent refresh [--json]       # 重新扫描 <home>/agents/*.md (只读加载)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ._ui_singleton import console
from .parser import _register_command


def _builtin_names() -> List[str]:
    from ..core.agent_types import _BUILTIN_TYPES
    return [t.name for t in _BUILTIN_TYPES]


def _type_to_dict(t: Any) -> Dict[str, Any]:
    return {
        "name": getattr(t, "name", ""),
        "description": getattr(t, "description", ""),
        "read_only": bool(getattr(t, "read_only", False)),
        "system_extra": getattr(t, "system_extra", ""),
        "custom": False,
    }


def _scan_custom(home: Any) -> List[Dict[str, Any]]:
    """扫描自定义类型文件 (不依赖进程内缓存, 纯读盘)。"""
    from ..core.agent_types import AgentType, _parse_agent_file

    out: List[Dict[str, Any]] = []
    agents_dir = __import__("pathlib").Path(home) / "agents"
    if not agents_dir.is_dir():
        return out
    for path in sorted(agents_dir.glob("*.md")):
        at = _parse_agent_file(path)
        if at is None:
            continue
        out.append({
            "name": at.name,
            "file": str(path),
            "description": at.description,
            "read_only": at.read_only,
            "system_extra": at.system_extra,
            "custom": True,
        })
    return out


def cmd_subagent(args: Any) -> int:
    """subagent 主入口: 子代理类型注册表可观测 (纯只读)。"""
    sub = getattr(args, "subagent_cmd", None) or "types"
    json_mode = bool(getattr(args, "json", False))

    from ..core.agent_types import all_types, get_agent_type
    from ..config.loader import home_dir

    home = home_dir()
    builtin = _builtin_names()

    if sub == "refresh":
        from ..core.agent_types import load_custom_types
        custom = load_custom_types(home)
        if json_mode:
            print(json.dumps({
                "loaded": len(custom),
                "types": [{"name": t.name, "read_only": t.read_only} for t in custom],
            }, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[green]✓ 已重新扫描自定义类型[/green] "
                      f"{len(custom)} 个 ([dim]{home}/agents/*.md[/dim])")
        return 0

    if sub == "types":
        name = str(getattr(args, "name", "") or "").strip()
        if name:
            t = get_agent_type(name)
            if t is None:
                console.print(f"[red]未知子代理类型: {name}[/red]")
                return 1
            d = _type_to_dict(t)
            d["custom"] = name not in builtin
            if d["custom"]:
                for c in _scan_custom(home):
                    if c["name"] == name:
                        d.update(c)
                        break
            if json_mode:
                print(json.dumps(d, ensure_ascii=False, indent=2))
                return 0
            console.print(f"[bold]{t.name}[/bold] "
                          f"· {'[yellow]只读(物理防写)[/yellow]' if t.read_only else '[green]可写[/green]'}")
            console.print(f"  描述: {t.description}")
            if t.system_extra:
                console.print("  角色指令:")
                for line in t.system_extra.split("\n"):
                    console.print(f"    {line}")
            return 0

        # 全部类型
        types = all_types()
        custom_map = {c["name"]: c for c in _scan_custom(home)}
        if json_mode:
            print(json.dumps({
                "count": len(types),
                "builtin_count": sum(1 for t in types if t.name in builtin),
                "custom_count": sum(1 for t in types if t.name not in builtin),
                "types": [_type_to_dict(t) for t in types],
            }, ensure_ascii=False, indent=2))
            return 0
        if not types:
            console.print("[green]✓ 无子代理类型[/green]")
            return 0
        console.print(f"[bold]子代理类型注册表 ({len(types)} 个)[/bold]\n")
        for t in types:
            is_builtin = t.name in builtin
            flag = "[dim](内置)[/dim]" if is_builtin else "[cyan](自定义)[/cyan]"
            rw = "[yellow]只读[/yellow]" if t.read_only else "[green]可写[/green]"
            console.print(f"  [green]{t.name:<18s}[/green] {rw} {flag}")
            console.print(f"      [dim]{t.description[:60]}[/dim]")
        console.print("\n[dim]详情: tuan subagent types <name> · "
                      "自定义来源: <TUAN_HOME>/agents/*.md[/dim]")
        return 0

    console.print(f"[red]未知 subagent 子命令: {sub}[/red]")
    return 1


_register_command("cmd_subagent", ".cmd_subagent")
