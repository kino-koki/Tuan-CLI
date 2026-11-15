"""integrity 命令 —— 文件完整性可观测性 (第 97 个独特功能)。

暴露 :mod:`tuan_cli.core.file_integrity` 的只读查询面:
- **变更历史**: 从 <home>/.integrity/changes.json 装载, 按严重度/变更类型/
  路径模式过滤, 支持最近 N 条;
- **统计**: 总变更数 + 按类型/按严重度分布;
- **报告**: Markdown 格式的完整性监控报告 (export_report)。

差异化价值: Claude Code 无「配置文件 / 内置技能 / SOUL 的 SHA-256 防篡改
监控」的只读查询入口。本命令把 FileIntegrityMonitor 落盘的变更记录开放为
可查询 (纯只读, 不触发任何写盘副作用 —— 不调用 snapshot/check)。

  tuan integrity [--home H] [--json]                    # 概览 (stats + 最近变更)
  tuan integrity stats [--home H] [--json]              # 变更统计
  tuan integrity changes [--severity S] [--change-type T] \
        [--path-pattern P] [--last N] [--home H] [--json]
  tuan integrity report [--last N] [--home H]           # Markdown 报告
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from ._ui_singleton import console
from .parser import _register_command


# ---------------------------------------------------------------- 辅助

def _get_monitor(home_raw: Optional[str]) -> Any:
    from ..core.file_integrity import FileIntegrityMonitor

    if home_raw:
        home = Path(home_raw).expanduser().resolve()
    else:
        from ..config.loader import home_dir
        home = home_dir()
    return FileIntegrityMonitor(home=home)


def _fmt_time(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (TypeError, ValueError, OSError):
        return "-"


def _sev_color(severity: str) -> str:
    return {"high": "red", "critical": "red", "medium": "yellow"}.get(severity, "dim")


def _change_dict(c: Any) -> dict[str, Any]:
    return {
        "path": c.path,
        "change_type": c.change_type,
        "old_sha256": c.old_sha256,
        "new_sha256": c.new_sha256,
        "severity": c.severity,
        "detected_at": c.detected_at,
        "time": _fmt_time(c.detected_at),
        "details": c.details,
    }


# ---------------------------------------------------------------- 子命令

def _cmd_changes(args: Any) -> int:
    """变更历史查询。"""
    from ..core.file_integrity import IntegrityChange  # noqa: F401 (类型提示)

    try:
        monitor = _get_monitor(getattr(args, "home", None))
        changes = monitor.get_changes(
            severity=getattr(args, "severity", None),
            change_type=getattr(args, "change_type", None),
            path_pattern=getattr(args, "path_pattern", None),
            last_n=int(getattr(args, "last", 100) or 100),
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]变更历史读取失败: {exc}[/red]")
        return 1

    if getattr(args, "json", False):
        print(json.dumps([_change_dict(c) for c in changes],
                         ensure_ascii=False, indent=2))
        return 0

    if not changes:
        console.print("[dim]暂无变更记录 (先 tuan safe integrity snapshot <目录> 建基准)[/dim]")
        return 0

    console.print(f"[bold]文件完整性变更历史 ({len(changes)} 条)[/bold]\n")
    for c in reversed(changes):
        color = _sev_color(c.severity)
        console.print(f"  [{color}]{c.severity.upper()}[/{color}] "
                      f"{_fmt_time(c.detected_at)}  {c.change_type}: {c.path}")
        if c.details:
            console.print(f"        [dim]{c.details}[/dim]")
    return 0


def _cmd_stats(args: Any) -> int:
    """变更统计。"""
    try:
        monitor = _get_monitor(getattr(args, "home", None))
        stats = monitor.stats()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]统计读取失败: {exc}[/red]")
        return 1

    if getattr(args, "json", False):
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    console.print("[bold]文件完整性变更统计[/bold]\n")
    console.print(f"  总变更数: {stats.get('total_changes', 0)}")
    console.print(f"  按类型:   {stats.get('by_type', {}) or '无'}")
    console.print(f"  按严重度: {stats.get('by_severity', {}) or '无'}")
    return 0


def _cmd_report(args: Any) -> int:
    """Markdown 报告导出。"""
    try:
        monitor = _get_monitor(getattr(args, "home", None))
        report = monitor.export_report(last_n=int(getattr(args, "last", 50) or 50))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]报告导出失败: {exc}[/red]")
        return 1

    print(report)
    return 0


def _cmd_overview(args: Any) -> int:
    """概览: 统计 + 最近变更。"""
    try:
        monitor = _get_monitor(getattr(args, "home", None))
        stats = monitor.stats()
        changes = monitor.get_changes(last_n=int(getattr(args, "last", 10) or 10))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]概览读取失败: {exc}[/red]")
        return 1

    if getattr(args, "json", False):
        print(json.dumps({
            "stats": stats,
            "recent": [_change_dict(c) for c in changes],
        }, ensure_ascii=False, indent=2))
        return 0

    console.print("[bold]=== 文件完整性监控 (只读) ===[/bold]\n")
    console.print(f"  总变更数: {stats.get('total_changes', 0)}")
    console.print(f"  按类型:   {stats.get('by_type', {}) or '无'}")
    console.print(f"  按严重度: {stats.get('by_severity', {}) or '无'}")

    if changes:
        console.print(f"\n[bold]最近变更 ({len(changes)} 条)[/bold]")
        for c in reversed(changes):
            color = _sev_color(c.severity)
            console.print(f"  [{color}]{c.severity.upper()}[/{color}] "
                          f"{_fmt_time(c.detected_at)}  {c.change_type}: {c.path}")
    else:
        console.print("\n[dim]暂无变更记录[/dim]")

    console.print("\n[dim]子命令: changes (过滤查询) / stats (统计) / "
                  "report (Markdown) | 数据源 <home>/.integrity/changes.json[/dim]")
    return 0


# ---------------------------------------------------------------- 分发入口

def cmd_integrity(args: Any) -> int:
    """文件完整性可观测性总入口 (第 97 个独特功能, 纯只读)。"""
    sub = getattr(args, "integrity_cmd", None) or "overview"

    if sub == "changes":
        return _cmd_changes(args)
    elif sub == "stats":
        return _cmd_stats(args)
    elif sub == "report":
        return _cmd_report(args)
    elif sub in ("overview", "status", ""):
        return _cmd_overview(args)
    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: overview / changes / stats / report")
        return 1


_register_command("cmd_integrity", ".cmd_integrity")
