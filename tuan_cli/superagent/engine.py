"""SuperAgent 引擎 —— 把 Router / Worker / EventBus / Watchdog / StateStore 组装起来。

对标 DeepSeek Super-agent 的完整系统:
- 双层架构: Router (承接交互/分派) + WorkerPool (隔离并发执行);
- 事件驱动: EventBus 接收 Trigger, 程序层过滤, 模型研判, 订阅直通;
- 主动: 两级过滤 + 投机执行 (speculative execution);
- 持久: StateStore 落盘 + 重启恢复 + Watchdog 自愈;
- 面向人的交互: Panel 展示待办, 异步 ReAct (Worker 后台跑, 前台继续收消息)。

用法:
    agent = SuperAgent(home="~/.tuan", agent=main_agent)
    agent.start()
    agent.ingest(Trigger(...))       # 外部事件进入
    agent.ingest_text("群聊", "有人在群里说: 这个 bug 能修吗")  # 便捷入口
    panel = agent.panel.render()
    agent.stop()
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .events import EventBus, ProgramRule
from .models import (
    EventStatus,
    EventSource,
    Ticket,
    TicketStatus,
    Trigger,
    TriggerKind,
    TriggerSource,
    WorkMode,
)
from .panel import Panel, PanelItem
from .router import Router
from .store import StateStore
from .watchdog import Watchdog
from .worker import Worker, WorkerPool

log = logging.getLogger(__name__)


def _looks_like_error(result: str) -> bool:
    """投机结果价值判定: 异常信息 (Traceback/Error/Exception) 视为无价值。

    「有价值再交付, 无价值直接放弃」的判别函数: 只把有实质产出的结果
    标记为 valuable, 失败兜底信息不算交付内容。
    """
    if not result:
        return False
    head = result[:200].lower()
    markers = ("traceback", "exception", "error:", "error\n", "失败", "异常",
               "error(", "typeerror", "valueerror", "keyerror", "runtimeerror")
    return any(m in head for m in markers)


class SuperAgent:
    """Super-Agent 引擎主入口。

    组装全部模块并管理生命周期 (start / stop)。
    真实模型执行通过注入 runner 工厂实现; 无注入时用默认占位 runner
    (适合测试/离线, 只验证调度与协作, 不执行真实任务)。
    """

    def __init__(
        self,
        home: str | Path = "~/.tuan",
        agent: Any = None,                     # 主 Agent (Router 模型研判用)
        work_mode: WorkMode = WorkMode.OBSERVE,
        max_workers: int = 5,
        workdir_root: Optional[str] = None,
        make_runner: Optional[Callable[[], Callable[[Any, Worker], str]]] = None,
        assess_fn: Optional[Callable[[Trigger], Dict[str, Any]]] = None,
        watchdog_enabled: bool = True,
        persist: bool = True,
    ) -> None:
        self.home = str(Path(home).expanduser())
        self.agent = agent
        self.work_mode = work_mode
        self.max_workers = max_workers
        self.workdir_root = workdir_root or (os.getcwd())
        self.persist = persist

        # 持久化 (先建, 供各模块使用)
        self.store = StateStore(self.home) if persist else None

        # 事件总线 + 程序层规则
        self.bus = EventBus()

        # Router (研判 + 分派)
        self.router = Router(
            agent=agent,
            work_mode=work_mode,
            assess_fn=assess_fn,
        )
        self.router._store = self.store   # 工单动作落盘 (accept/retry/reply)
        # 跨任务上下文回填: 重启后从 StateStore 恢复 recent_context() 可用。
        self.router.restore_context()

        # WorkerPool (并发隔离执行)
        # 若绑定了真实主 Agent 且未显式注入 runner, 默认用主 Agent 执行任务
        # (Super-Agent 与 Tuan-CLI 的融合: Worker 通过 agent.run() 跑真实任务)。
        if make_runner is None and agent is not None:
            make_runner = self._default_make_runner(agent)
        self.workers = WorkerPool(
            router=self.router,
            max_workers=max_workers,
            workdir_root=self.workdir_root,
            make_runner=make_runner,
            bus=self.bus,   # 订阅直通: Worker 注册到总线, Thread 后续事件直达 Worker
        )
        self.router.attach(self.workers, self.bus)
        self.bus.set_router(self.router)

        # Watchdog (外部监督)
        self.watchdog = Watchdog(
            router=self.router,
            worker_pool=self.workers,
            enabled=watchdog_enabled,
        )

        # Panel (人机交互)
        self.panel = Panel(self.router)

        # 状态跟踪
        self._started = False
        self._lock = threading.RLock()
        self._speculative: List[Dict[str, Any]] = []   # 投机执行记录
        self._recovered = 0
        # 投机执行结果回调 (TUI 挂钩用): fn(entry_dict) —— 完成/失败时触发一次。
        self._on_speculate_result: Optional[Callable[[Dict[str, Any]], None]] = None

    # ---------------------------------------------------------- 生命周期

    def start(self) -> None:
        """启动 Super-Agent (Watchdog + 恢复未完成工单)。"""
        if self._started:
            return
        self._started = True
        self.watchdog.start()
        self._recover_pending()
        log.info("superagent started: mode=%s max_workers=%d",
                 self.work_mode.value, self.max_workers)

    def stop(self) -> None:
        """停止 Super-Agent (协作式终止全部存活 Worker + 停 Watchdog)。"""
        self.watchdog.stop()
        for w in self.workers._workers.values():
            try:
                w.stop()   # 请求 Worker 协作式终止 (run_fn 应检查 should_stop)
            except Exception:  # noqa: BLE001
                pass
        self._started = False

    def is_running(self) -> bool:
        return self._started

    # ---------------------------------------------------------- 事件入口

    def on_event(self, trg: Trigger) -> EventStatus:
        """外部事件入口 (EventSource.emit 调用)。"""
        return self.bus.emit(trg)

    def ingest(self, trg: Trigger) -> EventStatus:
        return self.on_event(trg)

    def ingest_text(self, source: str, content: str,
                    sender: str = "", kind: TriggerKind = TriggerKind.MESSAGE) -> Trigger:
        """便捷入口: 从文本直接构造 Trigger 并投递。"""
        src = TriggerSource(source) if source in TriggerSource._value2member_map_ else TriggerSource.UNKNOWN
        trg = Trigger(kind=kind, source=src, channel=source, content=content, sender=sender)
        self.on_event(trg)
        return trg

    def observe_text(self, content: str, sender: str = "",
                     source: str = "local") -> None:
        """记录用户/外部对话为跨任务上下文 (不研判、不开单)。

        Super-Agent 与 Tuan-CLI 交互界面的融合点: 用户在前台对话区发的消息
        已由主 Agent 直接处理 (agent.run), 不能再喂给 Router 开单 (否则双份
        执行工具)。因此这里只把消息**记录为 Router 的跨任务上下文**, 让之后
        到来的外部事件 (PR/CI/群聊) 在研判时有对话背景可依。
        """
        self.router.observe(content, sender=sender, source=source)

    def recent_context(self, limit: int = 10) -> List[Dict[str, Any]]:
        """最近对话上下文快照 (TUI / CLI 状态展示用)。"""
        return self.router.recent_context(limit=limit)

    # ---------------------------------------------------------- 投机执行

    @staticmethod
    def _default_make_runner(agent: Any) -> Callable[[], Callable[[Any, Worker], str]]:
        """默认 runner 工厂: 用绑定的主 Agent 执行 Worker 任务。

        真实融合点 —— Super-Agent 的 Worker 通过主 Agent 的 ``run()`` 跑任务,
        复用同一套模型/工具/安全策略, 而不再只跑占位逻辑。Worker 可调用
        ``drain_events()`` 拉取订阅直通的新事件 (异步 ReAct 的新输入)。
        """
        def _factory() -> Callable[[Any, Worker], str]:
            def _runner(ticket: Any, worker: Worker) -> str:
                prompt = ticket.prompt or ticket.title
                worker.report_progress(f"开始: {ticket.title[:40]}")

                # 异步 ReAct 输入环: 工单声明了需要用户回答的问题时,
                # Worker 先挂起等答复 (request_input), 答复到达后并入 prompt
                # 再继续执行 —— 后台跑, 前台收消息, 需要人时挂起, 回复后恢复。
                ask = ticket.meta.get("ask")
                if ask:
                    replies = worker.request_input(str(ask))
                    if replies:
                        reply_text = replies[-1].content
                        prompt = f"{prompt}\n[用户答复] {reply_text}"
                        worker.report_progress(f"已收到答复: {reply_text[:60]}")
                    elif worker.should_stop:
                        return "已取消 (Super-Agent stop)"
                    else:
                        worker.report_progress("等待输入超时, 继续按原 prompt 执行")

                _throttle = {"last": 0.0}

                def _on_token(tok: str) -> None:
                    # 流式 token 汇入 progress 并节流上报 (供 Watchdog 判断实质进展,
                    # 也把"正在生成"的进展推回 TUI 对话区, 而非只写私有缓冲)。
                    worker._progress = (worker._progress + tok)[-120:]
                    now = time.monotonic()
                    if now - _throttle["last"] >= 0.8:
                        _throttle["last"] = now
                        try:
                            worker.report_progress(f"生成中… {worker._progress[-60:]}")
                        except Exception:  # noqa: BLE001 - 进度上报失败不阻断任务
                            pass

                try:
                    # 协作式终止: 任务开跑前先看是否已被 stop()
                    if worker.should_stop:
                        return "已取消 (Super-Agent stop)"
                    # 会话隔离: 每个工单独立 session_id, 不污染主会话。
                    # 优先流式 (on_token 实时进度), 旧签名/失败降级为整轮返回。
                    try:
                        result = agent.run(
                            prompt, stream=True, on_token=_on_token,
                            session_id=f"superagent-{ticket.ticket_id}"
                        )
                    except TypeError:
                        result = agent.run(prompt, stream=False)
                except Exception as exc:  # noqa: BLE001
                    # 流式执行失败: 尝试整轮降级 (有些实现 stream=True 未完整支持)
                    try:
                        result = agent.run(prompt, stream=False)
                    except Exception:
                        raise exc
                result = result or ""
                # 订阅直通的新事件 (若 Worker 执行逻辑需要继续处理)
                events = worker.drain_events()
                if events:
                    extra = "\n".join(f"- {e.sender}: {e.content[:60]}" for e in events[:5])
                    result = result + (f"\n[后续事件]\n{extra}" if result else extra)
                return result
            return _runner
        return _factory

    def speculate(self, prompt: str, title: str = "",
                  context: Dict[str, Any] = None) -> Dict[str, Any]:
        """投机执行: 后台提前尝试, 有价值再交付, 无价值直接放弃。

        对标 DeepSeek「静默复现并修复」: 收到会议邀约先查日程冲突/搜集背景/
        准备回复草稿; 群聊讨论问题时尝试复现故障、寻找修复方案。
        """
        spec_id = f"spec-{uuid.uuid4().hex[:8]}"
        entry = {
            "id": spec_id,
            "title": title or prompt[:50],
            "prompt": prompt,
            "status": "running",
            "context": context or {},
            "created_at": time.time(),
            "result": "",
            "valuable": False,
        }
        with self._lock:
            self._speculative.append(entry)

        def _run() -> None:
            try:
                runner = self.workers._make_runner()
                # 投机用临时 Ticket
                from .models import Ticket
                ticket = Ticket(title=entry["title"], prompt=prompt,
                                authorization="inferred")
                worker = Worker(worker_id=f"spec-{uuid.uuid4().hex[:6]}", ticket=ticket,
                                run_fn=runner, report_callback=lambda w_id, r: None)
                result = runner(ticket, worker)
                entry["result"] = result or ""
                entry["status"] = "done"
                # 价值判定: 有实质产出才算有价值 (空/异常信息视为无价值, 交付方放弃)。
                entry["valuable"] = bool(entry["result"]) and not _looks_like_error(
                    entry["result"])
            except Exception as exc:  # noqa: BLE001
                entry["status"] = "failed"
                entry["result"] = f"{type(exc).__name__}: {exc}"
                entry["valuable"] = False
            finally:
                # 交付闭环: 恰好一次, 失败兜底 (failed 也触发, 携带 valuable=False,
                # 供 TUI 挂钩决定"有价值再交付, 无价值直接放弃")。
                cb = self._on_speculate_result
                if cb is not None:
                    try:
                        cb(dict(entry))
                    except Exception:  # noqa: BLE001 - 展示回调绝不阻断投机线程
                        pass

        t = threading.Thread(target=_run, name=f"superagent-spec-{spec_id}", daemon=True)
        t.start()
        return entry

    # ---------------------------------------------------------- 恢复

    def _recover_pending(self) -> None:
        """主进程重启后, 恢复未完成工单 (带恢复说明)。"""
        if self.store is None:
            return
        for ticket in self.store.pending_tickets():
            # 恢复说明: 执行端需先检查目录/Git 历史/平台状态再决定如何继续
            note = self._recovery_note(ticket)
            ticket.progress = f"已从上次运行恢复: {note}"
            ticket.status = TicketStatus.RETRYING
            self.store.save_ticket(ticket)
            self._recovered += 1
            log.info("superagent recovered ticket %s: %s", ticket.ticket_id, note)

    @staticmethod
    def _recovery_note(ticket: Any) -> str:
        """为恢复的工单生成说明 (先检查外部状态, 避免重复执行)。"""
        parts = []
        if ticket.workdir:
            parts.append(f"检查工作目录 {ticket.workdir} 的当前状态")
        parts.append("检查 Git 历史与远端平台 (如 PR 是否已推送) 再决定如何继续")
        if ticket.meta.get("external_id"):
            parts.append(f"外部对象 {ticket.meta['external_id']} 需核对幂等")
        return "; ".join(parts) if parts else "检查执行环境后继续"

    # ---------------------------------------------------------- 事件源注册

    def add_source(self, source: EventSource) -> None:
        """注册外部事件源 (IM/GitHub/文件监视等)。"""
        self.bus.add_source(source)

    def add_rule(self, rule: ProgramRule) -> None:
        """添加程序层过滤规则。"""
        self.bus.add_rule(rule)

    # ---------------------------------------------------------- 工单动作 (人机交互)

    def accept_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """验收工单: REVIEW → DONE (结果已采纳)。"""
        ticket = self.router.accept_ticket(ticket_id)
        if ticket is not None:
            log.info("superagent accept: %s", ticket_id)
        return ticket

    def retry_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """重试工单: FAILED/BLOCKED → 重新分派。"""
        ticket = self.router.retry_ticket(ticket_id)
        if ticket is not None:
            log.info("superagent retry: %s", ticket_id)
        return ticket

    def reply_ticket(self, ticket_id: str, reply: str) -> Optional[Ticket]:
        """回答 NEEDS_INPUT 工单 (把答复注入)。"""
        ticket = self.router.reply_ticket(ticket_id, reply)
        if ticket is not None:
            log.info("superagent reply: %s", ticket_id)
        return ticket

    # ---------------------------------------------------------- 状态查询

    def status(self) -> Dict[str, Any]:
        return {
            "started": self._started,
            "work_mode": self.work_mode.value,
            "max_workers": self.max_workers,
            "router": self.router.metrics(),
            "workers": self.workers.status(),
            "active_workers": self.workers.active_count(),
            "watchdog": self.watchdog.metrics(),
            "event_bus": self.bus.status_counts(),
            "context": {
                "observed": len(self.router.recent_context(limit=1000)),
                "recent": self.router.recent_context(limit=5),
            },
            "panel": [i.to_dict() for i in self.panel.build()],
            "speculative": self._speculative,
            "recovered": self._recovered,
            "store": self.store.stats() if self.store else None,
        }

    def summary(self) -> str:
        """一行摘要 (状态栏用)。"""
        active = self.workers.active_count()
        needs = len(self.panel.needs_human())
        return f"Super-Agent: {active} worker 运行中 · {needs} 项待你处理"

    def render_panel(self) -> str:
        return self.panel.render()
