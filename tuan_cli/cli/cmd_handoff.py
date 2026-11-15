"""tuan chat handoff —— Chat 层: 会话交接 (CLI)。

`tuan chat handoff <session_id>` 把指定会话交接: 生成摘要 -> 开新会话 ->
旧会话归档 -> 谱系落盘 ``.tuan/handoffs.json``:

    tuan chat handoff <session_id>    交接指定会话 (ID 可前缀)

与 TUI 内 `/handoff` 共用 :mod:`tuan_cli.core.chat_handoff` 的同一份实现;
本模块轻量, 不导入 app 链。
"""

from __future__ import annotations
from typing import Any

from ..paths import default_workspace

import os
import json
import sys
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


def cmd_chat_handoff(args: Any) -> int:
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

# 仅注册 cmd_handoff (历史可观测)。cmd_chat_handoff 归 cmd_chat_handoff.py,
# 本模块不抢注 —— 否则与 cmd_chat_handoff.py::_register_command 异路径同名
# 冲突 (parser._register_command 对异路径同名抛 AssertionError)。
_register_command("cmd_handoff", ".cmd_handoff")


def cmd_handoff(args: Any) -> int:
    """``tuan handoff`` 会话交接历史可观测 (只读): 清单/详情/配置。

    分片 ``subcommands/ledger_ops.register_ledger_ops`` 声明了 ``handoff``
    子命令面 (list/show/config), 但 handler 从未实现。本函数补齐该缺口,
    复用 :meth:`ChatHandoff.list_handoffs` 读取 ``.tuan/handoffs.json``。
    """
    import sys as _sys  # noqa: F401 (保留, 供 JSON 分支输出; 兼容旧调用方)
    from ..core.chat_handoff import ChatHandoff

    sub = getattr(args, "handoff_cmd", None) or "list"
    workspace = getattr(args, "workspace", None) or default_workspace()
    json_mode = bool(getattr(args, "json", False))
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))
    handoff = ChatHandoff(workspace, config)
    records = handoff.list_handoffs()

    if sub == "list":
        if json_mode:
            _sys.stdout.write(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print("\n[bold]=== 会话交接历史 ===[/bold]\n")
        if not records:
            console.print("  [dim]暂无交接记录 (执行 `tuan chat handoff <session_id>` 生成)[/dim]")
            return 0
        for i, rec in enumerate(records, 1):
            console.print(f"  [cyan]{i:>3}[/cyan] {rec.get('old_session_id', '?')}"
                          f"  →  {rec.get('new_session_id', '?')}")
            if rec.get("project_id"):
                console.print(f"        [dim]project={rec['project_id']}[/dim]")
            preview = str(rec.get("summary", ""))[:60]
            if preview:
                console.print(f"        [dim]{preview}{'…' if len(str(rec.get('summary', ''))) > 60 else ''}[/dim]")
        return 0

    if sub == "show":
        index = getattr(args, "index", None)
        try:
            idx = int(index) - 1 if index is not None else 0
        except (TypeError, ValueError):
            console.print("[red]用法: tuan handoff show <序号>[/red]")
            return 1
        if not (0 <= idx < len(records)):
            console.print(f"[red]交接序号 {index} 超出范围 (共 {len(records)} 条)[/red]")
            return 1
        rec = records[idx]
        if json_mode:
            _sys.stdout.write(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print(f"\n[bold]=== 交接 #{idx + 1} ===[/bold]\n")
        console.print(f"  旧会话: [cyan]{rec.get('old_session_id', '?')}[/cyan]")
        console.print(f"  新会话: [cyan]{rec.get('new_session_id', '?')}[/cyan]")
        console.print(f"  归档:   {rec.get('archived', True)}")
        if rec.get("project_id"):
            console.print(f"  项目:   {rec['project_id']}")
        console.print(f"\n[dim]交接摘要:[/dim]")
        for line in str(rec.get("summary", "")).splitlines():
            console.print(f"    {line}")
        return 0

    if sub == "config":
        threshold = config.get("chat.auto_handoff_threshold", 0.8)
        enabled = config.get("chat.auto_handoff_enabled", True)
        cfg = {
            "enabled": bool(enabled),
            "threshold": float(threshold),
            "data_file": str(Path(home_dir()) / "handoffs.json"),
        }
        if json_mode:
            _sys.stdout.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print("\n[bold]=== 会话交接配置 ===[/bold]\n")
        console.print(f"  [cyan]enabled[/cyan]  {cfg['enabled']}")
        console.print(f"  [cyan]threshold[/cyan] {cfg['threshold']}")
        console.print(f"  [cyan]data_file[/cyan] {cfg['data_file']}")
        return 0

    console.print(f"[red]未知子命令:[/red] {sub} (可用: list / show / config)")
    return 1
