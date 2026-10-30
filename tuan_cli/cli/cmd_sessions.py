"""`tuan sessions` —— 会话列表 / 删除 (C-4.4 / C-4.5)。

与既有 `tuan session` (单数, list/resume/delete/export/...) 的分工:
- `tuan sessions list`   精简列出最近 20 条 (面向快速查看);
- `tuan sessions rm <id>` 删除指定会话, `--all` 清空全部;
- 恢复会话仍走 `tuan session resume <id>` 或 `tuan --continue` / `tuan --resume <id>`。
"""

from __future__ import annotations

from typing import Any

from ..session.store import (
    list_recent,
    remove_session,
    resolve_session,
    session_age_str,
    session_title,
)
from ._ui_singleton import console


def cmd_sessions(args: Any) -> int:
    """`tuan sessions <list|rm>` CLI 入口。"""
    sub = getattr(args, "sessions_cmd", "list")

    if sub == "list":
        return _cmd_list()
    if sub == "rm":
        return _cmd_rm(args)
    console.print("用法: tuan sessions list | tuan sessions rm <会话ID|编号|latest> [--all]")
    return 1


def _cmd_list() -> int:
    """列出最近 20 条会话 (时间 / 标题 / ID)。"""
    files = list_recent(20)
    if not files:
        console.print("没有会话记录。先运行 `tuan` 开始一次对话即可生成。")
        return 0
    console.print("  最近会话 (最近 20 条):")
    console.print(f"  {'#':>2}  {'时间':<12}  {'标题':<36} 会话ID")
    for i, p in enumerate(files, 1):
        title = session_title(p)[:36]
        console.print(f"  {i:>2}  {session_age_str(p):<12}  {title:<36} {p.stem}")
    console.print("  恢复: tuan session resume <编号|会话ID>  或  tuan --resume <会话ID>")
    return 0


def _cmd_rm(args: Any) -> int:
    """删除会话: `rm <id>` 或 `--all`。"""
    if getattr(args, "all", False):
        n = remove_session("", all_sessions=True)
        console.print(f"已清空全部 {n} 条会话")
        return 0

    target = getattr(args, "target", None)
    if not target:
        console.print("用法: tuan sessions rm <会话ID|编号|latest>  或  tuan sessions rm --all")
        return 1

    path = resolve_session(target)
    if path is None:
        console.print(f"未找到会话: {target}")
        return 1

    if not getattr(args, "yes", False):
        try:
            ans = input(f"  确认删除会话 {path.stem} ({session_title(path)})? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans != "y":
            console.print("已取消")
            return 0

    n = remove_session(target)
    if n:
        console.print(f"已删除会话: {path.stem}")
        return 0
    console.print(f"删除失败: {path.stem}")
    return 1
