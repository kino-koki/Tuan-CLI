"""goal 命令 —— 持久化 Goal 状态只读查看 (第 114 个独特功能)。

GoalEngine (core/goal_mode.py) 把目标拆解执行状态落盘到
``<workspace>/.tuan/goal.json`` (goal_id/description/status/iterations/created_at/
steps[]), 供新会话续用。但该状态此前**只能在一个活着的 REPL 会话里**用
``/goal`` 查看 —— 外部脚本/CI 无法脱离会话看到: 工作区里有没有活动目标、
目标是什么、拆成几步、各步状态、进展到第几步、是否已达上限。本命令补上
独立只读面 (纯只读, 直接解析 goal.json, 不构造 GoalEngine —— 避免任何写路径,
也不 mkdir)。

差异化价值: Claude Code 的 goal/任务状态只存在于交互会话内; 本命令把目标
状态变成可被任何进程审计的持久事实, 并给出进度条与"未完成任务"清单。

  tuan goal status [--workspace DIR] [--json]   # 查看当前目标与步骤进度
  tuan goal steps [--workspace DIR] [--json]    # 列出全部步骤 (含未完成)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command

_ICONS = {"pending": "☐", "in_progress": "◔", "done": "☑", "failed": "✗"}
_LABELS = {"pending": "待办", "in_progress": "进行中", "done": "已完成", "failed": "失败"}


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env = os.environ.get("TUAN_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _goal_path(workspace: Path) -> Path:
    return workspace / ".tuan" / "goal.json"


def _load(path: Path) -> Optional[Dict[str, Any]]:
    """直接解析 goal.json (纯只读); 文件缺失/损坏/无目标返回 None。"""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        isinstance(data, dict)
        and data.get("description")
        and isinstance(data.get("steps"), list)
    ):
        return data
    return None


def _progress(state: Dict[str, Any]) -> tuple:
    steps = state.get("steps", [])
    total = len(steps)
    done = sum(1 for s in steps if s.get("status") == "done")
    pct = round(done * 100 / total) if total else 0
    return done, total, pct


def _fmt_status(status: str) -> str:
    return f"{_ICONS.get(status, '☐')} {_LABELS.get(status, status)}"


def cmd_goal(args: Any) -> int:
    """持久化 Goal 状态只读查看 (第 114 个独特功能, 纯只读)。"""
    sub = getattr(args, "goal_cmd", None) or "status"
    json_mode = bool(getattr(args, "json", False))
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    path = _goal_path(workspace)
    state = _load(path)

    def _summary_payload() -> Dict[str, Any]:
        if state is None:
            return {"workspace": str(workspace), "goal_file": str(path),
                    "initialized": False, "active": False, "goal": None}
        done, total, pct = _progress(state)
        return {
            "workspace": str(workspace),
            "goal_file": str(path),
            "initialized": True,
            "active": bool(state.get("status") == "in_progress"),
            "goal": state,
            "progress": {"done": done, "total": total, "percent": pct},
            "remaining": [
                {"id": s.get("id"), "description": s.get("description"),
                 "status": s.get("status")}
                for s in state.get("steps", []) if s.get("status") != "done"
            ],
        }

    if sub == "status":
        if json_mode:
            print(json.dumps(_summary_payload(), ensure_ascii=False, indent=2))
            return 0
        if state is None:
            console.print("[dim]工作区尚无活动目标 (无 .tuan/goal.json; "
                          "用 /goal <描述> 设置后自动建立)[/dim]")
            return 0
        console.print(f"[bold]=== Goal · {workspace} ===[/bold]")
        console.print(f"  {path}")
        console.print(f"  目标: {state.get('description', '')}")
        console.print(f"  状态: {_fmt_status(str(state.get('status', '?')))}")
        console.print(f"  迭代: {state.get('iterations', 0)} · 创建于 {state.get('created_at', '-')}")
        done, total, pct = _progress(state)
        bar_w = 24
        filled = round(bar_w * done / total) if total else 0
        bar = "█" * filled + "░" * (bar_w - filled)
        console.print(f"  进度: [{bar}] {done}/{total} ({pct}%)\n")
        for s in state.get("steps", []):
            icon = _ICONS.get(str(s.get("status", "pending")), "☐")
            console.print(f"    {icon} {s.get('id', '?')}. {s.get('description', '')}")
            note = s.get("note")
            if note:
                console.print(f"        [dim]{note}[/dim]")
        return 0

    elif sub == "steps":
        if json_mode:
            print(json.dumps(_summary_payload(), ensure_ascii=False, indent=2))
            return 0
        if state is None:
            console.print("[dim]工作区尚无活动目标[/dim]")
            return 0
        remaining = [s for s in state.get("steps", []) if s.get("status") != "done"]
        if remaining:
            console.print(f"[bold]未完成步骤 ({len(remaining)}):[/bold]")
            for s in remaining:
                icon = _ICONS.get(str(s.get("status", "pending")), "☐")
                console.print(f"    {icon} {s.get('id', '?')}. {s.get('description', '')}")
        else:
            console.print("[dim]所有步骤已完成[/dim]")
        return 0

    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: status / steps")
        return 1


_register_command("cmd_goal", ".cmd_goal")
