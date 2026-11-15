"""``tuan teamlead`` —— 专家团编排器 CLI 入口 (v0.4.2)。

调用本机已安装的外部 CLI Agent (Claude Code / Codex / Hermes / DeepSeek /
Kimi Code) 组成专家开发团 (架构师/实现者/审查者/测试者), 并行派发一个开发目标,
聚合各角色输出。区别于 ``tuan team`` (团组成员/授权管理) 与进程内 subagents。

子命令:
  status   探测本机装了哪几家外部 agent (不执行任务)
  plan     显示 角色 -> agent 的分配计划 (不执行)
  run      组团并并行执行一个开发目标 (需要 PATH 命中至少一家)
"""

from __future__ import annotations

import asyncio
from typing import Any

from ._ui_singleton import console
from .parser import _register_command


def _run_async(coro: Any) -> Any:
    """在 CLI 里跑一个协程 (新建 loop, 避免与既有 loop 冲突)。"""
    return asyncio.new_event_loop().run_until_complete(coro)


def _cmd_status(args: Any) -> int:
    """探测本机已装的外部 agent。"""
    from ..agents.discovery import summarize
    from ..core.team_lead import make_team_lead

    lead = make_team_lead()
    infos = _run_async(lead.discover())
    s = summarize(infos)

    if args.json:
        import json
        console.print_json(json.dumps({
            "summary": s,
            "agents": [i.to_dict() for i in infos],
        }))
        return 0 if s["online"] > 0 else 1

    console.print(f"[bold]本机外部 Agent[/bold] ({s['line']}, {s['verified']} 校验通过)")
    for i in infos:
        mark = "[green]●[/green]" if i.healthy else "[dim]○[/dim]"
        ver = f" v{i.version}" if i.version else ""
        reason = f" ({i.reason})" if (i.reason and not i.healthy) else ""
        console.print(f"  {mark} {i.name} [{i.id}]{ver}{reason}")
    if s["online"] == 0:
        console.print("\n[yellow]未检测到任何外部 agent。请安装 claude / codex /"
                      " hermes / dsh / kimi-code 之一。[/yellow]")
        return 1
    return 0


def _cmd_plan(args: Any) -> int:
    """显示角色 -> agent 的分配计划。"""
    from ..core.team_lead import make_team_lead

    lead = make_team_lead()
    _run_async(lead.discover())
    plan = lead.plan()

    if args.json:
        import json
        console.print_json(json.dumps(plan))
        return 0

    console.print("[bold]专家团分配计划[/bold]")
    for r in lead.roles:
        agent = plan.get(r.key)
        shown = f"[green]{agent}[/green]" if agent else "[yellow]缺位[/yellow]"
        console.print(f"  [bold]{r.title}[/bold] ({r.key}) -> {shown}")
        console.print(f"    偏好: {', '.join(r.preferred) or '-'}")
    return 0


def _cmd_run(args: Any) -> int:
    """组团并并行执行开发目标 (结果进团组审计链, 若团组已创建)。"""
    from ..core.team_group import load_team_group
    from ..core.team_lead import make_audited_team_lead

    roles = args.roles.split(",") if args.roles else None
    ws = getattr(args, "workspace", None)
    store = None
    try:
        if ws:
            s = load_team_group(ws)
            if s.group is not None:
                store = s
    except Exception:  # noqa: BLE001
        store = None  # 无团组则纯 TeamLead (不写审计)
    lead = make_audited_team_lead(store, cwd=ws, timeout_sec=args.timeout)
    # 先探测 + 状态预览
    _run_async(lead.discover())
    online = len(lead.healthy_agents())
    if online == 0:
        console.print("[red]本机无可用外部 agent, 无法组团。[/red]")
        return 1

    report = _run_async(lead.run(
        args.goal, extra_context=args.context or "", roles=roles,
        actor=getattr(args, "actor", "") or "",
    ))

    if args.json:
        import json
        console.print_json(json.dumps(report.to_dict()))
        return 0 if report.failed == 0 and report.ok > 0 else 1

    console.print(f"[bold]专家团报告[/bold] goal={args.goal}")
    console.print(f"  在线 agent: {online} | 角色 {report.total} | "
                  f"成功 {report.ok} | 失败 {report.failed} | 缺位 {report.missing}")
    console.print(f"  耗时 {report.duration_ms}ms")
    for r in report.roles:
        color = {"ok": "green", "failed": "red", "missing": "yellow",
                 "empty": "yellow"}.get(r.status, "dim")
        console.print(f"\n  [{color}]●[/{color}] [bold]{r.title}[/bold] "
                      f"({r.role}) via {r.agent_id} — {r.status} ({r.duration_ms}ms)")
        if r.error:
            console.print(f"    [red]{r.error}[/red]")
        if r.text:
            # 每个角色最多展示前 40 行, 避免刷屏
            lines = r.text.splitlines()
            shown = lines[:40]
            for ln in shown:
                console.print(f"    {ln}")
            if len(lines) > 40:
                console.print(f"    [dim]… (共 {len(lines)} 行, 截断)[/dim]")
    ok = report.ok > 0 and report.failed == 0
    return 0 if ok else 1


# ------------------------------------------------------------------ 分发


def cmd_teamlead(args: Any) -> int:
    """teamlead 主入口: 分发到子命令。"""
    sub = getattr(args, "teamlead_cmd", None) or "status"
    dispatch = {
        "status": _cmd_status,
        "plan": _cmd_plan,
        "run": _cmd_run,
    }
    fn = dispatch.get(sub)
    if fn is None:
        console.print(f"[red]未知 teamlead 子命令: {sub}[/red]")
        return 1
    return fn(args)


_register_command("cmd_teamlead", ".cmd_teamlead")
