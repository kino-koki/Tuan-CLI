"""chat handoff 命令 —— `tuan chat handoff <session_id>`。

真正的交接实现一直存在 (``core/chat_handoff.py::ChatHandoff.handoff``:
生成摘要 → 新会话 ID → 落 ``.tuan/handoffs.json`` 谱系), 但 CLI 这一层
**从来没有对应函数**: ``cli/subcommands/session_workspace.py`` 把 ``chat``
的 func 设成 ``"cmd_chat_handoff"``, 全仓却搜不到这个符号 —— 于是
``tuan chat handoff`` 一走到分发就 ``AttributeError``, 子命令名存在、
功能不存在。本模块只做 CLI 薄封装, 不复制交接逻辑。

如实标注边界: 摘要走 ``build_summary`` 的启发式 (无 LLM 时不编造),
新会话 ID 只是登记, 不会自动打开 REPL。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._ui_singleton import console
from .parser import _register_command


def cmd_chat_handoff(args: Any) -> int:
    """把指定旧会话交接成一条新会话 (摘要 + 谱系记录)。"""
    from ..core.chat_handoff import ChatHandoff
    from ..memory.sessions import SessionStore
    from ..session.store import resolve_session

    target = str(getattr(args, "session_id", "") or "").strip()
    path = resolve_session(target)
    if path is None:
        console.print(f"[red]未找到会话: {target or '(空)'}[/red]")
        return 1
    try:
        messages = SessionStore.load_messages(path)
    except OSError as exc:
        console.print(f"[red]读取会话失败: {exc}[/red]")
        return 1
    if not messages:
        console.print(f"[yellow]会话 {path.stem} 没有可交接的消息, 已中止[/yellow]")
        return 1

    handoff = ChatHandoff(Path.cwd())
    report = handoff.handoff(old_session_id=path.stem, messages=messages)
    console.print(
        f"[bold]会话交接完成[/bold]\n"
        f"  旧会话: {report.old_session_id}\n"
        f"  新会话: {report.new_session_id} (已登记, 未自动开始)\n"
        f"  谱系记录: {handoff.tuan_dir / 'handoffs.json'}")
    if report.summary:
        console.print("\n[dim]--- 交接摘要 ---[/dim]\n" + report.summary)
    return 0


_register_command("cmd_chat_handoff", ".cmd_chat_handoff")
