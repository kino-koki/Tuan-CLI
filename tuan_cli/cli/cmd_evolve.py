"""evolve 命令 —— 反思性自我进化闭环 (阶段 A 命令面)。

暴露 :mod:`tuan_cli.self_improve.evolution_loop` 的反思性自我改进能力:
- **run**: 对一组任务运行一轮进化迭代 (候选生成 + 回归验证 + 接受/回滚 + 落账);
- **report**: 渲染进化账本摘要 (接受率 / 净改进 / 历史)。

差异化价值: 大多数 Agent 框架的 self-improve 只有"蒸馏技能" (面向用户知识),
没有对**自身行为**做"执行→自评→改进→回归验证"的真闭环。本命令把
EvolutionLoop 开放为可审计的 CLI 面 (账本 append-only, 可回放)。

  tuan evolve run --tasks "T1;T2" [--ledger PATH] [--json]
  tuan evolve report [--ledger PATH] [--json]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_ledger(raw: Optional[str]) -> str:
    if raw:
        return str(Path(raw).expanduser().resolve())
    home = Path.home()
    return str(home / ".tuan" / "evolution.jsonl")


def _split_tasks(raw: str) -> List[str]:
    return [t.strip() for t in raw.split(";") if t.strip()]


def cmd_evolve(args: Any) -> int:
    """evolve 主入口: 反思性自我进化。"""
    sub = getattr(args, "evolve_cmd", None) or "report"
    json_mode = bool(getattr(args, "json", False))
    ledger_path = _resolve_ledger(getattr(args, "ledger", None))

    if sub == "run":
        tasks_raw = getattr(args, "tasks", "") or ""
        tasks = _split_tasks(tasks_raw)
        if not tasks:
            console.print("[red]✗ 需要 --tasks 指定至少一个任务[/red] "
                          "(用分号分隔, 如 --tasks \"T1;T2\")")
            return 2
        # 从 CLI 触发真实进化需要任务执行器; 这里提供最小可运行的骨架:
        # 通过 _build_runner 允许外部注入 (默认用空产物, 用于验证闭环可跑)。
        runner = _build_runner()
        from ..self_improve.evolution_loop import EvolutionLoop

        loop = EvolutionLoop(run_task=runner, tasks=tasks, ledger_path=ledger_path)
        records = loop.iterate(lambda experiences: [])
        if json_mode:
            print(json.dumps({
                "ledger": ledger_path,
                "tasks": tasks,
                "records": [r.to_dict() for r in records],
            }, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]进化迭代完成 · {len(records)} 候选[/bold] "
                      f"[dim]{ledger_path}[/dim]")
        for r in records:
            mark = "[green]✓ 接受[/green]" if r.accepted else "[red]✗ 拒绝[/red]"
            console.print(f"  {mark} {r.summary[:48]} "
                          f"[dim]Δ{r.delta:+.1f}[/dim]")
        return 0

    # 默认 report
    from ..self_improve.evolution_loop import EvolutionLedger

    ledger = EvolutionLedger(ledger_path)
    entries = ledger.load()
    if json_mode:
        print(json.dumps({"ledger": ledger_path, "records": entries},
                         ensure_ascii=False, indent=2))
        return 0
    if not entries:
        console.print("[dim](进化账本为空, 尚未运行任何迭代)[/dim]")
        console.print("[dim]运行: tuan evolve run --tasks \"T1;T2\"[/dim]")
        return 0
    accepted = [r for r in entries if r.get("accepted")]
    deltas = [r.get("delta", 0.0) for r in accepted]
    avg = sum(deltas) / len(deltas) if deltas else 0.0
    console.print(f"[bold]进化摘要[/bold] · 共 {len(entries)} 次迭代 · "
                  f"接受 {len(accepted)} 次 · "
                  f"接受率 {len(accepted)/len(entries)*100:.0f}%")
    console.print(f"[dim]平均净改进: {avg:+.2f} 分[/dim]\n")
    for rec in entries:
        mark = "[green]✓[/green]" if rec.get("accepted") else "[red]✗[/red]"
        console.print(f"  {mark} {rec.get('summary', rec.get('candidate_id', ''))[:40]} "
                      f"[dim]Δ{rec.get('delta', 0.0):+.1f} "
                      f"· {rec.get('reason', '')[:36]}[/dim]")
    console.print(f"\n[dim]账本: {ledger_path}[/dim]")
    return 0


def _build_runner() -> Callable[[str], dict]:
    """构建默认任务执行器。

    在纯 CLI 骨架中, 默认产物为空 (ok=False), 用于验证闭环可跑通;
    真实进化需在宿主集成点注入任务执行器 (与任务编排层对接)。
    """
    def runner(task_id: str) -> dict:
        return {"ok": False, "error": f"no-op runner for task {task_id}",
                "tests_run": 0, "tests_passed": 0}
    return runner


_register_command("cmd_evolve", ".cmd_evolve")
