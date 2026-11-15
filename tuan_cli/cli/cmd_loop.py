"""loop 命令 —— Loop 系统可观测性 (第 54 个独特功能)。

暴露 :mod:`tuan_cli.core.loop_provider` 的 LoopRegistry:
管理可用的 LoopProvider (react / planner_execute) 并查询当前激活者。

差异化价值: Claude Code 的循环机制黑盒; 本命令让用户查询当前 Agent
跑的是哪个循环 (ReAct / 规划-执行), 查看各循环的说明, 并预览切换配置。
纯只读诊断, 不触发任何循环执行。
"""

from __future__ import annotations

import json
from typing import Any, List

from ._ui_singleton import console
from .parser import _register_command


def _build_registry() -> Any:
    """构建 LoopRegistry, 注册内置 LoopProvider (纯查询用, 不执行循环)。"""
    from ..core.loop_provider import LoopRegistry, PlannerExecuteLoop, ReActLoop

    reg = LoopRegistry()
    reg.register(ReActLoop())
    reg.register(PlannerExecuteLoop())
    return reg


def _cmd_loop_list(args: Any, json_mode: bool) -> int:
    reg = _build_registry()
    loops: List[dict] = reg.list_available()
    current = reg.current_name
    if json_mode:
        print(json.dumps({
            "count": len(loops),
            "current": current,
            "loops": loops,
        }, ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]Loop 系统[/bold] · 当前: [cyan]{current}[/cyan]")
    for l in loops:
        tag = "  ← 当前" if l["name"] == current else ""
        console.print(f"  [green]{l['name']}[/green]  [dim]{l['description']}[/dim]{tag}")
    console.print("\n[dim]切换: tuan config set loop.provider <name> "
                  "(planner_execute = 规划→执行 两阶段)[/dim]")
    return 0


def _cmd_loop_current(args: Any, json_mode: bool) -> int:
    reg = _build_registry()
    current = reg.current_name
    info = {"current": current}
    for l in reg.list_available():
        if l["name"] == current:
            info["description"] = l["description"]
            break
    if json_mode:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    console.print(f"当前 Loop: [cyan]{current}[/cyan]")
    console.print(f"  [dim]{info.get('description', '')}[/dim]")
    return 0


def _cmd_loop_info(args: Any, json_mode: bool) -> int:
    reg = _build_registry()
    name = args.name or reg.current_name
    found = next((l for l in reg.list_available() if l["name"] == name), None)
    if not found:
        console.print(f"[red]未知 Loop: {name}[/red] (可用: "
                      f"{', '.join(l['name'] for l in reg.list_available())})")
        return 1
    if json_mode:
        print(json.dumps({"name": name, **found}, ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]{found['name']}[/bold]")
    console.print(f"  [dim]{found['description']}[/dim]")
    return 0


def _cmd_loop_hooks(args: Any, json_mode: bool) -> int:
    """loop 生命周期钩子 (第 67 个独特功能: 循环行为可配置观测)。

    暴露 LoopRegistry 的 should_nudge / on_task_start / on_task_end:
    - 每个 Loop 提供「任务开始/结束」与「是否应催促进度」三个生命周期钩子,
      这是循环行为可配置的观测面 —— Claude Code 的循环是黑箱, 用户不知道
      何时会因卡住而 nudge (催促), 也不知道任务起止触发哪些回调;
    - 本命令列出每个 Loop 的钩子行为 + 当前注册的 hook 实例, 供编排者
      理解循环的驱动节奏, 配置是否启用进度催促 (should_nudge)。

      tuan loop hooks               # 列出每个 Loop 的生命周期钩子
      tuan loop hooks --name react  # 只看指定 Loop
      tuan loop hooks --json        # 机器可读
    """
    from ..core.loop_provider import LoopRegistry, PlannerExecuteLoop, ReActLoop

    reg = LoopRegistry()
    reg.register(ReActLoop())
    reg.register(PlannerExecuteLoop())
    loops = reg.list_available()

    only = getattr(args, "name", "") or ""
    if only:
        loops = [l for l in loops if l["name"] == only]

    hook_rows = []
    for l in loops:
        provider = _get_provider(reg, l["name"])
        row = {
            "name": l["name"],
            "should_nudge": _safe_nudge(provider),
            "on_task_start": "已注册" if getattr(provider, "on_task_start", None) else "无",
            "on_task_end": "已注册" if getattr(provider, "on_task_end", None) else "无",
        }
        hook_rows.append(row)

    if json_mode:
        print(json.dumps({"hooks": hook_rows}, ensure_ascii=False, indent=2))
        return 0
    if not hook_rows:
        console.print(f"[red]未知 Loop: {only}[/red]")
        return 1
    console.print("[bold]Loop 生命周期钩子[/bold] (循环行为可配置面)")
    for row in hook_rows:
        console.print(f"\n  [green]{row['name']}[/green]")
        console.print(f"    should_nudge (进度催促): [cyan]{row['should_nudge']}[/cyan]")
        console.print(f"    on_task_start: {row['on_task_start']}")
        console.print(f"    on_task_end: {row['on_task_end']}")
    console.print("\n[dim]提示: should_nudge 决定「长时间卡住时是否催促进度」; "
                  "on_task_start/end 是任务起止回调 (可接审计)[/dim]")
    return 0


def _get_provider(reg: Any, name: str) -> Any:
    """从注册表取指定名字的 LoopProvider 实例 (内部辅助)。"""
    loops = getattr(reg, "_loops", {}) or {}
    if name in loops:
        return loops[name]
    # 兜底: 当前激活
    return reg.current_name() and loops.get("react", None)


def _safe_nudge(provider: Any) -> str:
    """安全调用 should_nudge: 用最小 stub agent 避免 None 崩溃。

    should_nudge(agent) 访问 agent.config / agent.turn_count; 纯查询本命令
    不执行循环, 故用轻量 stub 代替真实 Agent, 仅探明「卡住时是否应催促」。
    """
    try:
        from ..config import Config

        class _StubConfig:
            def get(self, key: str, default: Any = None) -> Any:
                return default

        class _StubAgent:
            config = _StubConfig()
            turn_count = 3  # 超过默认 interval 3, 应触发催促

        return "是" if provider.should_nudge(_StubAgent()) else "否"
    except Exception:  # noqa: BLE001
        return "否 (无法探测)"


def _cmd_loop_markers(args: Any, json_mode: bool) -> int:
    """循环「完成标记」可观测面 (第 76 个独特功能: 模型声明完成的标记集合)。

    差异化价值: DevLoop / 后台运行 / 多 Agent 协作等所有自主循环都靠
    `markers.is_done` 判断「模型何时算收尾」—— 模型回复里出现这些标记
    即视为声明完成。Claude Code 的收尾判定是黑箱, 用户无法知道「哪些
    标记算完成」, 也无法预判某段回复会被判定为已结束。本命令把
    DONE_MARKERS 集合与 is_done 判定暴露为可查询/可测试:

      tuan loop markers               # 列出全部完成标记
      tuan loop markers --test "任务完成"  # 用真实回复测试判定
      tuan loop markers --json         # 机器可读
    """
    from ..core.markers import DONE_MARKERS, is_done

    test_text = getattr(args, "test", None)
    if test_text is not None:
        result = is_done(test_text)
        if json_mode:
            print(json.dumps({
                "text": test_text,
                "is_done": result,
                "matched": next((m for m in DONE_MARKERS if m in test_text), None),
            }, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]完成判定 · {test_text[:50]}[/bold]")
        if result:
            matched = next((m for m in DONE_MARKERS if m in test_text), None)
            console.print(f"[green]✓ 判定为已完成[/green]  (命中标记: {matched})")
        else:
            console.print("[yellow]⚠ 判定为未完成[/yellow]  (无完成标记)")
        return 0

    if json_mode:
        print(json.dumps({
            "count": len(DONE_MARKERS),
            "markers": list(DONE_MARKERS),
        }, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]循环完成标记 ({len(DONE_MARKERS)} 个)[/bold]  "
                  "模型回复含任一标记即判定为完成:\n")
    for i, m in enumerate(DONE_MARKERS, 1):
        console.print(f"  [green]{i:>2}.[/green] {m}")
    console.print("\n[dim]测试: tuan loop markers --test \"功能已完成\" "
                  "| 说明: 由 core/markers.py 统一判定, 各循环共用同一语义[/dim]")
    return 0


def cmd_loop(args: Any) -> int:
    """loop 主入口: 分发到子命令。"""
    sub = getattr(args, "loop_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))
    if sub == "list":
        return _cmd_loop_list(args, json_mode)
    if sub == "current":
        return _cmd_loop_current(args, json_mode)
    if sub == "info":
        return _cmd_loop_info(args, json_mode)
    if sub == "hooks":
        return _cmd_loop_hooks(args, json_mode)
    if sub == "markers":
        return _cmd_loop_markers(args, json_mode)
    console.print(f"[red]未知 loop 子命令: {sub}[/red]")
    return 1


_register_command("cmd_loop", ".cmd_loop")
