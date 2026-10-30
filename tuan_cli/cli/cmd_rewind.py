"""tuan rewind —— 会话时间线回溯 (离线 CLI)。

`tuan rewind <session_id> [--to N] [--list]` 把指定会话的 jsonl 事件流
截断到某个快照 (`.tuan/snapshots/`), 用于离线回退:

    tuan rewind <session_id> --list     列出该工作区的快照
    tuan rewind <session_id>            回退到最新快照
    tuan rewind <session_id> --to 2     回退到序号 2 的快照

与 TUI 内 `/rewind` 共用 :mod:`tuan_cli.core.rewind` 的同一份实现;
本模块轻量, 不导入 app 链。
"""

from __future__ import annotations
from ..paths import default_workspace

import os
from pathlib import Path
from typing import Any

from ..config import home_dir
from ..ui.plain_console import console


def _resolve_session_file(sid: str) -> Path | None:
    """按 session_id (可前缀) 解析会话 jsonl 文件; 找不到返回 None。"""
    sessions_dir = Path(home_dir()) / "sessions"
    if not sessions_dir.exists():
        return None
    if sid:
        files = sorted(sessions_dir.glob(f"{sid}*.jsonl"))
        if files:
            return files[0]
        return None
    # 无 sid: 取最新的会话文件
    files = sorted(sessions_dir.glob("*.jsonl"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0] if files else None


def cmd_rewind(args: Any) -> int:
    """会话 Rewind: 把指定会话回退到之前的快照。"""
    from ..core.rewind import RewindError, RewindManager, rewind_session_file

    workspace = getattr(args, "workspace", None) or default_workspace()
    sid = getattr(args, "session_id", "") or ""

    # --list: 只读列出当前工作区的快照
    if getattr(args, "list", False):
        mgr = RewindManager(workspace)
        snaps = mgr.list_snapshots()
        if not snaps:
            console.print("(没有可回退的快照)")
            return 0
        console.print(f"快照 {len(snaps)} 个 (工作区: {workspace}):")
        for s in snaps:
            console.print(
                f"  [{s.index}] {s.ts:>12.1f}  {s.reason} · {s.message_count} 条消息"
            )
        console.print("回退: tuan rewind <session_id> [--to N]")
        return 0

    session_file = _resolve_session_file(sid)
    if session_file is None:
        console.print(f"[rewind] 未找到会话文件: {sid or '(空)'} "
                      f"(会话目录: {Path(home_dir()) / 'sessions'})")
        return 1

    try:
        result = rewind_session_file(
            session_file,
            workspace,
            index=getattr(args, "to", None),
        )
    except RewindError as exc:
        console.print(f"[rewind] {exc}")
        return 1
    console.print(
        f"已 Rewind 会话 {result['session_id']}: "
        f"保留 {result['kept_events']} 条事件, 移除 {result['removed_events']} 条 "
        f"(快照 {result['snapshot_ts']:.1f})"
    )
    return 0


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_rewind", ".cmd_rewind")
