"""posture 命令 —— 跨子系统安全/韧性健康总览 (第 101 个独特功能)。

把 Tuan-CLI 各**独立持久化**的安全/韧性子系统聚合成一张健康报表, 每个
子系统给出 PASS / WARN / FAIL 判定与可操作的修复命令:

  - 文件完整性   (FileIntegrityMonitor): 变更历史是否有 high/critical
  - 持久化告警   (AlertLogger):          最近 JSONL 是否有 critical
  - 审计链       (SecurityAuditor):      防篡改链 verify_integrity
  - 协作黑板     (CollaborationProtocol): 活动键数
  - 后台作业     (BackgroundStore):       失败作业数
  - 存储占用     (cmd_storage 扫描):      子系统占用与总量

差异化价值: Claude Code 的安全/韧性子系统各自黑箱, 用户无「全局健康
一眼看」的聚合入口, 也无跨子系统的 PASS/WARN/FAIL 判定。本命令把已
落盘的多个子系统合并成一张可审计报表, 是纯只读 (不触发任何写/清理)。

  tuan posture [--home H] [--json]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


# ---------------------------------------------------------------- 辅助

def _get_home(home_raw: Optional[str]) -> Path:
    if home_raw:
        return Path(home_raw).expanduser().resolve()
    from ..config.loader import home_dir
    return Path(home_dir())


def _verdict(level: str) -> str:
    return {"PASS": "[green]PASS[/green]", "WARN": "[yellow]WARN[/yellow]",
            "FAIL": "[red]FAIL[/red]"}.get(level, "[dim]SKIP[/dim]")


def _collect(home: Path) -> List[Dict[str, Any]]:
    """收集各子系统健康判定。"""
    rows: List[Dict[str, Any]] = []

    # 1. 文件完整性
    try:
        from ..core.file_integrity import FileIntegrityMonitor
        mon = FileIntegrityMonitor(home=home)
        changes = mon.get_changes(last_n=100)
        stats = mon.stats()
        high = sum(1 for c in changes if c.severity in ("high", "critical"))
        level = "FAIL" if high > 0 else ("WARN" if changes else "PASS")
        rows.append({
            "subsystem": "integrity", "level": level,
            "detail": f"{stats.get('total_changes', 0)} 变更, {high} 条 high/critical",
            "hint": "tuan integrity changes --severity high" if high else "tuan safe integrity snapshot <目录> 建基准",
        })
    except Exception as exc:  # noqa: BLE001
        rows.append({"subsystem": "integrity", "level": "SKIP",
                     "detail": str(exc)[:80], "hint": ""})

    # 2. 持久化告警
    try:
        from ..core.security_alert import AlertLogger
        logger = AlertLogger(home=home)
        records = logger.read_recent(last_n=100)
        crit = sum(1 for r in records if r.get("severity") == "critical")
        level = "FAIL" if crit > 0 else ("WARN" if records else "PASS")
        rows.append({
            "subsystem": "alerts", "level": level,
            "detail": f"{len(records)} 条持久化告警, {crit} 条 critical",
            "hint": "tuan alerts --severity critical" if crit else "tuan alerts",
        })
    except Exception as exc:  # noqa: BLE001
        rows.append({"subsystem": "alerts", "level": "SKIP",
                     "detail": str(exc)[:80], "hint": ""})

    # 3. 审计链 (防篡改)
    try:
        from ..core.security_auditor import SecurityAuditor
        auditor = SecurityAuditor(home=home)
        integ = auditor.verify_integrity()
        valid = bool(integ.get("valid"))
        # 全新安装 (审计日志尚未建立) 不算失败, 记 PASS + 未初始化提示
        if not valid and not Path(auditor._log_file).exists():
            rows.append({
                "subsystem": "audit_chain", "level": "PASS",
                "detail": "审计日志未初始化 (首次安全事件落盘后自动建立)",
                "hint": "",
            })
        else:
            rows.append({
                "subsystem": "audit_chain", "level": "PASS" if valid else "FAIL",
                "detail": integ.get("message", "")[:80],
                "hint": "" if valid else "tuan safe audit --verify-only",
            })
    except Exception as exc:  # noqa: BLE001
        rows.append({"subsystem": "audit_chain", "level": "SKIP",
                     "detail": str(exc)[:80], "hint": ""})

    # 4. 协作黑板
    try:
        from ..core.collaboration_protocol import CollaborationProtocol
        proto = CollaborationProtocol()
        stats = proto.stats()
        keys = int(stats.get("keys", 0) or 0)
        level = "WARN" if keys > 50 else "PASS"
        rows.append({
            "subsystem": "collab", "level": level,
            "detail": f"{keys} 个活动键",
            "hint": "tuan collab snapshot" if keys > 50 else "",
        })
    except Exception as exc:  # noqa: BLE001
        rows.append({"subsystem": "collab", "level": "SKIP",
                     "detail": str(exc)[:80], "hint": ""})

    # 5. 后台作业
    try:
        from ..core.background_store import BackgroundStore
        store = BackgroundStore(home=home)
        jobs = store.list()
        failed = sum(1 for j in jobs if j.get("status") == "failed")
        level = "FAIL" if failed > 0 else ("WARN" if jobs else "PASS")
        rows.append({
            "subsystem": "background", "level": level,
            "detail": f"{len(jobs)} 个作业, {failed} 个失败",
            "hint": "tuan bg list --failed" if failed else "",
        })
    except Exception as exc:  # noqa: BLE001
        rows.append({"subsystem": "background", "level": "SKIP",
                     "detail": str(exc)[:80], "hint": ""})

    # 6. 存储占用
    try:
        from .cmd_storage import _dir_size, _fmt_size, _subsystem_scan
        total = sum(r["bytes"] for r in _subsystem_scan(home))
        gb = total / (1024 ** 3)
        level = "WARN" if gb > 2 else "PASS"
        rows.append({
            "subsystem": "storage", "level": level,
            "detail": f"{_fmt_size(total)} 总计",
            "hint": "tuan storage" if gb > 2 else "",
        })
    except Exception as exc:  # noqa: BLE001
        rows.append({"subsystem": "storage", "level": "SKIP",
                     "detail": str(exc)[:80], "hint": ""})

    return rows


# ---------------------------------------------------------------- 入口

def cmd_posture(args: Any) -> int:
    """跨子系统安全/韧性健康总览 (第 101 个独特功能, 纯只读)。"""
    try:
        home = _get_home(getattr(args, "home", None))
        rows = _collect(home)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]健康总览失败: {exc}[/red]")
        return 1

    if getattr(args, "json", False):
        print(json.dumps({"home": str(home), "subsystems": rows},
                         ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]=== Tuan 跨子系统健康总览 · {home} ===[/bold]\n")
    for r in rows:
        console.print(f"  {_verdict(r['level'])}  {r['subsystem']:<14} {r['detail']}")
        if r.get("hint"):
            console.print(f"         [dim]→ {r['hint']}[/dim]")

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    if has_fail:
        console.print("\n[yellow]存在 FAIL 子系统, 用上方 hint 修复后复查[/yellow]")
    elif has_warn:
        console.print("\n[cyan]整体可运行, 有 WARN 建议关注[/cyan]")
    else:
        console.print("\n[green]全部子系统健康[/green]")
    return 1 if has_fail else 0


_register_command("cmd_posture", ".cmd_posture")
