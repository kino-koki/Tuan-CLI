"""Super-Agent —— DeepSeek Super-agent 架构在 Tuan-CLI 的落地实现。

对标 DeepSeek《Super-agent 设计探索: 迈向更自主的 Agent 系统》(2026-10-31)
的四项基础特征与五大组成模块:

四项基础特征:
- 连续: 同一 Agent 可在 IM / GitHub / 本地文件等不同渠道连续交互;
- 高效: 并行处理多个复杂任务 (Router 分派 + 多 Worker 隔离并发);
- 主动: 持续观察环境事件, 自行推进值得处理的事项 (两级过滤 + 投机执行);
- 持久: 始终在线, 长期运行中能从异常状态恢复 (Watchdog + 状态持久化)。

五大组成模块:
- 双层架构: Router 层 (承接交互/维护全局上下文/分派) + Worker 层 (隔离并发执行);
- 事件驱动: Trigger → 程序规则过滤 → 模型研判 → 分派; 已关联事件经
  Subscription 直达 Worker, 不重复经过 Router;
- 面向人的交互: 异步 ReAct Loop (start/stop), 投机执行, 结构化提问,
  面板优先展示待回答/待审阅/受阻;
- 计算与状态及环境分离: 状态落盘, 执行环境可指向本地 daemon (BYOM);
- Watchdog: 独立巡检会话, 监控进展与方向, 异常时介入修复。

对外暴露:
- SuperAgent / Router / Worker / Watchdog / EventBus: 核心类
- Trigger / Thread / Ticket / Subscription: 领域对象
- EventSource: 事件源基类 (IM / GitHub / 文件监视可继承)
"""

from __future__ import annotations

from .models import (
    EventSource,
    EventStatus,
    Ticket,
    TicketStatus,
    Trigger,
    TriggerKind,
    TriggerSource,
    Subscription,
    Thread,
    WorkMode,
)
from .engine import SuperAgent
from .store import StateStore
from .router import Router
from .worker import Worker, WorkerPool
from .watchdog import Watchdog
from .events import EventBus, ProgramRule
from .panel import Panel, PanelItem

__all__ = [
    # 核心
    "SuperAgent",
    "StateStore",
    "Router",
    "Worker",
    "WorkerPool",
    "Watchdog",
    "EventBus",
    "ProgramRule",
    "Panel",
    "PanelItem",
    # 领域对象
    "Trigger",
    "TriggerKind",
    "TriggerSource",
    "Thread",
    "Ticket",
    "TicketStatus",
    "Subscription",
    "WorkMode",
    "EventSource",
    "EventStatus",
]
