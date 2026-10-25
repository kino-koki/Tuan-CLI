"""代理探测: 扫 PATH 找出本机装了哪几家代理。

对应协议 hello.agents[] 字段。每次 WebSocket 连接时重新探测 (不缓存),
保证用户在手机端看到的状态是实时的。

设计要点:
- 全部 5 家并行探测 (asyncio.gather), 总耗时 ≈ 单家耗时 (约 3s 上限)。
- 探测失败 (命令不存在 / --version 失败) 不影响其他代理, 各自返回 AgentInfo。
- 结果顺序按 ADAPTERS 注册顺序固定, 便于手机端稳定渲染。
"""
from __future__ import annotations

import asyncio
from typing import List

from .adapters import ADAPTERS, register_adapter
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodeXAdapter
from .adapters.deepseek_harness import DeepSeekHarnessAdapter
from .adapters.hermes import HermesAdapter
from .adapters.kimi_code import KimiCodeAdapter
from .base import AgentAdapter, AgentInfo

# 注册全部 5 家适配器 (固定顺序, 与协议文档一致)
for _cls in (ClaudeCodeAdapter, CodeXAdapter, HermesAdapter, DeepSeekHarnessAdapter, KimiCodeAdapter):
    _inst = _cls()
    register_adapter(_inst)

# 探测顺序 (固定, 便于 UI 稳定)
DETECTION_ORDER = [
    "claude-code",
    "codex",
    "hermes",
    "deepseek-harness",
    "kimi-code",
]


async def discover_agents() -> List[AgentInfo]:
    """并行探测所有代理, 返回 AgentInfo 列表 (按 DETECTION_ORDER 排序)。"""
    tasks = []
    for adapter_id in DETECTION_ORDER:
        adapter = ADAPTERS.get(adapter_id)
        if adapter is not None:
            tasks.append(adapter.detect())
    infos = await asyncio.gather(*tasks, return_exceptions=True)
    result: List[AgentInfo] = []
    for i, info in enumerate(infos):
        if isinstance(info, AgentInfo):
            result.append(info)
        else:
            # 探测异常: 返回不健康的 AgentInfo
            adapter = ADAPTERS.get(DETECTION_ORDER[i])
            if adapter is not None:
                result.append(AgentInfo(
                    id=adapter.id,
                    name=adapter.display_name,
                    healthy=False,
                    reason=f"probe error: {info}",
                ))
    return result
