"""qxt chat handoff <session_id> —— CLI 层面交接指定会话。

读旧会话 jsonl, 生成交接摘要, 开新会话 ID, 旧会话标记 archived, 打印交接报告。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List

from ..config import home_dir
from ..core.chat_handoff import ChatHandoff
from ._ui_singleton import ui


def _load_messages_from_session(session_file: Path) -> List[dict]:
    """从会话 jsonl 重建 messages (用于启发式摘要)。"""
    out: List[dict] = []
    with open(session_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") in ("user", "assistant") and "message" in rec:
                out.append(rec["message"])
    return out


def cmd_chat_handoff(args) -> int:
    sid = getattr(args, "session_id", "") or ""
    if not sid:
        ui.error("用法: qxt chat handoff <session_id>")
        return 1
    sessions_dir = home_dir() / "sessions"
    matches = sorted(sessions_dir.glob(f"{sid}*.jsonl"))
    if not matches:
        ui.error(f"未找到会话: {sid}")
        return 1
    session_file = matches[0]
    old_sid = session_file.stem

    workspace = getattr(args, "workspace", None) or os.getcwd()
    messages = _load_messages_from_session(session_file)

    handoff = ChatHandoff(workspace)
    report = handoff.handoff(old_sid, messages)

    ui.success("会话交接完成:")
    ui.info(f"  旧会话 (已归档): {report.old_session_id}")
    ui.info(f"  新会话 (继承项目上下文): {report.new_session_id}")
    ui.info("  交接摘要:")
    for line in report.summary.splitlines():
        ui.info("    " + line)
    ui.info(f"\n  恢复新会话: qxt session resume {report.new_session_id}")
    return 0
