"""与 Codex ``tui/src/app_event_sender.rs`` 对齐的事件发送器。

上游模块头：

    "Convenience sender for app events and common outbound TUI commands.
    This wraps the raw channel so call sites can submit typed `AppCommand`s
    without duplicating event construction or session logging behavior."

逐分支对齐 ``send()``（**顺序是有安全含义的，不能重排**）：
  1. ``voice_only`` 为真时，先做白名单判定，不匹配则 **直接 return**
     —— 上游注释：被 parked 的语音 owner 仍处理自己的会话，但它的 UI
     与排队的类型化工作**不得作用于可见会话**。注意这一步在日志之前，
     所以被丢弃的事件**不会**进 inbound 日志；
  2. 非 ``CodexOp`` 事件记 inbound 日志（上游「Avoid double-logging
     Ops; those are logged at the point of submission」）；
  3. 发送失败**吞掉错误并记 error 日志**，不把异常抛回调用点。

便捷方法（``interrupt`` / ``compact`` / ``set_thread_name`` /
``review`` / ``exec_approval`` / ``patch_approval`` /
``request_permissions_response`` / ``user_input_answer`` /
``resolve_elicitation`` / ``resolve_user_verification``）逐一对齐上游，
都通过 ``SubmitThreadOp`` 或 ``CodexOp`` 构造，不在调用点手拼事件。

本地化修改（如实列出）：
  - tokio ``UnboundedSender`` -> 可注入 sink 可调用对象 + 有界队列；
    **队列满时拒绝并计数**（本地化增强：上游无界队列在异常路径可能
    无限增长，这里不引入无界内存增长）；
  - ``Arc<AtomicBool>`` -> ``threading.Event``；
  - ``session_log`` / ``tracing`` -> 可注入 logger；
  - **新增提交前校验**：``validate_thread_op()`` 拒绝缺 thread_id 的
    提交（本地化安全增强，见 app_event.py）；
  - 新增 ``stats()`` 可观测：sent / dropped_voice / dropped_invalid /
    dropped_full / send_errors，便于审计「为什么事件没生效」。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from .app_command import AppCommand
from .app_event import AppEvent, EventCategory, validate_thread_op

DEFAULT_QUEUE_CAPACITY = 32768  # 对齐 app.rs THREAD_EVENT_CHANNEL_CAPACITY


class AppEventSender:
    """类型化事件发送器。"""

    def __init__(self, sink: Optional[Callable[[AppEvent], Any]] = None,
                 *, logger: Optional[Callable[[str, str], None]] = None,
                 capacity: int = DEFAULT_QUEUE_CAPACITY):
        self._sink = sink
        self._logger = logger or (lambda level, msg: None)
        self._queue: deque = deque()
        self._capacity = max(1, int(capacity))
        self._voice_only = threading.Event()
        self._lock = threading.RLock()
        self._sent = 0
        self._dropped_voice = 0
        self._dropped_invalid = 0
        self._dropped_full = 0
        self._send_errors = 0
        self._inbound_log: List[Dict[str, Any]] = []

    # ------------------------------------------------------------ voice_only
    def set_voice_only(self, enabled: bool) -> None:
        if enabled:
            self._voice_only.set()
        else:
            self._voice_only.clear()

    @property
    def voice_only(self) -> bool:
        return self._voice_only.is_set()

    # ------------------------------------------------------------ send
    def send(self, event: AppEvent) -> bool:
        """对齐上游 ``send``；返回是否真正送达。

        步骤 1→2→3 的顺序**不可重排**，见模块头。
        """
        # (1) 白名单：不匹配直接丢弃，且不写 inbound 日志
        if self._voice_only.is_set() and not event.is_voice_allowed():
            with self._lock:
                self._dropped_voice += 1
            return False

        # (1.5) 本地化增强：线程操作缺 id 一律拒绝，绝不"尽力投递"
        problem = validate_thread_op(event)
        if problem:
            with self._lock:
                self._dropped_invalid += 1
            self._logger("error", problem)
            return False

        # (2) inbound 日志：Ops 不双记
        if event.is_loggable_inbound():
            with self._lock:
                self._inbound_log.append(event.to_dict())

        # (2.5) 本地化增强：有界队列，满则拒绝而非无限增长
        with self._lock:
            if len(self._queue) >= self._capacity:
                self._dropped_full += 1
                self._logger("error", "app event queue full; event dropped")
                return False
            self._queue.append(event)

        # (3) 发送失败吞掉并记日志
        if self._sink is None:
            return True  # 已入队，无下游消费者（测试/离线场景）
        try:
            self._sink(event)
            with self._lock:
                self._sent += 1
            return True
        except Exception as exc:  # noqa: BLE001 - 对齐上游吞错语义
            with self._lock:
                self._send_errors += 1
            self._logger("error", f"failed to send event: {exc!r}")
            return False

    def drain(self, limit: Optional[int] = None) -> List[AppEvent]:
        """本地化：取出排队事件（供测试与离线重放）。"""
        with self._lock:
            n = len(self._queue) if limit is None else min(limit, len(self._queue))
            return [self._queue.popleft() for _ in range(n)]

    # ------------------------------------------------------------ 便捷方法
    def interrupt(self) -> bool:
        return self.send(AppEvent.codex_op(AppCommand.interrupt()))

    def compact(self) -> bool:
        return self.send(AppEvent.codex_op(AppCommand.compact()))

    def set_thread_name(self, name: str) -> bool:
        return self.send(AppEvent.codex_op(AppCommand.set_thread_name(name)))

    def review(self, target: str) -> bool:
        return self.send(AppEvent.codex_op(AppCommand.review(target)))

    def run_user_shell_command(self, command: str) -> bool:
        return self.send(AppEvent.codex_op(
            AppCommand.run_user_shell_command(command)))

    def exec_approval(self, thread_id: str, id: str,
                      decision: str, turn_id: Optional[str] = None) -> bool:
        return self.send(AppEvent.submit_thread_op(
            thread_id, AppCommand.exec_approval(id, decision, turn_id)))

    def patch_approval(self, thread_id: str, id: str,
                       decision: str) -> bool:
        return self.send(AppEvent.submit_thread_op(
            thread_id, AppCommand.patch_approval(id, decision)))

    def request_permissions_response(self, thread_id: str, id: str,
                                     response: Dict[str, Any]) -> bool:
        """本地化：上游用专用 AppCommand 构造器，此处用 payload 保留语义。"""
        from .app_command import CommandKind
        return self.send(AppEvent.submit_thread_op(
            thread_id, AppCommand(CommandKind.REQUEST_PERMISSIONS_RESPONSE,
                                  {"id": id, "response": response})))

    def user_input_answer(self, thread_id: str, id: str,
                          response: Dict[str, Any]) -> bool:
        from .app_command import CommandKind
        return self.send(AppEvent.submit_thread_op(
            thread_id, AppCommand(CommandKind.USER_INPUT_ANSWER,
                                  {"id": id, "response": response})))

    def resolve_elicitation(self, thread_id: str, server_name: str,
                            request_id: str, decision: str,
                            content: Optional[Dict[str, Any]] = None,
                            meta: Optional[Dict[str, Any]] = None) -> bool:
        from .app_command import CommandKind
        return self.send(AppEvent.submit_thread_op(
            thread_id, AppCommand(CommandKind.RESOLVE_ELICITATION, {
                "server_name": server_name, "request_id": request_id,
                "decision": decision, "content": content, "meta": meta})))

    def resolve_user_verification(self, thread_id: str, server_name: str,
                                  request_id: str,
                                  response: Dict[str, Any]) -> bool:
        from .app_command import CommandKind
        return self.send(AppEvent.submit_thread_op(
            thread_id, AppCommand(CommandKind.RESOLVE_USER_VERIFICATION, {
                "server_name": server_name, "request_id": request_id,
                "response": response})))

    # ------------------------------------------------------------ 可观测
    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "sent": self._sent,
                "queued": len(self._queue),
                "inbound_logged": len(self._inbound_log),
                "dropped_voice": self._dropped_voice,
                "dropped_invalid": self._dropped_invalid,
                "dropped_full": self._dropped_full,
                "send_errors": self._send_errors,
                "capacity": self._capacity,
            }

    def inbound_log(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._inbound_log)
