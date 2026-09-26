"""qxt rewind <session_id> —— CLI 层面回退指定会话 (离线, 不动运行中的会话)。

用法:
  qxt rewind <session_id> [--to N]   把会话 jsonl 截断到某个快照
  qxt rewind --list                  列出当前工作区的快照
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from ..core.rewind import RewindError, RewindManager, rewind_session_file
from ..memory.sessions import SessionStore
from ..config import home_dir
from ._ui_singleton import ui


def cmd_rewind(args) -> int:
    workspace = getattr(args, "workspace", None) or os.getcwd()
    sid = getattr(args, "session_id", "") or ""

    if getattr(args, "list", False) or not sid:
        mgr = RewindManager(workspace)
        snaps = mgr.list_snapshots()
        if not snaps:
            ui.info("(当前工作区没有可回退的快照)")
            return 0
        ui.info(f"快照 {len(snaps)} 个 (在 .qxt/snapshots/):")
        for s in snaps:
            ui.info(f"  [{s.index}] {datetime.fromtimestamp(s.ts).strftime('%Y-%m-%d %H:%M:%S')} "
                    f"· {s.reason} · {s.message_count} 条消息 · 会话 {s.session_id or '?'}")
        if not sid:
            return 0

    # 定位会话文件
    sessions_dir = home_dir() / "sessions"
    matches = sorted(sessions_dir.glob(f"{sid}*.jsonl"))
    if not matches:
        ui.error(f"未找到会话: {sid}")
        return 1
    session_file = matches[0]

    try:
        result = rewind_session_file(session_file, workspace, index=getattr(args, "to", None))
    except RewindError as exc:
        ui.error(str(exc))
        return 1

    ui.success(
        f"已回退会话 {result['session_id']}: 保留 {result['kept_events']} 条事件, "
        f"丢弃 {result['removed_events']} 条 (快照 "
        f"{datetime.fromtimestamp(result['snapshot_ts']).strftime('%H:%M:%S')})"
    )
    return 0
