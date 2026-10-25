"""5 家本地代理适配器。

每家一个文件, 继承 AgentAdapter, 提供:
- id / display_name / command (类属性)
- build_command() 覆盖 (每家 CLI 的调用方式不同)
- weights 打分权重 (用于 router auto 模式排序)

协议对齐: EventType / AgentEvent / TaskRequest 由 base 提供。
"""
from __future__ import annotations

from typing import Dict

from ..base import AgentAdapter

ADAPTERS: Dict[str, AgentAdapter] = {}


def register_adapter(adapter: AgentAdapter) -> None:
    """注册适配器实例到全局表。"""
    ADAPTERS[adapter.id] = adapter


def get_adapter(adapter_id: str) -> AgentAdapter | None:
    """按 id 取适配器, 不存在返回 None。"""
    return ADAPTERS.get(adapter_id)
