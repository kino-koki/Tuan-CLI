"""web audit 命令 —— Web 工作台持久化状态只读体检 (第 115 个独特功能)。

web/server.py 的 WebServer 把 Web 工作台状态落盘到:
- ``<workspace>/.tuan/web_sessions.json``: {sid: {id,title,created,messages[]}} 会话快照
  (重启不丢, 供 Web UI 恢复历史会话)
- ``<workspace>/.tuan/web_settings.json``: Web UI 用户偏好 (主题/字号/预算告警阈值等)

但这两份状态此前**只能启动 Web 服务**再经 ``/api/sessions``、``/api/settings``
查看 —— 外部脚本/CI 无法脱离运行中的服务看到: Web 工作台留下了哪些会话、
各会话多少条消息、创建时间、占多少磁盘, 以及用户偏好里配了什么。本命令
补上独立只读体检面 (纯只读: glob + json.load, 不构造 WebServer —— 其 __init__
会写盘, 避免任何副作用)。

差异化价值: Claude Code 的 Web/UI 会话状态同样只能运行时查看; 本命令把
Web 工作台的持久化状态变成可被任何进程审计的持久事实。

  tuan web audit [--workspace DIR] [--json]        # 会话+设置体检
  tuan web audit sessions [--workspace DIR] [--json]  # 只列会话
  tuan web audit settings [--workspace DIR] [--json]  # 只看用户偏好
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env = os.environ.get("TUAN_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """读取 JSON 文件 (纯只读); 缺失/损坏返回 None。"""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _msg_count(s: Dict[str, Any]) -> int:
    msgs = s.get("messages")
    if isinstance(msgs, list):
        return len(msgs)
    if isinstance(msgs, dict):
        return len(msgs)
    return 0


def _session_row(sid: str, s: Dict[str, Any]) -> Dict[str, Any]:
    created = s.get("created", "-")
    return {
        "id": sid,
        "title": str(s.get("title", sid))[:60],
        "created": created,
        "messages": _msg_count(s),
    }


def cmd_web_audit(args: Any) -> int:
    """Web 工作台持久化状态只读体检 (第 115 个独特功能, 纯只读)。"""
    sub = getattr(args, "web_audit_cmd", None) or "all"
    json_mode = bool(getattr(args, "json", False))
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    sessions_path = workspace / ".tuan" / "web_sessions.json"
    settings_path = workspace / ".tuan" / "web_settings.json"

    sessions_data = _read_json(sessions_path)
    settings_data = _read_json(settings_path)

    sessions: List[Dict[str, Any]] = []
    if sessions_data:
        for sid, s in sessions_data.items():
            if isinstance(s, dict):
                sessions.append(_session_row(sid, s))
    sessions.sort(key=lambda r: str(r["created"]), reverse=True)

    payload = {
        "workspace": str(workspace),
        "sessions_file": str(sessions_path),
        "settings_file": str(settings_path),
        "sessions_initialized": sessions_path.is_file(),
        "settings_initialized": settings_path.is_file(),
        "session_count": len(sessions),
        "total_messages": sum(r["messages"] for r in sessions),
        "sessions": sessions,
        "settings": settings_data or {},
    }

    if sub == "sessions":
        if json_mode:
            print(json.dumps({**payload, "settings": None}, ensure_ascii=False, indent=2))
            return 0
        _print_sessions(payload)
        return 0

    if sub == "settings":
        if json_mode:
            print(json.dumps({"workspace": str(workspace),
                              "settings_file": str(settings_path),
                              "initialized": settings_path.is_file(),
                              "settings": settings_data or {}},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]=== Web 工作台用户偏好 · {settings_path} ===[/bold]\n")
        if not settings_data:
            console.print("  [dim](未初始化或为空)[/dim]")
            return 0
        for k, v in sorted(settings_data.items()):
            console.print(f"  [bold]{k}[/bold] = {v}")
        return 0

    # 默认 all
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]=== Web 工作台持久化状态 · {workspace} ===[/bold]\n")
    if not sessions_path.is_file() and not settings_path.is_file():
        console.print("  [dim]Web 工作台尚未落盘任何状态 (启动 tuan web 并交互后自动建立)[/dim]")
        return 0
    _print_sessions(payload)
    console.print()
    console.print(f"[bold]用户偏好 · {settings_path}[/bold]")
    if settings_data:
        for k, v in sorted(settings_data.items()):
            console.print(f"  {k} = {v}")
    else:
        console.print("  [dim](未初始化或为空)[/dim]")
    return 0


def _print_sessions(payload: Dict[str, Any]) -> None:
    console.print(f"[bold]Web 会话 · {payload['sessions_file']}[/bold]")
    if not payload["sessions_initialized"]:
        console.print("  [dim](未初始化; 启动 tuan web 交互后自动建立)[/dim]")
        return
    if not payload["sessions"]:
        console.print("  [dim](空)[/dim]")
        return
    console.print(f"  {payload['session_count']} 个会话 · 共 {payload['total_messages']} 条消息\n")
    for r in payload["sessions"]:
        console.print(f"  [bold]{r['title']}[/bold]")
        console.print(f"      {r['id']} · {r['messages']} 条消息 · {r['created']}")


_register_command("cmd_web_audit", ".cmd_web_audit")
