"""safety 命令 —— 跨来源综合风险评分 (第 106 个独特功能)。

把多个**持久化只读面**的安全信号加权合成为单一 0-100 风险分, 并回答
「此刻整体风险多高、风险从哪条线来」。现有命令各自只读单一条线
(``safe trends`` 只读安全事件流、``integrity`` 只读文件变更、
``alerts`` 只读告警、``safe audit`` 只读审计链), 没有任何命令把四条线
**按同一时间窗口对齐并加权合成** —— 这正是本命令的差异化价值。

差异化价值: Claude Code 只有扁平命令级判定, 无「跨来源合成的可比较分数」。
本命令给趋势/基线用 —— 用户可用 ``--json`` 落一个分数, 下次再比, 观察
安全态势演进; 也可看「哪一子系统贡献最大」定位风险源头。

纯只读: 不构造 SecurityEventBus / 不触发任何写盘; 只用 AlertLogger.
read_recent + FileIntegrityMonitor.get_changes + SecurityAuditor.query +
明文安全事件流文件读取。四者均为只读/纯计算, 零写副作用。

  tuan safety score [--window H] [--json]     # 综合风险分 (0-100) + 各线贡献
"""

from __future__ import annotations

import logging
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


# 严重度 → 扣分权重 (单条)

log = logging.getLogger(__name__)
_SEV_WEIGHT = {"critical": 8.0, "high": 4.0, "medium": 2.0, "low": 1.0}
# 各线相对权重 (风险占比)
_LINE_WEIGHT = {"events": 0.4, "alerts": 0.25, "integrity": 0.2, "audit": 0.15}


def _get_home(home_raw: Optional[str]) -> Path:
    if home_raw:
        return Path(home_raw).expanduser().resolve()
    from ..config.loader import home_dir
    return Path(home_dir())


def _read_security_events(home: Path, window: float) -> List[Dict[str, Any]]:
    """读取明文安全事件流 (只读文件, 零写副作用)。"""
    for cand in (home / "security-audit.jsonl",
                 home / "audit" / "security_events.jsonl"):
        try:
            if cand.exists() and cand.stat().st_size > 0:
                rows: List[Dict[str, Any]] = []
                with cand.open("r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        ts = float(d.get("ts", 0) or 0)
                        if ts and ts >= window:
                            rows.append(d)
                return rows
        except OSError:
            continue
    return []


def _score_sev(rows: List[Any], sev_key: str = "severity") -> float:
    """按严重度加权累计扣分 (单条扣分, 越重越狠)。

    接受 dict 或带 .severity 属性的对象 (IntegrityChange/AuditRecord)。
    """
    total = 0.0
    for r in rows:
        if isinstance(r, dict):
            sev = str(r.get(sev_key, "") or "info").lower()
        else:
            sev = str(getattr(r, sev_key, "info") or "info").lower()
        total += _SEV_WEIGHT.get(sev, 0.25)
    return total


def _collect_line_scores(home: Path, window: float) -> List[Dict[str, Any]]:
    """采集四条线的原始扣分 (纯只读), 供加权合成。"""
    lines: List[Dict[str, Any]] = []

    # 1. 安全事件流 (明文)
    try:
        ev_rows = _read_security_events(home, window)
        raw = _score_sev(ev_rows)
        lines.append({
            "name": "events", "label": "安全事件流",
            "count": len(ev_rows), "raw": raw,
            "detail": f"{len(ev_rows)} 条 (critical/high/medium/low 加权)",
        })
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        lines.append({"name": "events", "label": "安全事件流", "count": 0,
                      "raw": 0.0, "detail": f"跳过: {str(exc)[:60]}"})

    # 2. 持久化告警 (AlertLogger 落盘 JSONL)
    try:
        from ..core.security_alert import AlertLogger
        alerts = AlertLogger(home=home).read_recent(last_n=200)
        in_win_al = [a for a in alerts if float(a.get("ts", 0) or 0) >= window]
        raw = _score_sev(in_win_al)
        lines.append({
            "name": "alerts", "label": "持久化告警",
            "count": len(in_win_al), "raw": raw,
            "detail": f"{len(in_win_al)} 条 (AlertLogger 落盘)",
        })
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        lines.append({"name": "alerts", "label": "持久化告警", "count": 0,
                      "raw": 0.0, "detail": f"跳过: {str(exc)[:60]}"})

    # 3. 文件完整性变更 (FileIntegrityMonitor 落盘)
    try:
        from ..core.file_integrity import FileIntegrityMonitor
        mon = FileIntegrityMonitor(home=home)
        changes = mon.get_changes(last_n=200)
        in_win_int = [c for c in changes if getattr(c, "ts", 0.0) >= window]
        raw = _score_sev(in_win_int)
        lines.append({
            "name": "integrity", "label": "文件完整性",
            "count": len(in_win_int), "raw": raw,
            "detail": f"{len(in_win_int)} 处变更 (FileIntegrityMonitor)",
        })
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        lines.append({"name": "integrity", "label": "文件完整性", "count": 0,
                      "raw": 0.0, "detail": f"跳过: {str(exc)[:60]}"})

    # 4. 审计链 (SecurityAuditor AEAD, 防篡改)
    try:
        from ..core.security_auditor import SecurityAuditor
        auditor = SecurityAuditor(home=home)
        records = auditor.query(last_n=200)
        in_win_aud = [r for r in records if getattr(r, "ts", 0.0) >= window]
        raw = _score_sev(in_win_aud)
        lines.append({
            "name": "audit", "label": "审计链",
            "count": len(in_win_aud), "raw": raw,
            "detail": f"{len(in_win_aud)} 条 (AEAD 防篡改)",
        })
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        lines.append({"name": "audit", "label": "审计链", "count": 0,
                      "raw": 0.0, "detail": f"跳过: {str(exc)[:60]}"})

    return lines


def cmd_safety(args: Any) -> int:
    """跨来源综合风险评分 (第 106 个独特功能, 纯只读)。"""
    try:
        home = _get_home(getattr(args, "home", None))
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]home 解析失败: {exc}[/red]")
        return 1

    json_mode = bool(getattr(args, "json", False))
    window_h = int(getattr(args, "window", 24) or 24)
    window = time.time() - window_h * 3600.0

    lines = _collect_line_scores(home, window)

    # 加权合成: 每条线归一化扣分 = raw * line_weight; 总分 = 100 - Σ
    weighted_total = 0.0
    line_parts: List[Dict[str, Any]] = []
    for ln in lines:
        contrib = ln["raw"] * _LINE_WEIGHT.get(ln["name"], 0.1)
        weighted_total += contrib
        line_parts.append({
            "line": ln["name"], "label": ln["label"],
            "count": ln["count"], "raw": ln["raw"],
            "weight": _LINE_WEIGHT.get(ln["name"], 0.1),
            "contribution": round(contrib, 2),
            "detail": ln["detail"],
        })
    score = max(0.0, min(100.0, 100.0 - weighted_total))
    # 贡献最大线
    if line_parts:
        top = max(line_parts, key=lambda p: p["contribution"])
        top_line = top["line"]
        top_pct = (top["contribution"] / weighted_total * 100.0) if weighted_total else 0.0
    else:
        top_line, top_pct = "-", 0.0

    # 风险分级
    if score >= 90:
        grade, color = "极低", "green"
    elif score >= 70:
        grade, color = "低", "green"
    elif score >= 45:
        grade, color = "中", "yellow"
    elif score >= 20:
        grade, color = "高", "red"
    else:
        grade, color = "危急", "red"

    if json_mode:
        print(json.dumps({
            "score": round(score, 1), "grade": grade,
            "window_hours": window_h, "lines": line_parts,
            "top_contributor": {"line": top_line, "percent": round(top_pct, 1)},
        }, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]跨来源综合风险评分 · {home}[/bold]\n")
    console.print(f"  综合风险分: [{color}]{score:.0f}/100 ({grade})[/{color}]")
    console.print(f"  风险主要来源: {top_line} "
                  f"(贡献 {top_pct:.0f}%)")
    console.print("\n[bold]各线贡献[/bold]")
    for p in line_parts:
        bar = "█" * int(min(20, p["contribution"] / 2)) if p["contribution"] else ""
        console.print(f"  {p['label']:<8} {p['contribution']:>6.1f}  "
                      f"[dim]{bar}[/dim]  {p['detail']}")
    console.print("\n[dim]说明: 0-100 分, 事件越少/越轻分越高; "
                  "--window 可改时间窗 (默认 24h)[/dim]")
    return 0


_register_command("cmd_safety", ".cmd_safety")
