"""checkpoint 命令 —— 自动检查点可观测性 (第 93 个独特功能)。

暴露 :mod:`tuan_cli.core.checkpoint_store` 的持久化检查点索引:
- **检查点清单**: 从 <workspace>/.tuan/checkpoints/checkpoints.json 装载,
  含 id/时间/ledger_marker/变更文件/摘要 (新的在前);
- **恢复预览**: 单个检查点含哪些文件变更、回滚到账本哪一位置、对话截到哪;
- **TTL/上限**: 当前 TTL 秒数、最大数量、启用/自动标记状态;
- **清理**: 触发过期检查点清理 (只读, 不执行代码回滚)。

差异化价值: Claude Code 的 ``/rewind`` 只在会话内交互式可用, 用户无法
独立查询「当前工作区有哪些检查点、各自对应哪些文件变更、摘要是什么」。
本命令把 CheckpointStore 的持久化索引开放为可查询 (纯只读)。

  tuan checkpoint [--workspace P] [--json]       # 检查点清单
  tuan checkpoint show <id> [--workspace P]      # 单个检查点详情
  tuan checkpoint prune [--workspace P]          # 清理过期检查点
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd()


def _get_store(raw_ws: Optional[str]) -> Any:
    from ..core.checkpoint_store import CheckpointStore

    ws = _resolve_workspace(raw_ws)
    return CheckpointStore(str(ws))


def _fmt_time(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (TypeError, ValueError, OSError):
        return "-"


def _cp_dict(cp: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": cp.get("id"),
        "created_at": cp.get("created_at"),
        "time": _fmt_time(float(cp.get("created_at", 0))),
        "ledger_marker": cp.get("ledger_marker"),
        "files": cp.get("files", []),
        "summary": cp.get("summary", ""),
        "n_files": len(cp.get("files", [])),
    }


def cmd_checkpoint(args: Any) -> int:
    """checkpoint 主入口: 自动检查点可观测 (纯只读查询 + 过期清理)。"""
    sub = getattr(args, "cp_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))
    ws_raw = getattr(args, "workspace", None)

    try:
        store = _get_store(ws_raw)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]检查点存储初始化失败: {exc}[/red]")
        return 1

    ws = _resolve_workspace(ws_raw)

    if sub == "prune":
        before = len(store.list())
        store._prune_expired()
        after = len(store.list())
        removed = max(0, before - after)
        if json_mode:
            print(json.dumps({
                "workspace": str(ws),
                "before": before, "after": after, "removed": removed,
            }, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[green]✓ 已清理过期检查点[/green] "
                      f"({removed} 个移除, 剩余 {after} 个)")
        return 0

    if sub == "show":
        cp_id = str(getattr(args, "cp_id", "") or "").strip()
        if not cp_id:
            console.print("[red]缺少检查点 ID[/red] (用法: tuan checkpoint show <id>)")
            return 1
        cp = store.find(cp_id)
        if cp is None:
            console.print(f"[red]未找到检查点: {cp_id}[/red]")
            return 1
        if json_mode:
            print(json.dumps(_cp_dict(cp), ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]检查点 {cp.get('id')}[/bold]")
        console.print(f"  时间: {_fmt_time(float(cp.get('created_at', 0)))}")
        console.print(f"  账本位置: [cyan]{cp.get('ledger_marker')}[/cyan]")
        files = cp.get("files", [])
        if files:
            console.print(f"  变更文件 ({len(files)}):")
            for f in files:
                console.print(f"    [dim]{f}[/dim]")
        else:
            console.print("  变更文件: (无)")
        if cp.get("summary"):
            console.print(f"  摘要: {cp.get('summary')}")
        return 0

    # 默认 list
    cps: List[Dict[str, Any]] = store.list()
    if json_mode:
        print(json.dumps({
            "workspace": str(ws),
            "enabled": store.enabled,
            "auto": store.auto,
            "ttl_seconds": store.ttl,
            "max_checkpoints": store.max_checkpoints,
            "count": len(cps),
            "checkpoints": [_cp_dict(c) for c in cps],
        }, ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]自动检查点 · {ws}[/bold]")
    console.print(f"[dim]启用={store.enabled} 自动={store.auto} "
                  f"TTL={store.ttl}s 上限={store.max_checkpoints}[/dim]\n")
    if not cps:
        console.print("[green]✓ 无检查点[/green] "
                      "([dim]<workspace>/.tuan/checkpoints/[/dim])")
        return 0
    console.print(f"共 {len(cps)} 个检查点 (新的在前):\n")
    for cp in cps:
        files = cp.get("files", [])
        n_files = len(files) if isinstance(files, list) else 0
        console.print(f"  [yellow]{str(cp.get('id'))[:10]}[/yellow]  "
                      f"[dim]{_fmt_time(float(cp.get('created_at', 0)))}[/dim]  "
                      f"[green]{n_files} 文件[/green]  "
                      f"[cyan]seq={cp.get('ledger_marker')}[/cyan]")
        if cp.get("summary"):
            console.print(f"      [dim]{str(cp.get('summary'))[:70]}[/dim]")
    console.print("\n[dim]详情: tuan checkpoint show <id> · 清理: tuan checkpoint prune[/dim]")
    return 0


_register_command("cmd_checkpoint", ".cmd_checkpoint")
