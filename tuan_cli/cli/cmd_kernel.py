"""kernel 命令 —— 内核/服务容器可观测性 (第 82 个独特功能)。

暴露 :mod:`tuan_cli.core.kernel` 的 Kernel 内部运行真相:
- **事件总线历史**: 内核已发出的全部 KernelEvent (seq/ts/type/payload);
- **服务归属**: 每个服务由谁注册 (owner), 多贡献者叠加顺序;
- **中间件**: 事件总线上已注册的中间件名称清单。

差异化价值: Claude Code 的内核事件总线 / 服务容器 / 中间件管线是黑箱,
用户无法知道「内核到底发了哪些事件」「哪个插件提供了某服务」「哪些
中间件在拦截事件」。本命令把这些内部运行真相暴露为可查询, 纯只读。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ._ui_singleton import console
from .parser import _register_command

import logging
log = logging.getLogger(__name__)


def _get_kernel() -> Any:
    """取内核实例 (纯只读查询, 不激活插件、不触发副作用)。

    优先用 build_kernel 构造真实内核 (含已注册插件/服务), 失败则回退
    空内核 —— 仅查询容器/总线结构, 不执行任何编排。
    """
    try:
        from ..app import build_kernel
        return build_kernel(bare=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("_get_kernel(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass
    from ..core.kernel import Kernel
    return Kernel()


def _cmd_kernel_events(args: Any, json_mode: bool) -> int:
    kernel = _get_kernel()
    events: List[Dict[str, Any]] = []
    for ev in kernel.events:
        events.append({
            "seq": getattr(ev, "seq", None),
            "ts": getattr(ev, "ts", None),
            "type": getattr(ev, "type", ""),
            "payload": getattr(ev, "payload", {}),
        })
    limit = int(getattr(args, "limit", 0) or 0)
    if limit > 0:
        events = events[-limit:]
    # 按类型统计
    by_type: Dict[str, int] = {}
    for ev in events:
        by_type[ev["type"]] = by_type.get(ev["type"], 0) + 1
    if json_mode:
        print(json.dumps({
            "total": len(events),
            "by_type": by_type,
            "events": events,
        }, ensure_ascii=False, indent=2))
        return 0
    if not events:
        console.print("[green]✓ 内核无事件[/green]")
        return 0
    console.print(f"[bold]内核事件总线 ({len(events)} 条)[/bold]\n")
    for ev in events[-limit if limit else 20:]:
        ts = ev.get("ts")
        ts_s = f"{ts:.2f}" if isinstance(ts, (int, float)) else str(ts)
        console.print(f"  [dim]#{ev.get('seq')}[/dim] [cyan]{ts_s}[/cyan] "
                      f"[green]{ev.get('type')}[/green]")
    if by_type:
        console.print("\n[dim]按类型: " + ", ".join(
            f"{k}={v}" for k, v in sorted(by_type.items(), key=lambda x: -x[1])) + "[/dim]")
    return 0


def _cmd_kernel_services(args: Any, json_mode: bool) -> int:
    kernel = _get_kernel()
    container = getattr(kernel, "services", None)
    if container is None:
        console.print("[red]内核无服务容器[/red]")
        return 1
    owners: Dict[str, str] = dict(getattr(container, "service_owners", {}))
    svcs: List[str] = list(getattr(container, "services", []))
    rows: List[Dict[str, Any]] = []
    for s in svcs:
        contribs = []
        try:
            contribs = list(container.contributions(s))
        except Exception:  # noqa: BLE001
            contribs = []
        rows.append({
            "service": s,
            "owner": owners.get(s, ""),
            "contributors": len(contribs),
            "contributions": [{"owner": c[0], "placement": c[1]} for c in contribs],
        })
    only = str(getattr(args, "service", "") or "").strip()
    if only:
        rows = [r for r in rows if r["service"] == only]
    if json_mode:
        print(json.dumps({"count": len(rows), "services": rows},
                         ensure_ascii=False, indent=2))
        return 0
    if not rows:
        console.print("[green]✓ 内核无服务[/green]")
        return 0
    console.print(f"[bold]内核服务容器 ({len(rows)} 个服务)[/bold]\n")
    for r in rows:
        contrib_tag = f" ({r['contributors']} 贡献)" if r["contributors"] > 1 else ""
        console.print(f"  [green]{r['service']:<30s}[/green] "
                      f"owner=[cyan]{r['owner'] or '(内建)'}[/cyan]{contrib_tag}")
    console.print("\n[dim]详情: tuan kernel services <name>[/dim]")
    return 0


def _cmd_kernel_middleware(args: Any, json_mode: bool) -> int:
    kernel = _get_kernel()
    bus = getattr(kernel, "bus", None)
    if bus is None:
        console.print("[red]内核无事件总线[/red]")
        return 1
    names: List[str] = list(getattr(bus, "middleware_names", []))
    if json_mode:
        print(json.dumps({"count": len(names), "middleware": names},
                         ensure_ascii=False, indent=2))
        return 0
    if not names:
        console.print("[green]✓ 内核无中间件[/green]")
        return 0
    console.print(f"[bold]内核中间件管线 ({len(names)} 个)[/bold]\n")
    for i, n in enumerate(names, 1):
        console.print(f"  [green]{i:>2}.[/green] {n}")
    console.print("\n[dim]说明: 中间件按注册顺序拦截/修改事件, 按名称排序执行[/dim]")
    return 0


def cmd_kernel(args: Any) -> int:
    """kernel 主入口: 分发到子命令 (纯只读内核可观测)。"""
    sub = getattr(args, "kernel_cmd", None) or "events"
    json_mode = bool(getattr(args, "json", False))
    if sub == "events":
        return _cmd_kernel_events(args, json_mode)
    if sub == "services":
        return _cmd_kernel_services(args, json_mode)
    if sub == "middleware":
        return _cmd_kernel_middleware(args, json_mode)
    console.print(f"[red]未知 kernel 子命令: {sub}[/red]")
    return 1


_register_command("cmd_kernel", ".cmd_kernel")
