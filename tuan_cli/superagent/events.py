"""事件总线 —— 接收 Trigger, 做程序层过滤, 分派给 Router / Worker。

对标 DeepSeek Super-agent 的事件驱动机制:
- 群聊消息、邮件、PR 评论、CI 结果等外部信息称为 Trigger;
- 系统先通过**程序规则**过滤事件 (两级过滤第一级, 快速排除无关消息),
  再交由大模型判断是否需要行动 (第二级, 由 Router 承担);
- 对于已经分配任务的 Thread, 后续事件经 Subscription **直达 Worker**,
  无需每次经过 Router, 从而降低路由负载。

本模块只负责第一级过滤 (程序规则) 与投递路由; 模型研判在 Router。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .models import (
    EventStatus,
    EventSource,
    Trigger,
    TriggerKind,
    TriggerSource,
)

log = logging.getLogger(__name__)


@dataclass
class ProgramRule:
    """一条程序层过滤规则。

    - matches(trigger): 是否命中此规则;
    - action: "allow" (放行给模型研判) | "drop" (直接丢弃, 无关)。
    """

    name: str
    fn: Callable[[Trigger], bool]
    action: str = "allow"
    description: str = ""

    def matches(self, trg: Trigger) -> bool:
        try:
            return bool(self.fn(trg))
        except Exception:  # noqa: BLE001 - 规则异常按不命中处理
            return False


class EventBus:
    """事件总线: 接收 Trigger → 程序层过滤 → 投递到 Router 或直达 Worker。

    线程安全: emit() 可从任意线程 (IM webhook / 文件监视线程) 调用。
    """

    def __init__(self) -> None:
        self._rules: List[ProgramRule] = []
        self._sources: List[EventSource] = []
        self._router: Any = None       # Router (处理未关联事件)
        self._workers: Dict[str, Any] = {}  # worker_id -> Worker (直达)
        self._subscriptions: Dict[str, str] = {}  # thread_id -> worker_id
        self._lock = threading.RLock()
        self._status: Dict[str, EventStatus] = {}
        self._listeners: List[Callable[[Trigger, EventStatus], None]] = []

    # ---------------------------------------------------------- 注册

    def add_rule(self, rule: ProgramRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def add_source(self, source: EventSource) -> None:
        with self._lock:
            source.attach(self._router_agent())
            self._sources.append(source)
            source.start()

    def set_router(self, router: Any) -> None:
        with self._lock:
            self._router = router

    def register_worker(self, worker_id: str, worker: Any) -> None:
        with self._lock:
            self._workers[worker_id] = worker

    def unregister_worker(self, worker_id: str) -> None:
        """注销 Worker (已完成, 不再接收直达事件)。"""
        with self._lock:
            self._workers.pop(worker_id, None)

    def subscribe(self, thread_id: str, worker_id: str) -> None:
        """把 Thread 的后续事件直达 Worker (Subscription)。"""
        with self._lock:
            self._subscriptions[thread_id] = worker_id

    def unsubscribe(self, thread_id: str) -> None:
        with self._lock:
            self._subscriptions.pop(thread_id, None)

    def add_listener(self, fn: Callable[[Trigger, EventStatus], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def _router_agent(self) -> Any:
        if self._router is not None:
            return getattr(self._router, "agent", None)
        return None

    # ---------------------------------------------------------- 过滤

    def program_filter(self, trg: Trigger) -> bool:
        """第一级过滤: 程序规则。返回 True 表示放行 (值得模型研判)。

        默认行为: 无规则时, 非 UNKNOWN 来源的事件放行; 已知来源默认放行
        (由 Router 的模型层做第二级精确研判, 避免程序层误杀)。
        """
        if trg.source == TriggerSource.UNKNOWN and trg.kind == TriggerKind.UNKNOWN:
            return False
        with self._lock:
            rules = list(self._rules)
        if not rules:
            return True
        for rule in rules:
            if rule.matches(trg):
                return rule.action == "allow"
        # 无规则命中: 默认放行 (交 Router 模型层判断, 减少漏判)
        return True

    # ---------------------------------------------------------- 投递

    def emit(self, trg: Trigger) -> EventStatus:
        """接收一条 Trigger, 执行两级处理的第一级, 然后投递。

        流程:
        1. 程序层过滤 (快);
        2. 若 Thread 已订阅 Worker → 直达 (不经过 Router);
        3. 否则交 Router 做模型研判与分派。
        """
        passed = self.program_filter(trg)
        trg.program_passed = passed
        if not passed:
            self._record(trg, EventStatus.FILTERED)
            self._notify(trg, EventStatus.FILTERED)
            return EventStatus.FILTERED

        # 订阅直通: 已关联 Thread 的后续事件直接送到 Worker
        worker_id = self._subscriptions.get(trg.thread_id, "")
        if worker_id:
            worker = self._workers.get(worker_id)
            if worker is not None:
                self._record(trg, EventStatus.DELIVERED)
                self._notify(trg, EventStatus.DELIVERED)
                try:
                    worker.on_thread_event(trg)
                except Exception:  # noqa: BLE001
                    log.exception("worker.on_thread_event failed: %s", worker_id)
                return EventStatus.DELIVERED

        # 交 Router
        router = self._router
        if router is None:
            self._record(trg, EventStatus.IGNORED)
            self._notify(trg, EventStatus.IGNORED)
            return EventStatus.IGNORED
        try:
            status = router.on_event(trg)
        except Exception:  # noqa: BLE001
            log.exception("router.on_event failed")
            status = EventStatus.IGNORED
        self._record(trg, status)
        self._notify(trg, status)
        return status

    # ---------------------------------------------------------- 状态

    def _record(self, trg: Trigger, status: EventStatus) -> None:
        with self._lock:
            self._status[trg.trigger_id] = status

    def _notify(self, trg: Trigger, status: EventStatus) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(trg, status)
            except Exception:  # noqa: BLE001
                pass

    def status_counts(self) -> Dict[str, int]:
        """各状态计数 (面板/统计用)。"""
        with self._lock:
            counts: Dict[str, int] = {}
            for s in self._status.values():
                counts[s.value] = counts.get(s.value, 0) + 1
            return counts

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """最近事件状态快照。"""
        with self._lock:
            items = [
                {"trigger_id": tid, "status": s.value}
                for tid, s in list(self._status.items())[-limit:]
            ]
        return items
