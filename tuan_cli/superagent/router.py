"""Router 层 —— 承接交互、维护全局上下文、分派任务。

对标 DeepSeek Super-agent 双层架构中的 Router:
- 持续运行的全局协调节点;
- 统一接收来自群聊/GitHub/邮件等不同平台的信息;
- 判断任务如何分配, 维护跨任务上下文;
- Worker 不直接向用户回复, 而是将状态和结果汇报给 Router, 由后者统一对外沟通。

两级过滤的第二级 (模型研判) 也在这里: 程序层 (EventBus) 排除无关消息后,
Router 用模型结合规则与上下文判断是否需要行动。

接单模式 (WorkMode):
- off / observe / auto 决定**推断出来的候选** (非明确请求) 是否开单;
- 明确授权的请求在三档模式下均可执行。

投机执行 (Speculative Execution): 在尚未确定结果是否被采用时, 提前在后台
尝试 (复现问题/找修复方案), 有价值的结果再交付, 无价值直接放弃。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set

from .models import (
    EventStatus,
    Thread,
    Ticket,
    TicketStatus,
    Trigger,
    TriggerKind,
    TriggerSource,
    WorkMode,
)

log = logging.getLogger(__name__)


class Router:
    """Router 会话: 研判事件、建立 Thread/Ticket、分派给 Worker。

    设计: Router 本身较"轻" —— 它做判断与分派, 具体实现交给 Worker。
    可用轻量模型跑 (DeepSeek 建议), 复杂任务用强模型 Worker。
    """

    def __init__(
        self,
        agent: Any = None,
        work_mode: WorkMode = WorkMode.OBSERVE,
        assess_fn: Optional[Callable[[Trigger], Dict[str, Any]]] = None,
        auto_rule: Optional[Callable[[Trigger], bool]] = None,
    ) -> None:
        self.agent = agent                    # 主 Agent (用于模型研判, 可注入)
        self.work_mode = work_mode            # 主动候选接单模式
        self.assess_fn = assess_fn            # 注入研判函数 (测试/可定制)
        self.auto_rule = auto_rule            # auto 模式的启用规则
        self.threads: Dict[str, Thread] = {}
        self.tickets: Dict[str, Ticket] = {}
        self._sources: Dict[str, TriggerSource] = {}  # trigger_id -> source
        self._worker_pool: Any = None
        self._bus: Any = None
        self._store: Any = None   # StateStore (引擎装配时注入, 工单动作落盘用)
        self._listeners: List[Callable[[str, Dict[str, Any]], None]] = []
        self._assess_count = 0
        self._dispatch_count = 0
        # 跨任务上下文 (DeepSeek: Router 维护全局上下文, 供模型研判与 Worker 复用)。
        # 环形缓冲: 记录最近用户/外部对话片段, 让「外部事件研判」有对话背景可依,
        # 而不是孤立判断单条 Trigger。线程安全 (TUI 前台收消息, Watchdog 后台读)。
        self._ctx: Deque[Dict[str, Any]] = deque(maxlen=40)
        self._ctx_lock = threading.RLock()
        self._ctx_ts = 0.0

    def attach(self, worker_pool: Any, bus: Any) -> None:
        self._worker_pool = worker_pool
        self._bus = bus

    def add_listener(self, fn: Callable[[str, Dict[str, Any]], None]) -> None:
        """监听 Router 决策 (事件名: dispatch / assess / ticket_update)。"""
        self._listeners.append(fn)

    def _notify(self, name: str, payload: Dict[str, Any]) -> None:
        for fn in self._listeners:
            try:
                fn(name, payload)
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------- 事件处理

    def observe(self, text: str, sender: str = "", source: str = "local") -> None:
        """把一段用户/外部对话记录进跨任务上下文 (不研判、不开单)。

        这是 Super-Agent 与 Tuan-CLI 交互界面的融合点: 用户在前台对话区发的
        消息**已由主 Agent 直接处理** (agent.run), 不能再喂给 Router 开单
        (否则同一条消息会双份执行工具)。因此这里只把消息**记录为上下文**,
        让之后到来的外部事件 (PR/CI/群聊) 在研判时有对话背景可依。

        注意: 这是「观察」不是「接单」——不触碰 work_mode, 不开工单,
        不产生事件投递, 纯上下文维护。线程安全。
        """
        content = (text or "").strip()
        if not content:
            return
        entry = {
            "role": "user",
            "content": content[:500],
            "sender": sender or "你",
            "source": source,
            "ts": time.time(),
        }
        with self._ctx_lock:
            self._ctx.append(entry)
            self._ctx_ts = time.time()
            # 跨任务上下文落盘: 崩溃/重启后 recent_context() 仍可用。
            store = self._store
        if store is not None:
            try:
                store.save_context(entry)
            except Exception:  # noqa: BLE001 - 落盘失败不阻断观察
                log.warning("save_context failed: %s", entry.get("content", "")[:40])

    def restore_context(self) -> int:
        """把持久化的观察上下文回填进内存环形缓冲 (重启恢复)。

        返回回填条数。由引擎在装配 Router 时调用; 无持久化时不动作。
        """
        store = self._store
        if store is None:
            return 0
        try:
            items = store.load_context()
        except Exception:  # noqa: BLE001
            return 0
        if not items:
            return 0
        with self._ctx_lock:
            for it in items:
                self._ctx.append(it)
            self._ctx_ts = max((it.get("ts", 0.0) for it in items), default=self._ctx_ts)
        return len(items)

    def recent_context(self, limit: int = 10) -> List[Dict[str, Any]]:
        """最近对话上下文 (供模型研判 / Worker 任务构建复用)。"""
        with self._ctx_lock:
            items = list(self._ctx)[-limit:]
        return items

    def _context_block(self, limit: int = 6) -> str:
        """把最近对话上下文渲染成提示词片段 (供模型研判 prompt 拼接)。"""
        items = self.recent_context(limit=limit)
        if not items:
            return ""
        lines = ["近期对话上下文 (供你判断外部事件是否与此相关):"]
        for it in items:
            who = it.get("sender", "你")
            body = it.get("content", "")
            lines.append(f"- {who}: {body[:120]}")
        return "\n".join(lines)

    def on_event(self, trg: Trigger) -> EventStatus:
        """Router 处理一条通过程序层过滤的事件。

        1. 归类到 Thread (同一话题);
        2. 若 Thread 已有 Ticket → 补发更新 (交回重路由或直达);
        3. 否则模型研判: 是否值得开单。
        """
        # 归类 Thread: 同一 source+channel 视为同一话题
        thread = self._get_or_create_thread(trg)
        trg.thread_id = thread.thread_id

        # 已有工单关联: 后续事件作为更新的输入
        if thread.ticket_id and thread.ticket_id in self.tickets:
            ticket = self.tickets[thread.ticket_id]
            self._update_ticket_from_event(ticket, trg)
            self._notify("ticket_update", {"ticket_id": ticket.ticket_id, "trigger_id": trg.trigger_id})
            return EventStatus.ROUTED

        # 无关联工单: 模型研判是否开单
        decision = self._assess(trg)
        self._assess_count += 1

        if not decision.get("actionable", False):
            self._notify("assess", {"trigger_id": trg.trigger_id, "actionable": False})
            return EventStatus.ASSESSED if decision.get("would_accept", False) else EventStatus.IGNORED

        # 开单 (明确请求 或 满足 auto/observe 模式的推断候选)
        ticket = self._dispatch_ticket(trg, decision)
        if ticket is not None:
            self._dispatch_count += 1
            return EventStatus.ROUTED

        # observe 模式: 正面判断只记录「本来会接单」, 实际不开单
        self._notify("assess", {"trigger_id": trg.trigger_id, "actionable": True, "would_accept": True, "opened": False})
        return EventStatus.ASSESSED

    # ---------------------------------------------------------- 研判

    def _assess(self, trg: Trigger) -> Dict[str, Any]:
        """第二级过滤: 模型研判是否需要行动。

        返回 {"actionable": bool, "would_accept": bool, "reason": str,
              "title": str, "prompt": str, "authorization": str}
        """
        if self.assess_fn is not None:
            return self.assess_fn(trg)

        # 无注入研判函数时: 用规则启发式 + 主 Agent 模型 (若可用)
        base = self._heuristic_assess(trg)
        if self.agent is not None:
            return self._model_assess(trg, base)
        return base

    def _heuristic_assess(self, trg: Trigger) -> Dict[str, Any]:
        """无模型时的启发式研判 (可独立测试)。

        规则:
        - 明确请求词 ("请修复" "请实现" "帮我" "fix this" "please") → 明确授权;
        - PR/CI 状态 → 明确授权 (与已派工单关联);
        - 其余推断候选 → 依据 WorkMode 决定。
        """
        text = (trg.content or "").lower()
        explicit_markers = ("请修复", "请实现", "请帮我", "帮我", "麻烦你",
                            "fix this", "please fix", "please implement", "请处理")
        is_explicit = any(m in text for m in explicit_markers) or trg.kind in (
            TriggerKind.PR, TriggerKind.CI, TriggerKind.ISSUE,
        )
        if is_explicit:
            return {
                "actionable": True,
                "would_accept": True,
                "authorization": "explicit",
                "title": self._guess_title(trg),
                "prompt": f"[{trg.source.value}:{trg.channel}] {trg.sender}: {trg.content}",
                "reason": "明确请求",
            }
        # 推断候选: 依据 work_mode
        if self.work_mode == WorkMode.OFF:
            return {"actionable": False, "would_accept": False, "reason": "off 模式不接推断候选"}
        if self.work_mode == WorkMode.AUTO:
            if self.auto_rule is not None and not self.auto_rule(trg):
                return {"actionable": False, "would_accept": False, "reason": "auto 模式未匹配启用规则"}
            return {
                "actionable": True,
                "would_accept": True,
                "authorization": "inferred",
                "title": self._guess_title(trg),
                "prompt": f"[{trg.source.value}:{trg.channel}] {trg.sender}: {trg.content}",
                "reason": "auto 模式推断候选",
            }
        # observe: 评估候选, 正面判断记录为「本来会接单」但实际不开单
        return {
            "actionable": True,
            "would_accept": True,
            "authorization": "inferred",
            "title": self._guess_title(trg),
            "prompt": f"[{trg.source.value}:{trg.channel}] {trg.sender}: {trg.content}",
            "reason": "observe 模式: 本来会接单",
            "observe_only": True,
        }

    def _model_assess(self, trg: Trigger, base: Dict[str, Any]) -> Dict[str, Any]:
        """用主 Agent 模型做语义研判 (需要真实模型时注入, 测试桩返回 base)。"""
        # 主 Agent 的模型调用; 失败时退回启发式
        try:
            ctx_block = self._context_block(limit=6)
            prompt = (
                "你是 Super-Agent 的 Router。判断下面这条外部事件是否需要启动工作。\n"
                "规则: 明确请求 (修复/实现/处理) 应开单; 普通讨论只在明确指向缺陷/待办时开单;\n"
                "无关闲聊不行动。只输出 JSON: {\"actionable\": bool, \"reason\": str, \"title\": str}\n\n"
                f"{ctx_block}\n"
                f"来源: {trg.source.value}:{trg.channel}\n发送者: {trg.sender}\n内容: {trg.content}"
            )
            raw = self.agent.run(prompt, stream=False) or ""
            obj = json.loads(self._extract_json(raw))
            actionable = bool(obj.get("actionable", False))
            if actionable:
                base["actionable"] = True
                base["would_accept"] = True
                base["title"] = obj.get("title") or base.get("title", trg.content[:60])
                base["reason"] = obj.get("reason", "模型研判: 值得行动")
            else:
                base["actionable"] = False
                base["would_accept"] = False
                base["reason"] = obj.get("reason", "模型研判: 无需行动")
            return base
        except Exception:  # noqa: BLE001
            return base

    @staticmethod
    def _extract_json(raw: str) -> str:
        text = raw.strip()
        if "```" in text:
            import re
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return text

    def _guess_title(self, trg: Trigger) -> str:
        content = (trg.content or "").strip()
        if not content:
            return f"{trg.kind.value}@{trg.channel or trg.source.value}"
        return content[:50] + ("…" if len(content) > 50 else "")

    # ---------------------------------------------------------- 分派

    def _dispatch_ticket(self, trg: Trigger, decision: Dict[str, Any]) -> Optional[Ticket]:
        """创建工单并分派给 Worker。

        observe 模式 (推断候选) 不开单; 明确请求或 auto 模式开单。
        """
        if decision.get("observe_only"):
            return None  # observe: 只记录, 不开单

        ticket = Ticket(
            title=decision.get("title", self._guess_title(trg)),
            prompt=decision.get("prompt", trg.content),
            source_trigger_id=trg.trigger_id,
            thread_id=trg.thread_id,
            authorization=decision.get("authorization", "explicit"),
        )
        thread = self.threads.get(trg.thread_id)
        if thread is not None:
            thread.ticket_id = ticket.ticket_id
        self.tickets[ticket.ticket_id] = ticket

        worker_id = ""
        if self._worker_pool is not None:
            # 先置状态再启动 Worker, 避免竞态: 若 Worker 立即完成并把工单
            # 标为 REVIEW, 不能被下面 "dispatch 后置 RUNNING" 覆盖 (先记录后执行)。
            ticket.status = TicketStatus.RUNNING
            ticket.started_at = time.time()
            worker_id = self._worker_pool.dispatch(ticket)
        if not worker_id:
            ticket.status = TicketStatus.BLOCKED
            ticket.started_at = 0.0
        ticket.worker_id = worker_id

        # 订阅: Thread 后续事件直达 Worker
        if self._bus is not None and worker_id:
            self._bus.subscribe(trg.thread_id, worker_id)

        self._notify("dispatch", {
            "ticket_id": ticket.ticket_id,
            "title": ticket.title,
            "worker_id": worker_id,
            "authorization": ticket.authorization,
        })
        return ticket

    # ---------------------------------------------------------- 工单动作 (人机交互)

    def accept_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """验收工单: REVIEW/DRAFT → DONE (结果已采纳, 关闭面板待办)。

        供 TUI 面板交互 / /superagent 子命令调用。返回工单 (失败返回 None)。
        DRAFT (未达交付标准的草稿) 也可验收: 用户明确采纳即视为完成。
        """
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return None
        if ticket.status in (TicketStatus.REVIEW, TicketStatus.DRAFT):
            ticket.status = TicketStatus.DONE
            ticket.updated_at = time.time()
            if self._store is not None:
                self._store.save_ticket(ticket)
            self._notify("ticket_update", {
                "ticket_id": ticket.ticket_id,
                "report": {"status": "accepted", "progress": "已验收 · 结果已采纳",
                           "result": ticket.result[:120]},
            })
        return ticket

    def retry_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """重试工单: FAILED/BLOCKED → 重新分派 (新 Worker 执行)。

        返回工单 (不可重试或不存在返回 None)。
        """
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return None
        if ticket.status not in (TicketStatus.FAILED, TicketStatus.BLOCKED):
            return None
        ticket.error = ""
        ticket.progress = "重试中…"
        ticket.status = TicketStatus.RUNNING
        ticket.started_at = time.time()
        ticket.updated_at = time.time()
        worker_id = ""
        if self._worker_pool is not None:
            worker_id = self._worker_pool.dispatch(ticket)
        if not worker_id:
            ticket.status = TicketStatus.BLOCKED
            ticket.started_at = 0.0
        ticket.worker_id = worker_id
        if self._store is not None:
            self._store.save_ticket(ticket)
        self._notify("ticket_update", {
            "ticket_id": ticket.ticket_id,
            "report": {"status": "retrying", "progress": "已重试 · 重新分派"},
        })
        return ticket

    def reply_ticket(self, ticket_id: str, reply: str) -> Optional[Ticket]:
        """回答 NEEDS_INPUT 工单: 把用户答复作为后续输入注入。

        供 TUI 面板交互 (待回答工单) / /superagent 子命令调用。

        可靠性: 直接调用 WorkerPool.on_ticket_update 把答复送达该工单的
        Worker (即使 EventBus 订阅直通尚未注册/已失效, 也不丢答复);
        随后才经 bus.emit 走订阅直通兜底。两条路径都调用 worker.on_thread_event
        可能重复投递 —— 因此主路径用 on_ticket_update (直达), bus.emit 仅作为
        Router 重路由的兜底 (仅当无订阅时, 事件交回 _update_ticket_from_event)。
        """
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return None
        if ticket.status != TicketStatus.NEEDS_INPUT:
            return None
        # 把答复作为新事件注入 (直达对应 Worker, 保证送达)
        trg = Trigger(
            kind=TriggerKind.MESSAGE,
            source=TriggerSource.LOCAL,
            channel="panel",
            content=reply,
            sender="你",
        )
        trg.thread_id = ticket.thread_id
        trg.ticket_id = ticket.ticket_id
        # 1) 主路径: 直达该工单的 Worker (经 WorkerPool.on_ticket_update 路由)。
        #    这保证答复可靠送达, 不依赖 EventBus 订阅是否已注册。
        delivered = False
        if self._worker_pool is not None:
            delivered = self._worker_pool.on_ticket_update(ticket_id, trg)
        # 2) 兜底: 仅当直达未成功 (Worker 已结束/不存在) 时, 才经 bus.emit
        #    走 Router 重路由, 把答复作为 Thread 后续事件记录。
        if not delivered:
            if self._bus is not None:
                self._bus.emit(trg)
            else:
                self._update_ticket_from_event(ticket, trg)
        ticket.updated_at = time.time()
        if self._store is not None:
            self._store.save_ticket(ticket)
        return ticket

    def _update_ticket_from_event(self, ticket: Ticket, trg: Trigger) -> None:
        """已有工单收到后续事件: 作为更新输入 (直达或重路由)。"""
        ticket.progress = f"收到新事件 ({trg.kind.value}): {trg.content[:80]}"
        ticket.updated_at = time.time()
        # 若 Worker 支持, 把更新推给 Worker
        if ticket.worker_id and self._worker_pool is not None:
            self._worker_pool.on_ticket_update(ticket.ticket_id, trg)

    # ---------------------------------------------------------- Thread

    def _get_or_create_thread(self, trg: Trigger) -> Thread:
        key = f"{trg.source.value}:{trg.channel}"
        for t in self.threads.values():
            if t.source == trg.source and t.channel == trg.channel:
                if trg.trigger_id not in t.triggers:
                    t.triggers.append(trg.trigger_id)
                t.updated_at = time.time()
                return t
        thread = Thread(topic=self._guess_title(trg), source=trg.source, channel=trg.channel)
        thread.triggers.append(trg.trigger_id)
        self.threads[thread.thread_id] = thread
        return thread

    # ---------------------------------------------------------- 状态

    def on_worker_report(self, worker_id: str, report: Dict[str, Any]) -> None:
        """Worker 汇报状态/结果 (Worker 不直接向用户回复)。"""
        ticket_id = report.get("ticket_id", "")
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return
        if report.get("status") == "done":
            ticket.status = TicketStatus.REVIEW
            ticket.result = report.get("result", "")
            ticket.finished_at = time.time()
        elif report.get("status") == "failed":
            ticket.status = TicketStatus.FAILED
            ticket.error = report.get("error", "Worker 失败")
            ticket.finished_at = time.time()
        elif report.get("status") == "cancelled":
            # 协作式终止: 工单落 CANCELLED (不再可审阅), 带最后结果快照。
            ticket.status = TicketStatus.CANCELLED
            ticket.result = report.get("result", "") or ticket.result
            ticket.progress = "已取消"
            ticket.finished_at = time.time()
        elif report.get("status") == "progress":
            ticket.status = TicketStatus.RUNNING
            ticket.progress = report.get("progress", "")
        elif report.get("status") == "needs_input":
            ticket.status = TicketStatus.NEEDS_INPUT
            ticket.progress = report.get("progress", "")
        ticket.updated_at = time.time()
        # 落盘: 终态 (done/failed/cancelled) 与 needs_input 状态变化需持久,
        # 否则重启后工单状态丢失 (progress 高频跳过, 避免频繁写盘)。
        if report.get("status") in ("done", "failed", "cancelled", "needs_input"):
            if self._store is not None:
                try:
                    self._store.save_ticket(ticket)
                except Exception:  # noqa: BLE001 - 落盘失败不阻断汇报
                    log.warning("save_ticket failed on report: %s", ticket.ticket_id)
        self._notify("ticket_update", {"ticket_id": ticket.ticket_id, "report": report})

    def ticket_summary(self) -> List[Dict[str, Any]]:
        """工单状态快照 (面板用)。"""
        out = []
        for t in self.tickets.values():
            out.append({
                "ticket_id": t.ticket_id,
                "title": t.title,
                "status": t.status.value,
                "authorization": t.authorization,
                "worker_id": t.worker_id,
                "progress": t.progress[:120],
                "has_result": bool(t.result),
                "error": t.error[:120],
                "updated_at": t.updated_at,
            })
        out.sort(key=lambda x: -x["updated_at"])
        return out

    def metrics(self) -> Dict[str, Any]:
        return {
            "threads": len(self.threads),
            "tickets": len(self.tickets),
            "assess": self._assess_count,
            "dispatch": self._dispatch_count,
            "status": {s.value: sum(1 for t in self.tickets.values() if t.status == s)
                       for s in TicketStatus},
        }
