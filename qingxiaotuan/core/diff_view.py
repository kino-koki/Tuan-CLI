"""REPL / 终端 diff 美化输出 (P2, 对标 Claude Code /diff)。

TUI 内联折叠 diff 块工程量较大 (需改 textual 布局), 本模块先在 **plain console /
REPL 模式** 提供:

- ``colorize_unified_diff(text)``: 给统一 diff 文本加 ANSI 颜色
  (新增行绿色 / 删除行红色 / 头信息灰色);
- ``summarize_diff(text)``: 返回 ``(+新增行, -删除行, 文件数)`` 摘要;
- ``render_edit_diff(old, new, filename)``: 对一段旧/新文本生成统一 diff 并上色;
- ``last_edit_diff(workspace)``: 从操作账本 (.qxt/ledger) 取最近一次文件编辑,
  返回 ``(文件名, 着色后 diff)``; 无编辑时返回 None。

TUI (textual) 内联可折叠 diff 块列为后续工作。
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Optional, Tuple

# ANSI 颜色 (与项目其他终端输出一致; Windows 10+ 终端与 rich 均支持)
_GREEN = "\033[32m"
_RED = "\033[31m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def colorize_unified_diff(text: str) -> str:
    """给统一 diff 文本按行着色: + 绿 / - 红 / @@ 与头信息灰。"""
    out = []
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            out.append(f"{_DIM}{line}{_RESET}")
        elif line.startswith("@@"):
            out.append(f"{_DIM}{line}{_RESET}")
        elif line.startswith("+"):
            out.append(f"{_GREEN}{line}{_RESET}")
        elif line.startswith("-"):
            out.append(f"{_RED}{line}{_RESET}")
        else:
            out.append(line)
    return "\n".join(out)


def summarize_diff(text: str) -> Tuple[int, int, int]:
    """返回 (新增行数, 删除行数, 涉及文件数)。"""
    added = sum(1 for l in text.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in text.splitlines() if l.startswith("-") and not l.startswith("---"))
    files = len({l[6:].split(" ")[0] for l in text.splitlines() if l.startswith("+++ ")})
    return added, removed, files


def render_edit_diff(old: str, new: str, filename: str = "file") -> str:
    """对旧/新文本生成统一 diff 并着色。无差异时返回空串。"""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = difflib.unified_diff(
        old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm=""
    )
    text = "\n".join(diff)
    if not text.strip():
        return ""
    return colorize_unified_diff(text)


# ------------------------------------------------------------------ 账本: 最近一次编辑

_LEDGER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def last_edit_diff(workspace: str | Path) -> Optional[Tuple[str, str]]:
    """从 .qxt/ledger 找最近一次 edit_file/write 记录, 返回 (文件名, 着色 diff)。

    账本格式由 core/ledger.py 定义; 这里容错解析, 读不到就返回 None。
    """
    ws = Path(workspace)
    ledger = ws / ".qxt" / "ledger"
    if not ledger.exists():
        return None
    try:
        # 账本可能是 jsonl 或目录; 优先取 jsonl
        cand = ledger if ledger.is_file() else (ledger / "events.jsonl")
        if not cand.exists():
            return None
        events = []
        for line in cand.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # 倒序找最近一次带 old/new 内容的编辑
        for ev in reversed(events):
            if ev.get("type") not in ("edit", "write", "edit_file"):
                continue
            path = ev.get("path") or ev.get("file") or ""
            old = ev.get("old")
            new = ev.get("new")
            if path and old is not None and new is not None:
                colored = render_edit_diff(old, new, Path(path).name)
                if colored:
                    return (str(path), colored)
    except OSError:
        return None
    return None


def format_no_diff() -> str:
    """无编辑时的提示文案。"""
    return "当前没有可展示的 diff (尚未发生文件编辑, 或工作区干净)。"
