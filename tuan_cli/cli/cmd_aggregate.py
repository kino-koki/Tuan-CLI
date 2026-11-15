"""`tuan aggregate` —— 多 Agent 结果聚合可观测性 (第 47 个独特功能)。

Claude Code 是单 Agent, 没有「多 Agent 结果聚合」概念 (去重/冲突检测/质量
评估/优先级合并)。Tuan-CLI 的 ResultAggregator (core/result_aggregator.py)
把这些决策记录为 AggregationDecision, 本命令把聚合过程变成可审计视图:

    tuan aggregate run <file.json>    # 从多 Agent 结果加载并聚合
    tuan aggregate demo               # 内置示例 (演示去重/冲突/质量合并)
    tuan aggregate run <file> --json  # 机器可读 (决策/冲突/质量摘要)

结果文件格式 (JSON 数组):
    [{"task_id": "T1", "agent_id": "agent_a", "content": "...", "role": "implementer",
      "quality_score": 0.8, "elapsed": 12.3, "tool_calls": 5}, ...]

差异化价值:
- 聚合透明化: 每个决策 (去重/冲突/质量/优先级) 都可追溯, 而非黑盒合并。
- 冲突审计: conflicts 列出矛盾结果 (冲突阈值内), 供人工复核。
- 跨进程可复现: 从 JSON 加载, 同一批结果产生同一聚合决策。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..ui.plain_console import console


def _load_results(path: str) -> List[Dict[str, Any]]:
    """从 JSON 文件加载多 Agent 结果。"""
    src = path.strip()
    if src.startswith("@"):
        src = src[1:]
    p = Path(src)
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        try:
            raw = json.loads(src)
        except Exception:  # noqa: BLE001
            raise ValueError(f"无法解析结果: {path!r}") from None
    if not isinstance(raw, list):
        raise ValueError("结果必须是 JSON 数组")
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("结果项必须是对象")
        out.append(item)
    return out


def _demo_results() -> List[Dict[str, Any]]:
    """内置示例: 含重复 (相似) 与冲突的结果。"""
    return [
        {"task_id": "T1", "agent_id": "agent_a", "role": "implementer",
         "content": "实现登录 API, 用 JWT 鉴权, 加刷新令牌", "quality_score": 0.9,
         "elapsed": 30.5, "tool_calls": 8},
        {"task_id": "T1", "agent_id": "agent_b", "role": "implementer",
         "content": "实现登录接口, 采用 JWT 认证, 带 refresh token", "quality_score": 0.7,
         "elapsed": 25.0, "tool_calls": 6},
        {"task_id": "T2", "agent_id": "agent_c", "role": "security_auditor",
         "content": "安全审计: 发现登录接口缺少速率限制, 建议加锁", "quality_score": 0.6,
         "elapsed": 15.0, "tool_calls": 3},
    ]


def _cmd_aggregate_run(args: Any, json_mode: bool) -> int:
    """aggregate run: 从多 Agent 结果加载并聚合。"""
    from ..core.result_aggregator import ResultAggregator

    path = getattr(args, "results", None) or ""
    try:
        items = _load_results(path)
    except ValueError as exc:
        console.print(f"[red]结果文件错误: {exc}[/red]")
        return 1
    if not items:
        console.print("[dim]结果为空[/dim]")
        return 0

    agg = ResultAggregator()
    for it in items:
        agg.add_result(
            task_id=str(it.get("task_id", "")),
            agent_id=str(it.get("agent_id", "")),
            content=str(it.get("content", "")),
            role=str(it.get("role", "")),
            quality_score=float(it.get("quality_score", 0.0) or 0.0),
            elapsed=float(it.get("elapsed", 0.0) or 0.0),
            tool_calls=int(it.get("tool_calls", 0) or 0),
            metadata=it.get("metadata") or {},
        )
    result = agg.aggregate()

    if json_mode:
        sys.stdout.write(json.dumps({
            "input_count": len(items),
            "result": result.to_dict(),
            "conflicts": result.conflicts,
            "decisions": [{
                "type": d.decision_type,
                "description": d.description,
                "affected_tasks": d.affected_tasks,
                "details": d.details,
            } for d in result.decisions],
            "merged_content": result.merged_content,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("[bold]多 Agent 结果聚合[/bold]")
    console.print(f"  输入: {len(items)} 个结果  去重后: {len(result.entries)} 个  "
                  f"决策: {len(result.decisions)} 个")
    console.print(f"  质量: {result.quality_summary or '(无)'}")
    if result.conflicts:
        console.print(f"\n[bold][red]冲突 {len(result.conflicts)} 处[/red][/bold]:")
        for c in result.conflicts:
            console.print(f"  [red]{c}[/red]")
    if result.decisions:
        console.print(f"\n[bold]聚合决策 ({len(result.decisions)}):[/bold]")
        for d in result.decisions:
            color = {"dedup": "yellow", "conflict": "red", "priority": "cyan"}.get(
                d.decision_type, "dim")
            console.print(f"  [{color}]{d.decision_type:>10}[/{color}] "
                          f"{d.description}  {d.affected_tasks or ''}")
    console.print("\n[bold]最终合并结果[/bold]:")
    console.print(f"  {result.merged_content[:120]}{'…' if len(result.merged_content) > 120 else ''}")
    console.print("\n提示: tuan aggregate run <file> --json 输出结构化 (CI 消费)")
    return 0


def _cmd_aggregate_demo(args: Any, json_mode: bool) -> int:
    """aggregate demo: 内置示例演示。"""
    from ..core.result_aggregator import ResultAggregator

    items = _demo_results()
    agg = ResultAggregator()
    for it in items:
        agg.add_result(
            task_id=str(it["task_id"]), agent_id=str(it["agent_id"]),
            content=str(it["content"]), role=str(it.get("role", "")),
            quality_score=float(it.get("quality_score", 0.0)),
            elapsed=float(it.get("elapsed", 0.0)), tool_calls=int(it.get("tool_calls", 0)),
        )
    result = agg.aggregate()
    console.print("[dim]内置示例 (演示去重/冲突/质量合并)[/dim]")

    if json_mode:
        sys.stdout.write(json.dumps({
            "input_count": len(items),
            "result": result.to_dict(),
            "conflicts": result.conflicts,
            "decisions": [{
                "type": d.decision_type, "description": d.description,
                "affected_tasks": d.affected_tasks, "details": d.details,
            } for d in result.decisions],
            "merged_content": result.merged_content,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print(f"  输入: {len(items)} 个结果  去重后: {len(result.entries)} 个  "
                  f"决策: {len(result.decisions)} 个")
    console.print(f"  质量: {result.quality_summary or '(无)'}")
    if result.conflicts:
        console.print(f"\n[bold][red]冲突 {len(result.conflicts)} 处[/red][/bold]:")
        for c in result.conflicts:
            console.print(f"  [red]{c}[/red]")
    if result.decisions:
        console.print(f"\n[bold]聚合决策 ({len(result.decisions)}):[/bold]")
        for d in result.decisions:
            color = {"dedup": "yellow", "conflict": "red", "priority": "cyan"}.get(
                d.decision_type, "dim")
            console.print(f"  [{color}]{d.decision_type:>10}[/{color}] "
                          f"{d.description}  {d.affected_tasks or ''}")
    console.print("\n[bold]最终合并结果[/bold]:")
    console.print(f"  {result.merged_content[:120]}{'…' if len(result.merged_content) > 120 else ''}")
    return 0


def cmd_aggregate(args: Any) -> int:
    """`tuan aggregate` 入口: 多 Agent 结果聚合可观测性。"""
    sub = getattr(args, "aggregate_cmd", None) or "demo"
    json_mode = bool(getattr(args, "json", False))

    if sub == "run":
        return _cmd_aggregate_run(args, json_mode)
    # 默认 demo
    return _cmd_aggregate_demo(args, json_mode)


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_aggregate", ".cmd_aggregate")
