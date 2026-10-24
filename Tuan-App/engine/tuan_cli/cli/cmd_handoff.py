"""tuan chat handoff —— Chat 层: 会话交接 (CLI)。

`tuan chat handoff <session_id>` 把指定会话交接: 生成摘要 -> 开新会话 ->
旧会话归档 -> 谱系落盘 ``.tuan/handoffs.json``:

    tuan chat handoff <session_id>    交接指定会话 (ID 可前缀)

与 TUI 内 `/handoff` 共用 :mod:`tuan_cli.core.chat_handoff` 的同一份实现;
本模块轻量, 不导入 app 链。
"""

from __future__ import annotations
from ..paths import default_workspace

import os
from pathlib import Path

from ..config import Config, home_dir
from ..ui.plain_console import console


def _resolve_session_file(sid: str) -> Path | None:
    """按 session_id (可前缀) 解析会话 jsonl 文件; 找不到返回 None。"""
    sessions_dir = Path(home_dir()) / "sessions"
    if not sessions_dir.exists():
        return None
    files = sorted(sessions_dir.glob(f"{sid}*.jsonl"))
    return files[0] if files else None


def cmd_chat_handoff(args) -> int:
    """Chat 层: 交接指定会话 (生成摘要 -> 开新会话)。"""
    from ..core.chat_handoff import ChatHandoff
    from ..core.project_layer import ProjectLayer
    from ..memory.sessions import SessionStore

    sid = getattr(args, "session_id", "") or ""
    if not sid:
        console.print("用法: tuan chat handoff <session_id>")
        return 1
    session_file = _resolve_session_file(sid)
    if session_file is None:
        console.print(f"[handoff] 未找到会话: {sid} "
                      f"(会话目录: {Path(home_dir()) / 'sessions'})")
        return 1

    messages = SessionStore.load_messages(session_file)
    if not messages:
        console.print(f"[handoff] 会话 {session_file.stem} 没有可交接的消息")
        return 1

    workspace = getattr(args, "workspace", None) or default_workspace()
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))
    handoff = ChatHandoff(workspace, config)

    pid = ""
    try:
        pid = ProjectLayer(workspace).info().project_id
    except Exception:  # noqa: BLE001 - 项目层未初始化时不阻塞交接
        pid = ""

    report = handoff.handoff(session_file.stem, messages, project_id=pid)
    console.print("会话交接完成:")
    console.print(f"  旧会话 (已归档): {report.old_session_id}")
    console.print(f"  新会话 ID:       {report.new_session_id}")
    console.print("  交接摘要:")
    for line in report.summary.splitlines():
        console.print("    " + line)
    console.print(f"  提示: 退出后 `tuan session resume {report.new_session_id}` "
                  "即可带着摘要继续。")
    return 0


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_chat_handoff", ".cmd_handoff")
