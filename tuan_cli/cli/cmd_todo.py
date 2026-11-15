"""todo 命令 —— 持久化任务清单只读查看 (第 112 个独特功能)。

todo_write 工具 (tools/todo_tool.py) 把会话任务清单落盘到
``<workspace>/.tuan/todo.json``, 供新会话/新 Agent 恢复进度 (跨会话不丢失)。
但该清单此前**只能在一个活着的 REPL 会话里**用 ``/todos`` 查看 —— 外部
脚本、CI、或不想启动整个会话的用户完全看不到: 工作区里到底有没有任务清单、
各步骤状态、进度百分比。本命令补上独立只读面 (纯只读, 只调 load_disk_todos,
不调 save_disk_todos 写路径, 也不 mkdir)。

差异化价值: Claude Code 的 TodoWrite 状态只存在于交互会话内, 没有"脱离会话
检查任务清单"的只读 CLI。本命令让任务清单成为工作区里可被任何进程审计的
持久事实。

  tuan todo list [--workspace DIR] [--json]    # 列出工作区任务清单
  tuan todo show <序号> [--workspace DIR]      # 查看单个步骤详情
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command

_ICONS = {"pending": "☐", "in_progress": "◔", "completed": "☑"}
_LABELS = {"pending": "待办", "in_progress": "进行中", "completed": "已完成"}


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env = os.environ.get("TUAN_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _load(workspace: Path) -> List[Dict[str, Any]]:
    """读取工作区任务清单 (纯只读, 文件缺失/损坏返回空)。"""
    from ..tools.todo_tool import load_disk_todos
    return load_disk_todos(workspace)


def _todo_path(workspace: Path) -> Path:
    from ..tools.todo_tool import todo_file_path
    return todo_file_path(workspace)


def cmd_todo(args: Any) -> int:
    """持久化任务清单只读查看 (第 112 个独特功能, 纯只读)。"""
    sub = getattr(args, "todo_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    path = _todo_path(workspace)
    todos = _load(workspace)

    if sub == "list":
        if json_mode:
            print(json.dumps({
                "workspace": str(workspace),
                "todo_file": str(path),
                "initialized": path.is_file(),
                "total": len(todos),
                "by_status": _by_status(todos),
                "progress": _progress(todos),
                "items": todos,
            }, ensure_ascii=False, indent=2))
            return 0
        if not path.is_file():
            console.print("[dim]工作区尚未初始化任务清单 (无 .tuan/todo.json; "
                          "Agent 用 todo_write 列出步骤后自动建立)[/dim]")
            return 0
        if not todos:
            console.print(f"[dim]任务清单文件存在但为空: {path}[/dim]")
            return 0
        done, total, pct = _progress(todos)
        console.print(f"[bold]=== 任务清单 · {workspace} ===[/bold]")
        console.print(f"  {path}")
        console.print(f"  进度: {done}/{total} 完成 ({pct}%)\n")
        for i, t in enumerate(todos, 1):
            status = str(t.get("status", "pending"))
            icon = _ICONS.get(status, "☐")
            label = _LABELS.get(status, status)
            console.print(f"  {icon} {i}. {t.get('content', '')}  [dim]({label})[/dim]")
        return 0

    elif sub == "show":
        raw = getattr(args, "index", None)
        try:
            idx = int(str(raw))
        except (TypeError, ValueError):
            console.print("[red]缺少序号: tuan todo show <序号>[/red]")
            return 1
        if not path.is_file():
            console.print("[dim]工作区尚未初始化任务清单[/dim]")
            return 0
        if idx < 1 or idx > len(todos):
            console.print(f"[red]序号越界: {idx} (清单共 {len(todos)} 项)[/red]")
            return 1
        item = todos[idx - 1]
        if json_mode:
            print(json.dumps({"index": idx, "workspace": str(workspace),
                              "todo_file": str(path), "item": item},
                             ensure_ascii=False, indent=2))
            return 0
        status = str(item.get("status", "pending"))
        console.print(f"[bold]{idx}. {item.get('content', '')}[/bold]")
        console.print(f"  状态: {_ICONS.get(status, '☐')} {_LABELS.get(status, status)}")
        for k, v in item.items():
            if k in ("content", "status"):
                continue
            console.print(f"  {k}: {v}")
        return 0

    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: list / show")
        return 1


def _by_status(todos: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t in todos:
        s = str(t.get("status", "pending"))
        out[s] = out.get(s, 0) + 1
    return out


def _progress(todos: List[Dict[str, Any]]) -> tuple:
    total = len(todos)
    done = sum(1 for t in todos if t.get("status") == "completed")
    pct = round(done * 100 / total) if total else 0
    return done, total, pct


_register_command("cmd_todo", ".cmd_todo")
