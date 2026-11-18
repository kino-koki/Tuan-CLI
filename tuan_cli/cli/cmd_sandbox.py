"""tuan sandbox —— 进程隔离沙箱可观测性 (差异化能力)。

Claude Code 使用 Docker 沙箱 (--sandbox docker), 但**没有**第一等的沙箱
裁决/策略可观测命令 —— 用户无法回答「我的沙箱到底拦截了什么、用什么后端、
副本模式是否生效」。Tuan-CLI 的 :mod:`tuan_cli.sandbox` 是核心差异化能力
(4 层滤网 L0 意图 → L1 信任 → L2 资源 → L3 强隔离 + copy-diff-apply 副本),
本模块把这条流水线暴露为可审计命令:

    tuan sandbox assess "<command>"      完整 4 层滤网裁决 (差异化)
    tuan sandbox policy                  当前沙箱策略 + 可用后端 (差异化)
    tuan sandbox backends                探测本机可用隔离后端 (差异化)
    tuan sandbox trace --last N          最近沙箱裁决 (若已接审计/总线)

与 ``safe risk`` (六维风险向量, 纯风险构成) 不同: ``sandbox assess`` 是
**真实执行层裁决** (谁在 L0-L3 哪层拦截、建议哪个执行域、是否强隔离),
两者互补 —— risk 解释「为什么危险」, sandbox 解释「实际怎么裁决」。
"""

from __future__ import annotations

import logging
import json
import os
import sys
from typing import Any, Dict, List

from ..config import Config
from ..config.loader import home_dir
from ._ui_singleton import console



log = logging.getLogger(__name__)
def _build_sandbox() -> Any:
    """按配置构建 SandboxManager (生产工厂, 含审计/总线接线)。"""
    from ..sandbox.manager import SandboxManager

    cfg = Config()
    policy = cfg.get("sandbox", {}) or {}
    auditor = None
    bus = None
    try:
        from ..core.security_auditor import SecurityAuditor

        auditor = SecurityAuditor(home=home_dir())
    except Exception as exc:  # noqa: BLE001 - 审计不可用不阻塞
        log.debug("安全路径 fallback 降级: %s", exc)
        auditor = None
    try:
        from ..core.security_bus import get_security_bus

        bus = get_security_bus()
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        bus = None
    return SandboxManager(policy, auditor=auditor, bus=bus)


def _payload_for(command: str, workspace: str, yolo: bool) -> Any:
    """构造命令 Payload (与 assess_command 同构)。"""
    from ..sandbox.verdict import Payload

    return Payload(
        tool_name="run_shell",
        text=[command],
        command=command,
        method="shell",
        workspace=workspace,
        trust_level=None,
        plan_mode=False,
        yolo=yolo,
        require_confirm=not yolo,
        meta={},
    )


def cmd_sandbox(args: Any) -> int:
    """tuan sandbox 入口: 沙箱可观测性。"""
    sub = getattr(args, "sandbox_cmd", None) or "policy"

    if sub == "assess":
        return _sandbox_assess(args)
    if sub == "policy":
        return _sandbox_policy(args)
    if sub == "backends":
        return _sandbox_backends(args)
    if sub == "trace":
        return _sandbox_trace(args)
    console.print("未知子命令。可用: assess / policy / backends / trace")
    return 1


def _sandbox_assess(args: Any) -> int:
    """对单条命令跑完整 4 层滤网, 展示真实裁决 (第 37 个独特功能)。

      tuan sandbox assess "rm -rf /"
      tuan sandbox assess "git push" --workspace e:\\proj --yolo --json
    """
    command = getattr(args, "command", "")
    workspace = getattr(args, "workspace", None) or os.getcwd()
    yolo = bool(getattr(args, "yolo", False))
    json_mode = bool(getattr(args, "json", False))
    if not command:
        console.print("[red]用法: tuan sandbox assess \"<命令>\" [--workspace DIR] [--yolo] [--json][/red]")
        return 1

    mgr = _build_sandbox()
    payload = _payload_for(command, workspace, yolo)
    verdict = mgr.assess(payload)

    if json_mode:
        sys.stdout.write(json.dumps({
            "command": command,
            "workspace": workspace,
            "yolo": yolo,
            "action": verdict.action.value,
            "layer": verdict.layer,
            "severity": verdict.severity,
            "reason": verdict.reason,
            "suggestions": list(verdict.suggestions),
            "blocks": verdict.blocks,
            "isolate": verdict.isolate,
            "network_allowed": verdict.network,
            "backend": verdict.backend,
            "workspace_mode": verdict.workspace_mode,
            "memory_mb": verdict.memory_mb,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    act_color = {"allow": "green", "confirm": "yellow",
                 "isolate": "orange", "deny": "red"}
    sev_color = {"info": "dim", "low": "cyan", "medium": "yellow",
                 "high": "orange", "critical": "red"}
    color = act_color.get(verdict.action.value, "dim")
    sev = sev_color.get(verdict.severity, "dim")

    console.print("\n[bold]=== 沙箱 4 层滤网裁决 ===[/bold]\n")
    console.print(f"  命令: [dim]{command[:90]}{'…' if len(command) > 90 else ''}[/dim]")
    console.print(f"  工作区: [dim]{workspace}[/dim]"
                  + ("  [dim](yolo 模式)[/dim]" if yolo else ""))
    console.print(f"\n  [bold]裁决[/bold]: [{color}]{verdict.action.value.upper()}[/{color}]"
                  f"  ([{sev}]{verdict.severity}[/{sev}])")
    console.print(f"  [bold]命中层[/bold]: {verdict.layer} "
                  f"(L0 意图 / L1 信任 / L2 资源 / L3 强隔离)")
    if verdict.reason:
        console.print(f"  [bold]理由[/bold]: {verdict.reason}")
    if verdict.suggestions:
        console.print("  [bold]建议[/bold]:")
        for s in verdict.suggestions:
            console.print(f"    [dim]· {s}[/dim]")

    console.print("\n  [bold]执行域[/bold]")
    console.print(f"    隔离: {'[yellow]需要[/yellow]' if verdict.isolate else '[green]不需要[/green]'}")
    console.print(f"    后端: {verdict.backend or 'auto'}")
    console.print(f"    工作区模式: {verdict.workspace_mode} "
                  "(direct=真工作区 / copy_diff_apply=隔离副本)")
    console.print(f"    网络: {'[green]允许[/green]' if verdict.network else '[yellow]阻断[/yellow]'}")
    if verdict.memory_mb:
        console.print(f"    内存上限: {verdict.memory_mb} MB")

    if verdict.blocks:
        console.print("\n[red]→ 该命令会被沙箱拦截 (fail-closed)[/red]")
    elif verdict.isolate:
        console.print("\n[orange]→ 该命令将隔离执行 (副本或强后端)[/orange]")
    else:
        console.print("\n[green]→ 该命令允许直跑 (宿主)[/green]")

    console.print("\n[dim]提示: safe risk 看六维风险构成; sandbox policy 看策略; "
                  "sandbox trace 看历史裁决[/dim]")
    return 0


def _sandbox_policy(args: Any) -> int:
    """当前沙箱策略 (合并默认值) + 启用状态 (第 37 个独特功能)。

    Claude Code 的 --sandbox docker 是一个开关, 无策略透明度; 这里展示
    resource 限制 / 后端选择 / 副本阈值 / 域名白名单, 让用户知道沙箱到底
    承诺了什么约束 —— 避免「以为隔离了其实没隔离」。
    """
    json_mode = bool(getattr(args, "json", False))
    try:
        cfg = Config()
        raw_policy = cfg.get("sandbox", {}) or {}
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]读取配置失败: {exc}[/red]")
        return 1

    from ..sandbox.manager import DEFAULT_POLICY, json_deep_merge

    merged = json_deep_merge(DEFAULT_POLICY, raw_policy)
    resource = merged.get("resource", {}) or {}

    if json_mode:
        sys.stdout.write(json.dumps({
            "enabled": bool(merged.get("enabled", True)),
            "backend": merged.get("backend", "auto"),
            "enforce_required": bool(merged.get("enforce_required", True)),
            "deny_unknown_shell": bool(merged.get("deny_unknown_shell", False)),
            "resource": resource,
            "allowed_domains": list(merged.get("allowed_domains", []) or []),
            "configured_overrides": list(raw_policy.keys()),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    enabled = bool(merged.get("enabled", True))
    console.print("\n[bold]=== 沙箱策略 ===[/bold]\n")
    console.print(f"  启用: {'[green]✓ 开启[/green]' if enabled else '[red]✗ 关闭[/red]'}")
    console.print(f"  后端: {merged.get('backend', 'auto')} "
                  f"(auto=自动探测 local/docker/landlock/seatbelt/jobobject)")
    console.print(f"  无强后端时 fail-closed: "
                  f"{'[green]✓ 拒绝[/green]' if merged.get('enforce_required', True) else '[red]✗ 静默降级[/red]'}")
    console.print(f"  未知 shell 拒绝: {merged.get('deny_unknown_shell', False)}")

    console.print("\n  [bold]资源限制[/bold]")
    for key, label in (("max_memory_mb", "内存上限 MB"),
                       ("max_timeout", "超时秒"),
                       ("cpu_rate_pct", "CPU 速率 %"),
                       ("active_process_limit", "活跃进程上限"),
                       ("kill_timeout_seconds", "终止宽限秒"),
                       ("isolate_copy_threshold", "副本隔离阈值")):
        val = resource.get(key, 0)
        if key == "isolate_copy_threshold":
            console.print(f"    {label}: {val} (高危以上走 copy-diff-apply)")
        elif val:
            console.print(f"    {label}: {val}")
        else:
            console.print(f"    {label}: [dim]不限[/dim]")

    domains = merged.get("allowed_domains", []) or []
    console.print(f"  域名白名单: {', '.join(domains) if domains else '[dim]未设置 (默认阻断网络)[/dim]'}")

    console.print("\n[dim]说明: copy_diff_apply=高危命令在隔离副本执行, diff 预览+确认后才写回; "
                  "sandbox backends 看本机可用后端[/dim]")
    return 0


def _sandbox_backends(args: Any) -> int:
    """探测本机可用隔离后端 (第 37 个独特功能)。

    Claude Code 沙箱后端是黑箱 (docker 存在才可用); 这里逐后端探测,
    如实汇报「能真正强制隔离」还是「降级裸跑」—— 防止选了不可用后端
    却在 enforce_required 关闭时静默裸执行。
    """
    json_mode = bool(getattr(args, "json", False))
    from ..sandbox.backends import pick_backend, detect_backends

    try:
        backend_list = detect_backends()
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]后端探测失败: {exc}[/red]")
        return 1
    available = [b["name"] for b in backend_list if b.get("available")]

    chosen, ok = pick_backend("auto")
    chosen_reason = "可用强后端" if ok else "仅本地降级"

    if json_mode:
        sys.stdout.write(json.dumps({
            "available": available,
            "all_backends": backend_list,
            "chosen": chosen,
            "chosen_ok": ok,
            "chosen_reason": chosen_reason,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 沙箱隔离后端探测 ===[/bold]\n")
    if not available:
        console.print("[red]无可用强隔离后端[/red]")
        console.print("  若 enforce_required=true, 高危命令将被 fail-closed 拒绝")
        console.print("  (而非静默降级裸跑) —— 这是设计意图, 不是缺陷。")
        return 0
    for b in available:
        console.print(f"  [green]✓[/green] {b}")
    console.print(f"\n  自动选中: [bold]{chosen}[/bold]")
    if chosen_reason:
        console.print(f"  [dim]{chosen_reason}[/dim]")
    console.print("\n[dim]说明: local=裸跑非 OS 级隔离; docker/landlock/seatbelt/jobobject=强隔离; "
                  "若自动选中 local 且 enforce_required, 高危命令会 fail-closed[/dim]")
    return 0


def _sandbox_trace(args: Any) -> int:
    """最近沙箱裁决 (从审计/总线回读, 第 37 个独特功能)。

    若沙箱接入了 SecurityAuditor (内存缓冲) 或 SecurityEventBus (持久 JSONL),
    这里回读最近 N 条 DENY/ISOLATE 裁决, 形成「沙箱拦截史」—— 回答
    「这段时间沙箱拦了什么」, 是审计闭环的可观测面。
    """
    json_mode = bool(getattr(args, "json", False))
    limit = int(getattr(args, "limit", 20) or 20)

    records: List[Dict[str, Any]] = []
    # 优先持久总线 (~/.tuan/security-audit.jsonl)
    try:
        from ..core.security_bus import get_security_bus

        bus = get_security_bus()
        events = bus.get_events(limit=limit)
        for ev in events:
            payload = ev.to_dict().get("payload", {}) or {}
            records.append({
                "ts": ev.timestamp,
                "type": ev.event_type,
                "source": getattr(ev, "source", "sandbox") or "sandbox",
                "severity": ev.severity,
                "command": (payload.get("command", "") or "")[:120],
                "layer": payload.get("layer", ""),
                "reason": payload.get("reason", ""),
            })
    except Exception as exc:  # noqa: BLE001 - 总线不可用回退审计
        log.debug("安全路径 fallback 降级: %s", exc)
        try:
            from ..core.security_auditor import SecurityAuditor

            auditor = SecurityAuditor(home=home_dir())
            for rec in auditor.recent_alerts(limit):
                records.append({
                    "ts": rec.get("timestamp", 0),
                    "type": rec.get("module", "sandbox"),
                    "source": rec.get("module", "sandbox"),
                    "severity": rec.get("severity", "?"),
                    "command": (rec.get("input_summary", "") or "")[:120],
                    "layer": (rec.get("context", {}) or {}).get("layer", ""),
                    "reason": (rec.get("reasons") or [""])[0] if rec.get("reasons") else "",
                })
        except Exception as exc:  # noqa: BLE001
            log.debug("安全路径 fallback 降级: %s", exc)
            console.print(f"[red]读取沙箱裁决历史失败: {exc}[/red]")
            return 1

    if json_mode:
        sys.stdout.write(json.dumps({
            "records": records,
            "count": len(records),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 最近沙箱裁决 ===[/bold]\n")
    if not records:
        console.print("[dim]暂无沙箱裁决记录 (运行 tuan sandbox assess 产生, 或开启审计后跑会话)[/dim]")
        return 0
    sev_color = {"info": "dim", "low": "cyan", "medium": "yellow",
                 "high": "orange", "critical": "red"}
    for r in records:
        ts = r.get("ts", 0)
        try:
            import time as _t
            tstr = _t.strftime("%m-%d %H:%M", _t.localtime(ts)) if ts else "-"
        except (TypeError, ValueError, OSError):
            tstr = "-"
        sev = r.get("severity", "?")
        color = sev_color.get(sev, "dim")
        console.print(f"  {tstr}  [{color}]{sev:<8}[/{color}] "
                      f"{r.get('type', '?')}  {r.get('command', '')}")
        if r.get("reason"):
            console.print(f"      [dim]{r['reason'][:80]}[/dim]")

    console.print("\n[dim]说明: 记录来自 SecurityEventBus (持久) 或 SecurityAuditor (内存); "
                  "sandbox assess 主动触发裁决[/dim]")
    return 0
