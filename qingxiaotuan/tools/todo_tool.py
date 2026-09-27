"""TodoWrite 内置工具 —— 对标 Claude Code 的 TodoWrite。

在 session_tools 内存版 todo_write/todo_read 之上补两层能力:
- **持久化**: 任务清单落盘到 ``<workspace>/.qxt/todo.json``, 新会话/新 Agent
  进入同一工作区时 ``todo_list`` 可恢复上次任务清单 (不丢失进度);
- **todo_list**: 显式列出当前任务 (pending/in_progress/completed 三态 + 进度)。

todo_write 的校验文案与 session_tools 完全一致 (全量覆盖语义, 同时只能有一项
in_progress), 本插件在注册顺序上排在 SessionToolsPlugin 之后, 以"升级"而非
"改坏"的方式覆盖同名工具。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

TODO_STATUSES = ("pending", "in_progress", "completed")
TODO_FILE_NAME = Path(".qxt") / "todo.json"


# ------------------------------------------------------------------ 持久化层


def todo_file_path(workspace: Path) -> Path:
    """任务清单持久化路径: <workspace>/.qxt/todo.json。"""
    return Path(workspace) / TODO_FILE_NAME


def load_disk_todos(workspace: Path) -> List[Dict[str, Any]]:
    """从工作区加载任务清单; 文件缺失/损坏时返回空列表 (容错, 不抛错)。"""
    path = todo_file_path(workspace)
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [t for t in data if isinstance(t, dict) and t.get("content")]
    except Exception:  # noqa: BLE001 - 损坏的清单不应阻断 Agent
        pass
    return []


def save_disk_todos(workspace: Path, todos: List[Dict[str, Any]]) -> Path:
    """把任务清单写入工作区 .qxt/todo.json; 返回写入路径。"""
    path = todo_file_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(todos), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------------------ 校验 (与 session_tools 同语义)


def _validate_todos(todos: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """返回 (cleaned, error_msg)。cleaned 与 error_msg 互斥。"""
    if not isinstance(todos, list) or not todos:
        return None, "[错误] todo_write 需要非空的 todos 数组 (全量覆盖语义)"
    cleaned: List[Dict[str, Any]] = []
    for i, item in enumerate(todos, 1):
        if not isinstance(item, dict):
            return None, f"[错误] 第 {i} 项不是对象: {item!r}"
        content = str(item.get("content", "")).strip()
        status = str(item.get("status", "pending")).strip().lower()
        if not content:
            return None, f"[错误] 第 {i} 项缺少 content"
        if status not in TODO_STATUSES:
            return None, (
                f"[错误] 第 {i} 项 status 非法: {status} "
                f"(允许: {'/'.join(TODO_STATUSES)})"
            )
        cleaned.append({"content": content, "status": status})
    if sum(1 for t in cleaned if t["status"] == "in_progress") > 1:
        return None, "[错误] 同时只能有一项 in_progress (请先完成当前项)"
    return cleaned, None


# ------------------------------------------------------------------ handlers


def _todo_write_handler(ctx: ToolContext, todos: Any = None, **_kwargs) -> str:
    cleaned, err = _validate_todos(todos)
    if err is not None:
        return err
    assert cleaned is not None
    ctx.todos = cleaned
    # 持久化到工作区 (失败不阻断: 内存态已生效)
    try:
        save_disk_todos(Path(ctx.workspace or "."), cleaned)
    except Exception as exc:  # noqa: BLE001
        return f"任务清单已更新 ({sum(1 for t in cleaned if t['status'] == 'completed')}/{len(cleaned)} 完成)。(警告: 持久化失败: {exc})"
    try:
        ctx.kernel.emit("todos.updated", {"todos": list(cleaned)})
    except Exception:  # noqa: BLE001
        pass
    done = sum(1 for t in cleaned if t["status"] == "completed")
    return f"任务清单已更新 ({done}/{len(cleaned)} 完成)。"


def _todo_list_handler(ctx: ToolContext, **_kwargs) -> str:
    todos: List[Dict[str, Any]] = list(getattr(ctx, "todos", None) or [])
    if not todos:
        # 内存态为空时从工作区恢复 (跨会话/新 Agent 场景)
        todos = load_disk_todos(Path(getattr(ctx, "workspace", ".") or "."))
        if todos:
            ctx.todos = todos
    if not todos:
        return "(任务清单为空) 用 todo_write 先列出本任务的步骤。"
    icons = {"pending": "☐", "in_progress": "◔", "completed": "☑"}
    lines = [
        f"{icons.get(t['status'], '☐')} [{t['status']}] {t['content']}" for t in todos
    ]
    done = sum(1 for t in todos if t["status"] == "completed")
    lines.append(f"进度: {done}/{len(todos)}")
    return "\n".join(lines)


# ------------------------------------------------------------------ 工具定义


def build_todo_write_tool() -> Tool:
    return Tool(
        name="todo_write",
        description=(
            "写入/更新会话任务清单 (全量覆盖, 并持久化到工作区 .qxt/todo.json)。\n"
            "开始一个多步骤任务前先用它列出步骤, 每完成一步就更新对应项的状态,\n"
            "让用户随时看到进展。同时只能有一项 in_progress。\n"
            "status 取值: pending (待办) / in_progress (进行中) / completed (已完成)。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "完整清单 (覆盖旧值, 同时写入工作区)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": string_prop("步骤内容"),
                            "status": {
                                "type": "string",
                                "enum": list(TODO_STATUSES),
                                "description": "该步骤当前状态",
                            },
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        },
        handler=_todo_write_handler,
        dangerous=False,
        group="session",
        read_only=True,
    )


def build_todo_list_tool() -> Tool:
    return Tool(
        name="todo_list",
        description=(
            "列出当前任务清单 (内存态优先, 为空时从工作区 .qxt/todo.json 恢复)。\n"
            "显示每项的状态图标与整体完成进度。"
        ),
        parameters={"type": "object", "properties": {}},
        handler=_todo_list_handler,
        dangerous=False,
        group="session",
        read_only=True,
    )


class TodoToolPlugin(Plugin):
    """TodoWrite 工具插件: todo_write (持久化) + todo_list。"""

    name = "tools.todo"

    def activate(self, kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(build_todo_write_tool())
        registry.register(build_todo_list_tool())
