"""Agent 路由器: 任务 → 代理。

两种模式:
- 显式指定 (task.agent != "auto"): 直接用, 未安装/不健康返回错误。
- 自动 (task.agent == "auto"): 按 mode 打分 + 健康度 + 优先级排序。

打分规则 (mode -> weight):
- 每家适配器自带 weights 字典 (mode -> score)。
- 未匹配的 mode 默认给 1 分。
- 健康度: healthy=False 的代理直接跳过 (不参与打分)。
- 同分按注册顺序 (claude-code > deepseek-harness > codex > kimi-code > hermes) 排序。
"""
from __future__ import annotations

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

    # 自动模式: 打分
    candidates = []
    for adapter_id in REGISTRATION_PRIORITY:
        adapter = ADAPTERS.get(adapter_id)
        if adapter is None:
            continue
        info = await adapter.detect()
        if not info.healthy:
            continue
        score = adapter.weights.get(task.mode, 1)
        candidates.append((adapter_id, adapter, score))

    if not candidates:
        return None, "NO_AGENT_AVAILABLE: 本机未安装任何可用代理"

    # 按分数降序 + 注册顺序升序排序
    candidates.sort(key=lambda x: (-x[2], REGISTRATION_PRIORITY.index(x[0])))
    return candidates[0][1], None
