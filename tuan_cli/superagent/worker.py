"""Worker 层 —— 隔离会话中并发执行具体工作。

对标 DeepSeek Super-agent 双层架构中的 Worker:
- 每个 Worker 拥有独立的上下文和工具能力, 在相互隔离的会话中并发执行;
- Worker 不直接向用户回复, 而是将状态和结果汇报给 Router;
- Worker 可以订阅对应 Thread, 后续相关事件由程序直接发送给它 (Subscription);
- Worker 内部还可以调用子 Agent (Subagent)。

WorkerPool 管理多个 Worker 的并发调度与隔离 (复用 SubAgentPool 的沙箱/隔离机制)。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .models import Ticket, TicketStatus, Trigger

log = logging.getLogger(__name__)


@dataclass
class WorkerReport:
    """Worker 向 Router 的汇报。"""
    ticket_id: str
    status: str            # "progress" | "done" | "failed" | "needs_input"
    progress: str = ""
    result: str = ""
    error: str = ""
    elapsed: float = 0.0


class Worker:
    """一个隔离执行会话 (对应一个 Ticket / 一个工作目录)。

    Worker 持有自己的 run_fn (实际执行逻辑), 在独立线程里跑;
    通过 report_callback 把状态/结果汇报给 Router (不直接向用户回复)。
    """

    def __init__(
        self,
        worker_id: str,
        ticket: Ticket,
        run_fn: Callable[[Ticket, "Worker"], str],
        report_callback: Callable[[str, Dict[str, Any]], None],
        workdir: Optional[str] = None,
        max_runtime: float = 1800.0,
    ) -> None:
        self.worker_id = worker_id
        self.ticket = ticket
        self.run_fn = run_fn
        self.report_callback = report_callback
        self.workdir = workdir or ""
        self.max_runtime = max_runtime
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pending_events: List[Trigger] = []
        self._events_lock = threading.Lock()
        self._progress = ""
        self._result = ""
        self._error = ""
        self._finished = False
        self._started_at = 0.0
        self._elapsed = 0.0

    # ---------------------------------------------------------- 生命周期

    def start(self) -> None:
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"superagent-worker-{self.worker_id}", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        try:
            result = self.run_fn(self.ticket, self)
            self._result = result or ""
            self._finished = True
            self._elapsed = time.time() - self._started_at
            # 状态机: stop() 请求过 (should_stop) 且执行因协作式终止返回
            # (如默认 runner 返回"已取消"), 应落 CANCELLED 而非 DONE,
            # 避免"被取消的工单误报为可审阅结果"的非法迁移。
            if self.should_stop:
                self._report("cancelled", result=self._result, elapsed=self._elapsed)
            else:
                self._report("done", result=self._result, elapsed=self._elapsed)
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            self._finished = True
            self._elapsed = time.time() - self._started_at
            self._report("failed", error=self._error, elapsed=self._elapsed)

    def stop(self) -> None:
        """请求终止 (协作式; run_fn 应定期检查 should_stop)。"""
        self._stop.set()

    @property
    def should_stop(self) -> bool:
        return self._stop.is_set()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---------------------------------------------------------- 事件直通

    def on_thread_event(self, trg: Trigger) -> None:
        """订阅的 Thread 后续事件直接送达 (Subscription)。"""
        with self._events_lock:
            self._pending_events.append(trg)

    def drain_events(self) -> List[Trigger]:
        """Worker 执行逻辑可定期取走新到事件 (异步 ReAct 的"新输入")。"""
        with self._events_lock:
            evs = list(self._pending_events)
            self._pending_events.clear()
        return evs

    def wait_for_input(self, timeout: float = 300.0) -> List[Trigger]:
        """阻塞等待用户答复 (NEEDS_INPUT 后的异步 ReAct 恢复)。

        Worker 调用 report_needs_input() 后, 用此方法挂起等待新输入;
        收到事件 (reply_ticket 注入 / 订阅直通直达) 后返回取到的答复列表。
        空列表 = 超时或请求停止, 调用方应结束当前执行环。

        这是「异步 ReAct」闭环: Worker 后台跑, 前台继续收消息,
        需要人时挂起等答复, 答复到达后恢复执行。
        """
        deadline = time.time() + timeout
        while not self._stop.is_set():
            with self._events_lock:
                if self._pending_events:
                    evs = list(self._pending_events)
                    self._pending_events.clear()
                    return evs
            if time.time() >= deadline:
                return []
            time.sleep(0.05)
        return []

    def request_input(self, question: str, timeout: float = 300.0) -> List[Trigger]:
        """报告需要用户输入并挂起等待答复 (异步 ReAct 闭环 API)。

        先汇报 NEEDS_INPUT (Router → 面板/TUI 呈现「需要你回答」),
        再阻塞等待新事件 (reply_ticket / 订阅直通直达)。
        答复到达后返回; 空列表 = 超时或请求停止。
        """
        self.report_needs_input(question)
        return self.wait_for_input(timeout=timeout)

    # ---------------------------------------------------------- 汇报

    def report_progress(self, progress: str) -> None:
        self._progress = progress
        self._report("progress", progress=progress)

    def report_needs_input(self, question: str) -> None:
        self._progress = question
        self._report("needs_input", progress=question)

    def _report(self, status: str, **kw: Any) -> None:
        payload = {"ticket_id": self.ticket.ticket_id, "status": status}
        payload.update(kw)
        try:
            self.report_callback(self.worker_id, payload)
        except Exception:  # noqa: BLE001
            log.exception("report_callback failed")


class WorkerPool:
    """管理多个 Worker 的并发调度与隔离。

    每个 Ticket 对应一个 Worker; Worker 在独立线程中执行 run_fn。
    复用 SubAgentPool 的隔离工作目录机制 (可选), 但 Worker 本身是轻量线程。
    """

    def __init__(
        self,
        router: Any = None,
        max_workers: int = 5,
        workdir_root: Optional[str] = None,
        make_runner: Optional[Callable[[], Callable[[Ticket, Worker], str]]] = None,
        bus: Any = None,
    ) -> None:
        self.router = router
        self.max_workers = max(1, min(max_workers, 5))
        self.workdir_root = workdir_root or ""
        self.make_runner = make_runner   # 注入 runner 工厂 (测试/真实)
        self.bus = bus                   # EventBus (订阅直通注册/注销用, 可空)
        self._workers: Dict[str, Worker] = {}
        self._ticket_to_worker: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._reserved_slots = 0          # 人工跟进/状态请求的保留名额

    # ---------------------------------------------------------- 调度

    def dispatch(self, ticket: Ticket) -> str:
        """为工单分配 Worker 并启动执行。返回 worker_id (0 表示受限)。"""
        worker_id = ""
        with self._lock:
            active = sum(1 for w in self._workers.values() if w.is_alive)
            if active >= self.max_workers:
                return ""  # 名额已满 (Router 会标 BLOCKED)
            worker_id = f"wk-{uuid.uuid4().hex[:8]}"

        run_fn = self._make_runner()
        workdir = self._make_workdir(ticket, worker_id)
        worker = Worker(
            worker_id=worker_id,
            ticket=ticket,
            run_fn=run_fn,
            report_callback=self._on_worker_report,
            workdir=workdir,
        )
        with self._lock:
            self._workers[worker_id] = worker
            self._ticket_to_worker[ticket.ticket_id] = worker_id
        # 注册到 EventBus: 让 Thread 订阅直通真正生效 (Subscription → Worker 直达,
        # 而非每次退化为 Router 重路由)。Worker 结束时会取消订阅 (见 _on_worker_report)。
        if self.bus is not None:
            self.bus.register_worker(worker_id, worker)
        worker.start()
        return worker_id

    def _make_runner(self) -> Callable[[Ticket, Worker], str]:
        """创建 Worker 执行函数。

        默认: 若有注入工厂用注入; 否则返回一个占位 runner (供测试/无模型环境)。
        """
        if self.make_runner is not None:
            return self.make_runner()
        return _default_runner

    def _make_workdir(self, ticket: Ticket, worker_id: str) -> str:
        if not self.workdir_root:
            return ""
        safe_id = "".join(c for c in worker_id if c.isalnum() or c in "-_") or uuid.uuid4().hex[:6]
        wd = Path(self.workdir_root) / ".tuan" / "superagent" / safe_id
        try:
            wd.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""
        return str(wd)

    # ---------------------------------------------------------- 汇报回传

    def _on_worker_report(self, worker_id: str, report: Dict[str, Any]) -> None:
        # Worker 结束 (完成/失败/取消): 取消订阅直通, 避免已结束的 Worker 继续
        # 接收 Thread 后续事件 (泄漏)。needs_input 仍存活, 保留订阅 (等回复)。
        if report.get("status") in ("done", "failed", "cancelled"):
            self._release_subscription(worker_id)
        if self.router is not None:
            self.router.on_worker_report(worker_id, report)

    def _release_subscription(self, worker_id: str) -> None:
        """取消该 Worker 的订阅直通并注销 (Worker 已完成, 不再接收事件)。"""
        if self.bus is None:
            return
        # 找该 Worker 对应的 Thread (经 Router 的 tickets/threads 反查)
        thread_id = ""
        if self.router is not None:
            ticket = next(
                (t for t in self.router.tickets.values() if t.worker_id == worker_id),
                None,
            )
            if ticket is not None and ticket.thread_id:
                thread_id = ticket.thread_id
        if thread_id:
            self.bus.unsubscribe(thread_id)
        try:
            self.bus.unregister_worker(worker_id)
        except Exception:  # noqa: BLE001 - 注销失败不影响主流程
            pass

    def on_ticket_update(self, ticket_id: str, trg: Trigger) -> bool:
        """把 Ticket 的后续事件推给对应 Worker。

        返回是否已投递到存活 Worker (False 表示 Worker 已结束/不存在,
        调用方可再走 Router 重路由兜底)。
        """
        with self._lock:
            worker_id = self._ticket_to_worker.get(ticket_id, "")
        if worker_id:
            worker = self._workers.get(worker_id)
            if worker is not None:
                worker.on_thread_event(trg)
                return True
        return False

    # ---------------------------------------------------------- 状态

    def status(self) -> List[Dict[str, Any]]:
        with self._lock:
            out = []
            for wid, w in self._workers.items():
                # 状态字段从工单状态派生 (RUNNING/REVIEW/FAILED/NEEDS_INPUT…),
                # 供 CLI/TUI 状态展示, 而非 CLI 里 get('status','?') 永远显示 ?。
                st = getattr(w.ticket, "status", None)
                status_val = st.value if st is not None else ("done" if w._finished else "running")
                out.append({
                    "worker_id": wid,
                    "ticket_id": w.ticket.ticket_id,
                    "title": w.ticket.title[:60],
                    "status": status_val,
                    "alive": w.is_alive,
                    "finished": w._finished,
                    "elapsed": round(time.time() - w._started_at, 1) if w._started_at else 0.0,
                    "progress": w._progress[:120],
                    "pending_events": len(w._pending_events),
                })
            return out

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for w in self._workers.values() if w.is_alive)


def _default_runner(ticket: Ticket, worker: Worker) -> str:
    """默认 runner: 把工单 prompt 当作任务执行 (真实场景由引擎注入 agent 实现)。

    这里实现一个可独立测试的默认行为: 模拟执行, 支持 worker.drain_events()
    处理订阅直通的新事件。
    """
    worker.report_progress(f"开始: {ticket.title[:40]}")
    time.sleep(0.1)
    events = worker.drain_events()
    extra = ""
    if events:
        extra = "\n".join(f"- {e.sender}: {e.content[:60]}" for e in events[:5])
        worker.report_progress(f"收到 {len(events)} 条后续事件")
    return f"执行完成: {ticket.title[:60]}" + (f"\n后续事件:\n{extra}" if extra else "")
