"""tuan safe · 审计与告警视图子命令。

覆盖: audit / alerts / summary。只读展示, 不做执行侧决策。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from ...config.loader import home_dir
from .._ui_singleton import console


def _cmd_audit(args: Any) -> int:
    """安全审计可视入口: 完整性校验 / 关联告警 / 统计 / 导出。

    把安全审计器 (AEAD + HMAC 防篡改链) 的能力直接暴露给运维:
      tuan safe audit                   完整性校验 + 关联告警 + 统计
      tuan safe audit --last N          最近 N 条明文记录
      tuan safe audit --module NAME     按模块过滤
      tuan safe audit --verify-only     只跑完整性校验
      tuan safe audit --export md       导出 Markdown 报告
      tuan safe audit --export json     导出 JSON
      tuan safe audit --export jsonl    导出 JSONL (SIEM 可消费)
    """
    verify_only = bool(getattr(args, "verify_only", False))
    export_fmt = getattr(args, "export", None)
    last_n = int(getattr(args, "last", 50) or 50)
    module = getattr(args, "module", None)
    severity = getattr(args, "severity", None)

    # --- SecurityBus 维护操作 (第 55 个独特功能: 安全可观测性) ---
    if bool(getattr(args, "flush", False)) or bool(getattr(args, "clear", False)):
        from ...core.security_bus import get_security_bus
        bus = get_security_bus()
        if bool(getattr(args, "flush", False)):
            bus.flush()
            console.print(f"[green]✓ 已刷盘[/green] SecurityBus 事件 (持久路径: "
                          f"{bus._persist_path or '(未持久化)'})")
        if bool(getattr(args, "clear", False)):
            bus.clear()
            console.print("[green]✓ 已清空[/green] SecurityBus 内存事件 (审计链不受影响)")
        return 0

    try:
        from ...core.security_auditor import SecurityAuditor
        auditor = SecurityAuditor(home=Path(home_dir()))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]安全审计器初始化失败: {exc}[/red]")
        return 1

    # --- 完整性校验 (防篡改链全量重放) ---
    integrity = auditor.verify_integrity()
    if verify_only:
        if integrity.get("valid"):
            console.print(f"[green]✓ 审计链完整[/green] 校验 {integrity.get('checked', 0)} 条记录 "
                          f"(日志: {integrity.get('message', '')})")
            return 0
        console.print(f"[red]✗ 审计链损坏[/red] {integrity.get('message', '')}")
        return 1

    # --- 导出 ---
    if export_fmt:
        fmt = export_fmt.lower()
        try:
            if fmt == "md":
                text = auditor.export_markdown(last_n)
                sys.stdout.write(text + "\n")
            elif fmt == "json":
                sys.stdout.write(auditor.export_json(last_n) + "\n")
            elif fmt == "jsonl":
                import json as _json
                for rec in auditor.recent_alerts(last_n):
                    sys.stdout.write(_json.dumps(rec, ensure_ascii=False) + "\n")
            else:
                console.print(f"[red]未知导出格式: {fmt} (可选 md/json/jsonl)[/red]")
                return 1
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]导出失败: {exc}[/red]")
            return 1
        # 状态行写到 stderr; console 是剥离标记的 PlainConsole, 等价纯文本输出。
        sys.stderr.write(f"已导出 {last_n} 条 → {fmt}\n")
        return 0

    # --- 总览 ---
    console.print("\n[bold]=== 安全审计 · 可视化 ===[/bold]\n")

    # 完整性
    if integrity.get("valid"):
        console.print(f"[bold]防篡改链[/bold]: [green]✓ 完整[/green] "
                      f"(校验 {integrity.get('checked', 0)} 条)")
    else:
        console.print(f"[bold]防篡改链[/bold]: [red]✗ 损坏[/red] "
                      f"{integrity.get('message', '')}")

    # 统计
    try:
        stats = auditor.stats()
        sev = stats.get("by_severity", {})
        console.print(f"[bold]记录[/bold]: {stats.get('total', 0)} 条 "
                      f"| 严重度 {sev or '无'} | 算法 {stats.get('algorithm', '?')}")
        corr = stats.get("correlation", {}) or {}
        console.print(f"[bold]关联[/bold]: {corr.get('total_alerts', 0)} 个告警, "
                      f"{corr.get('unique_signatures', 0)} 个模式")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]统计读取失败: {exc}[/red]")

    # 最近关联告警
    try:
        alerts = auditor.recent_alerts(last_n)
        if alerts:
            console.print(f"\n[bold]最近关联告警 (最近 {len(alerts)} 条)[/bold]")
            for a in alerts:
                ts = a.get("ts", "")
                if isinstance(ts, (int, float)):
                    from datetime import datetime as _dt
                    ts = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                console.print(f"  [yellow]{a.get('severity', '?')}[/yellow] "
                              f"{ts}  {a.get('signature', '')}  "
                              f"(模块 {a.get('module', '?')})")
        else:
            console.print("\n[dim]暂无关联告警 (会话内未触发安全事件)[/dim]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]关联告警读取失败: {exc}[/red]")

    # 最近明文记录
    try:
        recs = auditor.query(module=module, severity=severity, last_n=last_n)
        if recs:
            console.print(f"\n[bold]最近审计记录 (最近 {len(recs)} 条)[/bold]")
            for r in recs[-15:]:
                from datetime import datetime as _dt
                ts = _dt.fromtimestamp(r.ts).strftime("%Y-%m-%d %H:%M:%S")
                console.print(f"  {ts}  [{r.severity}]  "
                              f"{r.module}.{r.action}  {r.input_summary[:60] if r.input_summary else ''}")
        else:
            console.print("\n[dim]无匹配记录 (可加 --module/--severity 过滤)[/dim]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]记录查询失败: {exc}[/red]")

    console.print("\n[dim]提示: tuan safe audit --export md/json/jsonl 可导出; "
                  "--verify-only 只跑完整性校验[/dim]")
    return 0


def _cmd_alerts(args: Any) -> int:
    """安全告警历史/统计/导出 (第 58 个独特功能: 实时告警通道可观测)。

    暴露 SecurityAlerter (实时告警通道: 多通道通知 + 速率限制 + 内存缓冲)
    的查询/导出能力 —— 这是与 SecurityAuditor (防篡改审计链) 互补的另一条
    安全观测线: Auditor 记「系统做了什么」, Alerter 记「用户被告警了什么」。
    Claude Code 的告警只在日志里, 没有历史/统计/导出入口。

      tuan safe alerts                    # 最近告警 (内存缓冲)
      tuan safe alerts --severity high    # 按严重度过滤
      tuan safe alerts --last 100         # 最近 100 条
      tuan safe alerts --stats            # 只显示统计 (严重度/来源分布)
      tuan safe alerts --export md        # 导出 Markdown 报告
      tuan safe alerts --json             # 机器可读 (CI / SIEM 消费)
    """
    from ...core.security_alert import SecurityAlerter

    alerter = SecurityAlerter(home=Path(home_dir()))
    last_n = int(getattr(args, "last", 50) or 50)
    severity = getattr(args, "severity", None)
    json_mode = bool(getattr(args, "json", False))
    stats_only = bool(getattr(args, "stats", False))
    export_fmt = getattr(args, "export", None)

    # --- 导出报告 ---
    if export_fmt:
        fmt = export_fmt.lower()
        if fmt == "md":
            sys.stdout.write(alerter.export_alerts(last_n) + "\n")
        else:
            console.print(f"[red]未知导出格式: {fmt} (可用 md)[/red]")
            return 1
        return 0

    # --- 统计 ---
    stats = alerter.get_alert_stats()
    if json_mode:
        json_recent = [
            {
                "severity": r.severity,
                "title": r.title,
                "message": r.message[:200],
                "source": r.source,
                "timestamp": r.timestamp,
                "notified": r.notified,
            }
            for r in alerter.get_recent_alerts(severity=severity, last_n=last_n)
        ]
        sys.stdout.write(json.dumps({
            "stats": stats,
            "count": len(json_recent),
            "recent": json_recent,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    if stats_only:
        console.print("\n[bold]=== 安全告警统计 (实时告警通道) ===[/bold]\n")
        console.print(f"  [bold]总数[/bold]: {stats.get('total', 0)}")
        by_sev = stats.get("by_severity", {}) or {}
        for sev in ("critical", "high", "medium", "low"):
            n = by_sev.get(sev, 0)
            if n:
                color = {"critical": "red", "high": "yellow", "medium": "cyan",
                         "low": "dim"}.get(sev, "dim")
                console.print(f"  [{color}]{sev:>8}[/{color}]  {n}")
        by_src = stats.get("by_source", {}) or {}
        if by_src:
            console.print(f"\n  [bold]按来源[/bold]:")
            for src, n in sorted(by_src.items(), key=lambda kv: -kv[1]):
                console.print(f"    {src}  {n}")
        console.print("\n[dim]提示: tuan safe alerts 看明细; --export md 导出报告[/dim]")
        return 0

    # --- 明细 ---
    recent = alerter.get_recent_alerts(severity=severity, last_n=last_n)
    if not recent:
        console.print("[dim]无告警记录 (安全事件未触发实时告警通道)[/dim]")
        console.print("[dim]提示: 运行 `tuan chat` 触发安全事件; 或 tuan safe audit 看审计链[/dim]")
        return 0

    console.print(f"\n[bold]=== 安全告警 (最近 {len(recent)} 条) ===[/bold]\n")
    for r in reversed(recent):
        color = {"critical": "red", "high": "yellow", "medium": "cyan",
                 "low": "dim"}.get(r.severity, "dim")
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp))
        notified = " [green]✓通知[/green]" if r.notified else ""
        console.print(f"  [{color}]{r.severity.upper():>8}[/{color}] "
                      f"[dim]{ts}[/dim] {r.title}{notified}")
        if r.message:
            console.print(f"      [dim]{r.message[:160]}[/dim]")
        if r.source:
            console.print(f"      [dim]来源: {r.source}[/dim]")
    console.print("\n[dim]提示: tuan safe alerts --stats 看分布; --export md 导出; "
                  "--severity critical 只看严重[/dim]")
    return 0


def _cmd_summary(args: Any) -> int:
    """安全事件摘要 (第 55 个独特功能: 安全可观测性)。

    直接暴露 SecurityBus.summary(): 类型/严重度分布 + 最近 Critical 事件。
    Claude Code 无此概念 —— 安全事件只在日志里, 没有「摘要」入口。

      tuan safe summary                  # 文本摘要
      tuan safe summary --last 50        # 只看最近 50 条
      tuan safe summary --json           # 机器可读 (统计 + 最近 Critical)
    """
    from ...core.security_bus import get_security_bus

    bus = get_security_bus()
    last_n = int(getattr(args, "last", 100) or 100)
    json_mode = bool(getattr(args, "json", False))

    if json_mode:
        stats = bus.get_stats()
        criticals = [
            {
                "source": e.source,
                "event_type": e.event_type,
                "severity": e.severity,
                "command": e.payload.get("command", "")[:200],
                "ts": e.timestamp,
            }
            for e in bus.get_events(severity="critical", limit=10)
        ]
        sys.stdout.write(json.dumps({
            "summary": stats,
            "recent_critical": criticals,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print(bus.summary(last_n))
    return 0
