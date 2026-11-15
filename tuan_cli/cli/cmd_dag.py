"""`tuan dag` —— 任务依赖图 (DAG) 可观测性 (第 46 个独特功能)。

Claude Code 是单 Agent 串行, 没有「多 Agent 依赖调度」概念。Tuan-CLI 的
TaskDAG (core/task_dag.py) 用有向无环图表示任务依赖, 支持关键路径分析、
波次调度、失败重试、死锁检测。本命令把这份 DAG 智能调度暴露为可查询视图:

    tuan dag demo                       # 内置示例 DAG (演示关键路径/波次/环)
    tuan dag plan <file.json>           # 从任务计划文件加载并分析
    tuan dag plan <file.json> --break   # 分析并自动打破循环依赖
    tuan dag check <file.json>          # 仅环检测 (CI 门禁用)
    tuan dag plan <file.json> --json    # 机器可读

任务计划文件格式 (JSON 数组):
    [{"id": "T1", "title": "分析需求", "prompt": "...", "depends_on": ""},
     {"id": "T2", "title": "实现功能", "prompt": "...", "depends_on": "T1", "role": "implementer"}]

差异化价值:
- DAG 透明化: 用户能看到关键路径 (最长依赖链 = 最短完成时间) 和波次 (可并行
  执行的任务), 而非黑盒调度。
- 死锁检测: check 子命令用环检测做 CI 门禁, 防止任务计划里的循环依赖。
- 跨进程可复现: 从 plan 文件加载, 同一计划在任何进程产生同一分析。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..ui.plain_console import console


def _demo_tasks() -> List[Dict[str, str]]:
    """内置示例任务计划 (依赖链 + 并行分支 + 关键路径)。"""
    return [
        {"id": "T1", "title": "分析需求", "prompt": "分析需求", "role": "architect"},
        {"id": "T2", "title": "设计架构", "prompt": "设计架构", "depends_on": "T1", "role": "architect"},
        {"id": "T3", "title": "实现API", "prompt": "实现API", "depends_on": "T2", "role": "implementer"},
        {"id": "T4", "title": "实现UI", "prompt": "实现UI", "depends_on": "T2", "role": "implementer"},
        {"id": "T5", "title": "写测试", "prompt": "写测试", "depends_on": "T3;T4", "role": "tester"},
        {"id": "T6", "title": "代码审查", "prompt": "代码审查", "depends_on": "T5", "role": "reviewer"},
    ]


def _load_plan(path: str) -> List[Dict[str, str]]:
    """从 JSON 文件加载任务计划; 支持 --json 内联或 @file 路径。"""
    src = path.strip()
    if src.startswith("@"):
        src = src[1:]
    p = Path(src)
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        # 尝试当作内联 JSON 字符串
        try:
            raw = json.loads(src)
        except Exception:  # noqa: BLE001
            raise ValueError(f"无法解析任务计划: {path!r} (不是文件也不是合法 JSON)") from None
    if not isinstance(raw, list):
        raise ValueError("任务计划必须是 JSON 数组")
    out: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"任务项必须是对象, 得到: {type(item).__name__}")
        out.append({
            "id": str(item.get("id", "")),
            "title": str(item.get("title", "")),
            "prompt": str(item.get("prompt", "")),
            "depends_on": str(item.get("depends_on", "") or ""),
            "role": str(item.get("role", "implementer")),
        })
    return out


def _render_plan(dag: Any, tasks: List[Dict[str, str]], json_mode: bool,
                 break_cycles: bool = False) -> int:
    """渲染 DAG 分析: 状态摘要 + 关键路径 + 波次 + 环。"""
    if json_mode:
        summary = dag.get_status_summary()
        path = dag.critical_path()
        cycles = dag.detect_cycles()
        # 波次模拟: 依次完成可执行波次 (用克隆图, 不破坏原图)
        sim_dag = _clone_dag(dag)
        waves: List[List[str]] = []
        while True:
            wave = [n.task_id for n in sim_dag.get_wave(5)]
            if not wave:
                break
            waves.append(wave)
            for tid in wave:
                sim_dag.mark_completed(tid, "sim")
        sys.stdout.write(json.dumps({
            "tasks": tasks,
            "summary": summary,
            "critical_path": path,
            "waves": waves,
            "cycles": cycles,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    summary = dag.get_status_summary()
    path = dag.critical_path()
    cycles = dag.detect_cycles()

    console.print("[bold]任务 DAG 分析[/bold]")
    console.print(f"  节点: {summary['total']}  状态: "
                  f"{summary['by_status'] or '(全部 pending)'}")

    # 关键路径
    if path:
        console.print(f"\n[bold]关键路径[/bold] (最长依赖链 = 最短完成时间):")
        console.print("  " + " → ".join(path))

    # 波次
    sim_dag = _clone_dag(dag)
    sim_waves: List[List[str]] = []
    while True:
        wave = [n.task_id for n in sim_dag.get_wave(5)]
        if not wave:
            break
        sim_waves.append(wave)
        for tid in wave:
            sim_dag.mark_completed(tid, "sim")
    if sim_waves:
        console.print(f"\n[bold]调度波次[/bold] ({len(sim_waves)} 波, 并发≤5):")
        for i, w in enumerate(sim_waves, 1):
            titles = {n.task_id: n.title for n in dag.get_all_nodes()}
            label = ", ".join(f"{t}({titles.get(t, '')})" for t in w)
            console.print(f"  波{i}: {label}")

    # 环检测
    if cycles:
        console.print(f"\n[red]循环依赖 {len(cycles)} 处:[/red]")
        for c in cycles:
            console.print(f"  [red]{' → '.join(c)}[/red]")
        if break_cycles:
            n = dag.break_cycles()
            console.print(f"  [green]已自动打破 {n} 处循环依赖[/green]")
    else:
        console.print("\n[green]无循环依赖 (DAG 合法)[/green]")

    console.print("\n提示: tuan dag plan <file.json> --json 输出结构化; "
                  "tuan dag check <file.json> 做 CI 门禁")
    return 0


def _clone_dag(dag: Any) -> Any:
    """克隆一个 TaskDAG (深拷贝节点, 不共享状态)。"""
    from ..core.task_dag import TaskDAG
    new = TaskDAG()
    for node in dag.get_all_nodes():
        new.add_node(
            task_id=node.task_id,
            title=node.title,
            prompt=node.prompt,
            role=node.role,
            priority=node.priority,
            max_retries=node.max_retries,
        )
        new._nodes[node.task_id].metadata = dict(node.metadata)
    for node in dag.get_all_nodes():
        for dep in node.dependencies:
            if dep in new._nodes:
                new.add_dependency(node.task_id, dep)
    return new


def _build_dag_no_break(tasks: List[Dict[str, str]]) -> Any:
    """构建 DAG, 不自动打破循环 (用于 check 门禁检测原始计划里的环)。

    与 TaskDAG.from_plan 不同, 保留原始依赖边, 让 detect_cycles 能真正
    看到用户计划里的循环依赖 (CI 门禁用)。
    """
    from ..core.task_dag import TaskDAG

    dag = TaskDAG()
    for t in tasks:
        dag.add_node(
            task_id=t.get("id", ""),
            title=t.get("title", ""),
            prompt=t.get("prompt", ""),
            role=t.get("role", "implementer"),
        )
    for t in tasks:
        tid = t.get("id", "")
        deps = t.get("depends_on", "")
        if deps:
            for d in deps.replace(";", ",").split(","):
                d = d.strip()
                if d:
                    dag.add_dependency(tid, d)
    return dag


def _cmd_dag_plan(args: Any, json_mode: bool) -> int:
    """dag plan: 从任务计划文件加载并分析。"""
    from ..core.task_dag import TaskDAG

    plan_path = getattr(args, "plan", None) or ""
    break_cycles = bool(getattr(args, "break", False))
    try:
        tasks = _load_plan(plan_path)
    except ValueError as exc:
        console.print(f"[red]任务计划错误: {exc}[/red]")
        return 1
    if not tasks:
        console.print("[dim]任务计划为空[/dim]")
        return 0
    dag = TaskDAG.from_plan(tasks)
    return _render_plan(dag, tasks, json_mode, break_cycles)


def _cmd_dag_check(args: Any, json_mode: bool) -> int:
    """dag check: 仅环检测 (CI 门禁)。不自动打破, 检测原始计划里的环。"""
    plan_path = getattr(args, "plan", None) or ""
    try:
        tasks = _load_plan(plan_path)
    except ValueError as exc:
        console.print(f"[red]任务计划错误: {exc}[/red]")
        return 1
    dag = _build_dag_no_break(tasks)
    cycles = dag.detect_cycles()
    if json_mode:
        sys.stdout.write(json.dumps({
            "ok": not cycles,
            "cycles": cycles,
            "task_count": len(tasks),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0 if not cycles else 1
    if cycles:
        console.print(f"[red]检测到 {len(cycles)} 处循环依赖:[/red]")
        for c in cycles:
            console.print(f"  [red]{' → '.join(c)}[/red]")
        return 1
    console.print(f"[green]无循环依赖[/green] ({len(tasks)} 个任务, DAG 合法)")
    return 0


def _cmd_dag_demo(args: Any, json_mode: bool) -> int:
    """dag demo: 内置示例 DAG 演示。"""
    from ..core.task_dag import TaskDAG

    tasks = _demo_tasks()
    dag = TaskDAG.from_plan(tasks)
    console.print("[dim]内置示例 DAG (演示关键路径/波次/环检测)[/dim]")
    return _render_plan(dag, tasks, json_mode)


def cmd_dag(args: Any) -> int:
    """`tuan dag` 入口: 任务依赖图可观测性。"""
    sub = getattr(args, "dag_cmd", None) or "demo"
    json_mode = bool(getattr(args, "json", False))

    if sub == "plan":
        return _cmd_dag_plan(args, json_mode)
    if sub == "check":
        return _cmd_dag_check(args, json_mode)
    # 默认 demo
    return _cmd_dag_demo(args, json_mode)


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_dag", ".cmd_dag")
