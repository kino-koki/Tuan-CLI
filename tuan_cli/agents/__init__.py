"""Agent-of-Agents 调度层 (v0.3.2 新增)。

手机 Tuan-Chat Native ⇄ 桌面 Tuan-Chat ⇄ 5 家本地代理 (Claude Code / CodeX /
hermes / DeepSeek Harness / Kimi Code) 的核心路由与适配层。

对外暴露:
- AgentAdapter / AgentEvent / EventType / TaskRequest / AgentInfo: 基类与模型
- route: 任务 → 代理 路由器函数
- route_explain: 带打分明细的路由解释 (status/route 命令用)
- discover_agents: 探测本机安装了哪些代理
- probe_agent / summarize: 单点探测与一行摘要 (启动清单 / 状态栏用)
- ADAPTERS: 适配器注册表 (id → 实例)
"""
from __future__ import annotations

from .base import (
    AgentAdapter,
    AgentEvent,
    AgentInfo,
    EventType,
    TaskRequest,
)
from .discovery import DETECTION_ORDER, discover_agents, probe_agent, summarize
from .router import route, route_explain
from .adapters import ADAPTERS, get_adapter, register_adapter

__all__ = [
    "AgentAdapter",
    "AgentEvent",
    "AgentInfo",
    "EventType",
    "TaskRequest",
    "route",
    "route_explain",
    "discover_agents",
    "probe_agent",
    "summarize",
    "DETECTION_ORDER",
    "ADAPTERS",
    "get_adapter",
    "register_adapter",
]
