"""alerts 命令 —— 持久化安全告警可观测性 (第 98 个独特功能)。

暴露 :mod:`tuan_cli.core.security_alert` 中 **AlertLogger 的磁盘只读面**:
读取 <home>/audit/security_alerts.jsonl (跨进程持久化的告警日志, 进程重启
后仍在), 按严重度/来源/时间过滤, 支持统计与 Markdown 导出。

差异化价值: `tuan safe alerts` 暴露的是 SecurityAlerter 的**内存缓冲**
(仅当前进程, 重启即失)。本命令读的是 AlertLogger 落盘的 **JSONL 文件**,
是跨进程、跨重启的持久审计面 —— 运维可回溯「历史上用户被告警了什么」,
与 Auditor 防篡改链互补 (Auditor 记系统行为, AlertLogger 记用户告警)。

纯只读: 不调用 SecurityAlerter.alert(), 不写入, 只 read_text + json.loads。

  tuan alerts [--home H] [--json]                     # 最近告警 (持久化)
  tuan alerts --severity high [--last 100] [--home H] # 按严重度过滤
  tuan alerts --source mcp_security [--home H]        # 按来源过滤
  tuan alerts stats [--home H] [--json]               # 持久化告警统计
  tuan alerts report [--last 100] [--home H]          # Markdown 报告
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


# ---------------------------------------------------------------- 辅助

def _get_logger(home_raw: Optional[str]) -> Any:
    from ..core.security_alert import AlertLogger

    if home_raw:
        home = Path(home_raw).expanduser().resolve()
    else:
        from ..config.loader import home_dir
        home = Path(home_dir())
    return AlertLogger(home=home)


def _fmt_time(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (TypeError, ValueError, OSError):
        return "-"


def _sev_color(severity: str) -> str:
    return {"critical": "red", "high": "red", "medium": "yellow"}.get(severity, "dim")


def _filter_records(
    records: List[Dict[str, Any]],
    severity: Optional[str],
    source: Optional[str],
    last_n: int,
) -> List[Dict[str, Any]]:
    if severity:
        records = [r for r in records if r.get("severity") == severity]
    if source:
        records = [r for r in records if r.get("source") == source]
    return records[-last_n:]


def _record_dict(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "severity": r.get("severity", "low"),
        "title": r.get("title", ""),
        "message": r.get("message", ""),
        "source": r.get("source", ""),
        "timestamp": r.get("timestamp", 0.0),
        "time": _fmt_time(float(r.get("timestamp", 0.0))),
        "notified": bool(r.get("notified", False)),
        "details": r.get("details", {}),
    }


# ---------------------------------------------------------------- 子命令

def _cmd_alerts_list(args: Any) -> int:
    """最近告警明细 (持久化)。"""
    try:
        logger = _get_logger(getattr(args, "home", None))
        records = logger.read_recent(last_n=max(int(getattr(args, "last", 50) or 50), 1))
        records = _filter_records(
            records,
            getattr(args, "severity", None),
            getattr(args, "source", None),
            int(getattr(args, "last", 50) or 50),
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]告警日志读取失败: {exc}[/red]")
        return 1

    if getattr(args, "json", False):
        print(json.dumps([_record_dict(r) for r in records],
                         ensure_ascii=False, indent=2))
        return 0

    if not records:
        console.print("[dim]暂无持久化告警记录 (文件 <home>/audit/security_alerts.jsonl 为空)[/dim]")
        return 0

    console.print(f"[bold]持久化安全告警 ({len(records)} 条)[/bold]\n")
    for r in reversed(records):
        sev = r.get("severity", "low")
        color = _sev_color(sev)
        console.print(f"  [{color}]{str(sev).upper()}[/{color}] "
                      f"{_fmt_time(float(r.get('timestamp', 0.0)))}  "
                      f"{r.get('title', '')}")
        msg = (r.get("message") or "")[:120]
        if msg:
            console.print(f"        [dim]{msg}[/dim]")
        if r.get("source"):
            console.print(f"        [dim]来源: {r['source']}[/dim]")
    return 0


def _cmd_alerts_stats(args: Any) -> int:
    """持久化告警统计。"""
    try:
        logger = _get_logger(getattr(args, "home", None))
        records = logger.read_recent(last_n=100000)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]告警日志读取失败: {exc}[/red]")
        return 1

    by_severity: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    for r in records:
        sev = r.get("severity", "unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        src = r.get("source", "") or "(无)"
        by_source[src] = by_source.get(src, 0) + 1

    stats = {"total": len(records), "by_severity": by_severity, "by_source": by_source}

    if getattr(args, "json", False):
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    console.print("[bold]持久化安全告警统计[/bold]\n")
    console.print(f"  总告警数: {stats['total']}")
    console.print(f"  按严重度: {by_severity or '无'}")
    console.print(f"  按来源:   {by_source or '无'}")
    console.print("\n[dim]数据源 <home>/audit/security_alerts.jsonl (跨进程持久化)[/dim]")
    return 0


def _cmd_alerts_report(args: Any) -> int:
    """Markdown 报告导出。"""
    try:
        logger = _get_logger(getattr(args, "home", None))
        records = logger.read_recent(last_n=int(getattr(args, "last", 100) or 100))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]告警日志读取失败: {exc}[/red]")
        return 1

    lines = [
        "# 安全告警报告 (持久化)",
        "",
        f"- 总告警数: {len(records)}",
        "",
    ]
    for r in reversed(records):
        sev = r.get("severity", "low")
        ts = _fmt_time(float(r.get("timestamp", 0.0)))
        lines.append(f"### [{str(sev).upper()}] [{ts}] {r.get('title', '')}")
        if r.get("message"):
            lines.append(f"- {str(r.get('message', ''))[:200]}")
        if r.get("source"):
            lines.append(f"- 来源: {r.get('source')}")
        lines.append("")

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------- 分发入口

def cmd_alerts(args: Any) -> int:
    """持久化安全告警可观测性总入口 (第 98 个独特功能, 纯只读)。"""
    sub = getattr(args, "alerts_cmd", None) or "list"

    if sub == "stats":
        return _cmd_alerts_stats(args)
    elif sub == "report":
        return _cmd_alerts_report(args)
    elif sub in ("list", "recent", ""):
        return _cmd_alerts_list(args)
    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: list / stats / report")
        return 1


_register_command("cmd_alerts", ".cmd_alerts")
