"""ledger 命令 —— 操作账本可观测性 (第 96 个独特功能)。

暴露 :mod:`tuan_cli.core.ledger` 的持久化变更凭证账本 (只读查询面):
- **账本清单**: 每条变更凭证的 id/时间/工具/类型/摘要/目标文件;
- **影响半径统计**: 操作数 / 触及文件数 / 文件清单;
- **检查点标记**: 当前变更记录数 (配合 undo_since 使用, 只读)。

差异化价值: Claude Code 只有 git 薄封装撤销, 不记录 Agent 工具级变更,
更没有「执行前快照 + 异常自动回滚」的事务账本。本命令把 MutationLedger
落到 .tuan/ledger/ledger.jsonl 的凭证历史开放为可查询 (纯只读, 不写盘)。

  tuan ledger [--workspace P] [--json]     # 凭证清单 (默认)
  tuan ledger stats [--workspace P]        # 影响半径统计
  tuan ledger mark [--workspace P]         # 当前变更计数 (检查点标记)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_ws(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd()


def _get_ledger(raw_ws: Optional[str]) -> Any:
    from ..core.ledger import MutationLedger

    ledger = MutationLedger(str(_resolve_ws(raw_ws)), config=None)
    ledger.load_journal()  # 从磁盘重建内存账本 (只读装载, 不产生写副作用)
    return ledger


def _fmt_time(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "-"


def _rec_dict(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": rec.get("id", ""),
        "ts": rec.get("ts", 0),
        "time": _fmt_time(float(rec.get("ts", 0))),
        "tool": rec.get("tool", ""),
        "kind": rec.get("kind", "mutation"),
        "summary": rec.get("summary", ""),
        "targets": rec.get("targets", []),
    }


def cmd_ledger(args: Any) -> int:
    """ledger 主入口: 操作账本可观测 (纯只读查询)。"""
    sub = getattr(args, "ledger_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))
    ws_raw = getattr(args, "workspace", None)
    ledger = _get_ledger(ws_raw)
    ws = _resolve_ws(ws_raw)

    if sub == "stats":
        stats = ledger.stats()
        if json_mode:
            print(json.dumps({
                "workspace": str(ws),
                "enabled": ledger.enabled,
                **stats,
            }, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]操作账本影响半径 · {ws.name}[/bold]")
        console.print(f"[dim]启用={ledger.enabled} 上限={ledger.max_records} "
                      f"journal={ledger.journal_path.name}[/dim]")
        console.print(f"  变更凭证: [cyan]{stats['records']}[/cyan] 条")
        console.print(f"  触及文件: [cyan]{stats['files_touched']}[/cyan] 个")
        if stats["files"]:
            console.print("  文件:")
            for f in stats["files"]:
                console.print(f"    [dim]{f}[/dim]")
        return 0

    if sub == "mark":
        n = ledger.mark()
        if json_mode:
            print(json.dumps({
                "workspace": str(ws),
                "enabled": ledger.enabled,
                "mark": n,
            }, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]检查点标记 · {ws.name}[/bold]")
        console.print(f"  当前变更记录数: [cyan]{n}[/cyan] "
                      "(配合 undo_since 只回滚此后变更)")
        return 0

    # 默认 list
    history = ledger.history()
    if json_mode:
        print(json.dumps({
            "workspace": str(ws),
            "enabled": ledger.enabled,
            "count": len(history),
            "records": [_rec_dict(r) for r in history],
        }, ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]操作账本凭证 · {ws.name}[/bold]")
    console.print(f"[dim]启用={ledger.enabled} · "
                  f"journal={ledger.journal_path}[/dim]\n")
    if not history:
        console.print("[green]✓ 无变更凭证[/green] "
                      "([dim]<workspace>/.tuan/ledger/ledger.jsonl[/dim])")
        return 0
    console.print(f"共 {len(history)} 条凭证:\n")
    for r in history:
        rd = _rec_dict(r)
        targets = ", ".join(rd["targets"]) if rd["targets"] else "-"
        console.print(f"  [yellow]{rd['id']}[/yellow] "
                      f"[dim]{rd['time']}[/dim] "
                      f"[cyan]{rd['tool']}[/cyan] "
                      f"[magenta]{rd['kind']}[/magenta] "
                      f"[dim]{targets}[/dim]")
        if rd["summary"]:
            console.print(f"        [dim]↳ {rd['summary']}[/dim]")
    console.print("\n[dim]统计: tuan ledger stats · 检查点: tuan ledger mark[/dim]")
    return 0


_register_command("cmd_ledger", ".cmd_ledger")
