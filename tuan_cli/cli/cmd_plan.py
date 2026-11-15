"""plan 命令 —— 实施计划存档只读体检 (第 120 个独特功能)。

exit_plan_mode 工具 (tools/session_tools.py `_archive_plan`) 把「经确认的
实施计划」原子落盘到 ``<workspace>/.tuan/plan.md`` (含 UTC 存档时间与来源头),
供后续会话/审计恢复。但此前该存档**只写不读**: 唯一的写路径在 Plan 模式
退出时触发, 没有任何命令能回看它 —— 跨会话恢复、审计计划差异、确认计划
是否真的落盘过, 都做不到。对比 Claude Code: 它的 Plan Mode 计划只活在
对话里, 退出即丢, 没有"已确认实施计划"的持久化回看面。本命令补上这个
只读体检面 (纯只读: 直接读 plan.md, 不调 _archive_plan 写路径, 不 mkdir)。

  tuan plan show [--workspace DIR] [--json]      # 查看当前存档 (含时间/来源/行数)
  tuan plan diff [--workspace DIR] [--file X]    # 与指定文件/字符串比对差异摘要
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env = os.environ.get("TUAN_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _plan_path(workspace: Path) -> Path:
    return workspace / ".tuan" / "plan.md"


def _parse_header(text: str) -> Dict[str, Any]:
    """解析存档头的 UTC 时间与来源, 返回 (meta, body_start)。"""
    meta: Dict[str, Any] = {"saved_at": None, "source": None}
    m = re.search(r"- 存档时间 \(UTC\):\s*(.+)", text)
    if m:
        meta["saved_at"] = m.group(1).strip()
    m = re.search(r"- 来源:\s*(.+)", text)
    if m:
        meta["source"] = m.group(1).strip()
    return meta


def _diff_stats(a: str, b: str) -> Dict[str, int]:
    """简化差异统计: 行级 added/removed (LCS 长度)。"""
    la = a.splitlines()
    lb = b.splitlines()
    n, m = len(la), len(lb)
    # 用集合行计数做快速近似, 避免 O(n*m) DP 在超大文件上爆栈
    from collections import Counter
    ca, cb = Counter(la), Counter(lb)
    added = sum(max(0, v) for v in (cb - ca).values())
    removed = sum(max(0, v) for v in (ca - cb).values())
    return {"added": added, "removed": removed, "common": n - removed, "a_lines": n, "b_lines": m}


def cmd_plan(args: Any) -> int:
    """实施计划存档只读体检 (第 120 个独特功能, 纯只读)。"""
    sub = getattr(args, "plan_cmd", None) or "show"
    json_mode = bool(getattr(args, "json", False))
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    ppath = _plan_path(workspace)

    if sub == "show":
        if not ppath.is_file():
            if json_mode:
                print('{"initialized": false}')
                return 0
            console.print("[dim]尚无已确认的实施计划存档 ("
                          "退出 Plan 模式并确认后自动建立: "
                          f"{ppath})[/dim]")
            return 0
        try:
            text = ppath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            console.print(f"[red]读取存档失败: {exc}[/red]")
            return 1
        meta = _parse_header(text)
        if json_mode:
            import json as _json
            print(_json.dumps({
                "initialized": True,
                "saved_at": meta["saved_at"],
                "source": meta["source"],
                "bytes": len(text.encode("utf-8")),
                "lines": text.count("\n"),
            }, ensure_ascii=False))
            return 0
        console.print(f"[bold]已确认实施计划 · {ppath}[/bold]\n")
        if meta["saved_at"]:
            console.print(f"  存档时间 (UTC): {meta['saved_at']}")
        if meta["source"]:
            console.print(f"  来源: {meta['source']}")
        console.print(f"  {len(text.encode('utf-8'))} 字节 · {text.count(chr(10))} 行\n")
        console.print("[dim]--- 内容 ---[/dim]")
        console.print(text)
        return 0

    elif sub == "diff":
        if not ppath.is_file():
            console.print("[red]尚无存档可比对: 先退出 Plan 模式确认生成[/red]")
            return 1
        try:
            current = ppath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            console.print(f"[red]读取存档失败: {exc}[/red]")
            return 1
        other_file = getattr(args, "file", None)
        if other_file:
            try:
                other = Path(other_file).expanduser().read_text(
                    encoding="utf-8", errors="replace")
            except OSError as exc:
                console.print(f"[red]读取比对文件失败: {exc}[/red]")
                return 1
        else:
            other = getattr(args, "text", "") or ""
            if not other.strip():
                console.print("[red]需要 --file <路径> 或 --text <字符串> 作为比对对象[/red]")
                return 1
        stats = _diff_stats(current, other)
        if json_mode:
            print('{"a_lines": %d, "b_lines": %d, "added": %d, '
                  '"removed": %d, "common": %d}'
                  % (stats["a_lines"], stats["b_lines"], stats["added"],
                     stats["removed"], stats["common"]))
            return 0
        console.print(f"[bold]计划差异 · {ppath}[/bold]\n")
        console.print(f"  当前存档: {stats['a_lines']} 行")
        console.print(f"  比对对象: {stats['b_lines']} 行")
        console.print(f"  新增行: {stats['added']}  删除行: {stats['removed']}  "
                      f"  公共行: {stats['common']}")
        if stats["added"] == 0 and stats["removed"] == 0:
            console.print("\n  [green]两者内容一致 (行级)[/green]")
        else:
            console.print("\n  [yellow]存在差异[/yellow]")
        return 0

    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: show / diff")
        return 1


_register_command("cmd_plan", ".cmd_plan")
