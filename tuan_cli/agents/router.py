"""Agent 路由器: 任务 → 代理。

两种模式:
- 显式指定 (task.agent != "auto"): 直接用, 未安装/不健康返回错误。
- 自动 (task.agent == "auto"): 按 mode 打分 + 健康度 + 健康分 + 优先级排序。

打分规则 (mode -> weight):
- 每家适配器自带 weights 字典 (mode -> score)。
- 未匹配的 mode 默认给 1 分。
- 健康度: healthy=False 的代理直接跳过 (不参与打分)。
- 同分 (weight) 时按 detect() 的健康分 (score) 降序: 版本校验通过的
  真实安装 (100) 排在「同名可疑」(60) / 「版本未知」(70 之间按分) 之前,
  再同分按注册顺序 (claude-code > deepseek-harness > codex > kimi-code > hermes)。

探测并行: auto 模式对所有适配器 asyncio.gather 并发探测 (detect 为真正
异步实现), 总耗时 ≈ 单家最慢者, 不再是串行累加。
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple

from .adapters import ADAPTERS
from .base import AgentAdapter, TaskRequest


# 注册顺序 (同分时的优先级, 越靠前越优先)
REGISTRATION_PRIORITY = [
    "claude-code",
    "deepseek-harness",
    "codex",
    "kimi-code",
    "hermes",
]


async def route(task: TaskRequest) -> Tuple[Optional[AgentAdapter], Optional[str]]:
    """路由任务到适配器。

    返回 (adapter, error_message):
    - 成功: (adapter, None)
    - 失败: (None, error_message)
    """
    if task.agent and task.agent != "auto":
        # 显式指定
        adapter = ADAPTERS.get(task.agent)
        if adapter is None:
            return None, f"AGENT_NOT_FOUND: {task.agent}"
        info = await adapter.detect()
        if not info.healthy:
            return None, f"AGENT_UNHEALTHY: {task.agent} ({info.reason})"
        return adapter, None

    # 自动模式: 并行探测 + 打分
    adapter_ids = [aid for aid in REGISTRATION_PRIORITY if aid in ADAPTERS]
    infos = await asyncio.gather(
        *(ADAPTERS[aid].detect() for aid in adapter_ids), return_exceptions=True
    )
    candidates = []
    for aid, probe in zip(adapter_ids, infos):
        if isinstance(probe, BaseException):
            continue
        if not probe.healthy:
            continue
        weight = ADAPTERS[aid].weights.get(task.mode, 1)
        candidates.append((aid, ADAPTERS[aid], weight, probe.score))

    if not candidates:
        return None, "NO_AGENT_AVAILABLE: 本机未安装任何可用代理"

    # 排序: mode 权重降序 → 健康分降序 → 注册顺序升序
    candidates.sort(key=lambda x: (-x[2], -x[3], REGISTRATION_PRIORITY.index(x[0])))
    return candidates[0][1], None


async def route_explain(task: TaskRequest) -> dict:
    """路由决策的完整解释 (供 `tuan dispatch route` 打分明细与测试)。

    返回 {"agent": id|None, "error": str|None, "candidates": [...]}:
    candidates 每项含 id / name / weight / score / healthy / reason /
    selected (是否被选中)。
    """
    adapter_ids = [aid for aid in REGISTRATION_PRIORITY if aid in ADAPTERS]
    infos = await asyncio.gather(
        *(ADAPTERS[aid].detect() for aid in adapter_ids), return_exceptions=True
    )
    rows = []
    for aid, info in zip(adapter_ids, infos):
        adapter = ADAPTERS[aid]
        if isinstance(info, BaseException):
            rows.append({
                "id": aid, "name": adapter.display_name, "healthy": False,
                "score": 0, "weight": adapter.weights.get(task.mode, 1),
                "reason": f"probe error: {info}", "selected": False,
            })
            continue
        rows.append({
            "id": aid, "name": adapter.display_name, "healthy": info.healthy,
            "score": info.score, "weight": adapter.weights.get(task.mode, 1),
            "reason": info.reason, "selected": False,
        })

    if task.agent and task.agent != "auto":
        explicit_adapter = ADAPTERS.get(task.agent)
        if explicit_adapter is None:
            return {"agent": None, "error": f"AGENT_NOT_FOUND: {task.agent}", "candidates": rows}
        info = await explicit_adapter.detect()
        if not info.healthy:
            return {
                "agent": None,
                "error": f"AGENT_UNHEALTHY: {task.agent} ({info.reason})",
                "candidates": rows,
            }
        for r in rows:
            if r["id"] == task.agent:
                r["selected"] = True
        return {"agent": task.agent, "error": None, "candidates": rows}

    eligible = [r for r in rows if r["healthy"]]
    if not eligible:
        return {
            "agent": None,
            "error": "NO_AGENT_AVAILABLE: 本机未安装任何可用代理",
            "candidates": rows,
        }
    eligible.sort(key=lambda r: (-r["weight"], -r["score"], adapter_ids.index(r["id"])))
    eligible[0]["selected"] = True
    return {"agent": eligible[0]["id"], "error": None, "candidates": rows}
