"""与 Codex ``tui/src/copy_input_guard.rs`` 对齐的复制输入守卫。

上游全文只有一句契约：

    "Keep queued submissions paused until the transcript selector releases
    its owner."

实现是 RAII：``CopyInputGuard`` 持有事件发送器，**析构时**（正常或异常）
发出 ``AppEvent::TranscriptCopyClosed``，从而解除排队提交的暂停。

本地化修改（如实列出）：
  - Rust ``Drop`` -> Python 上下文管理器 ``__enter__/__exit__`` + 显式
    ``close()`` + ``__del__`` 兜底。**异常路径也必须释放**，这是上游
    Drop 的核心语义，不能只做 happy path；
  - 发送器是可调用对象而非 ``AppEventSender``；发送失败时**吞掉异常**
    （析构里抛异常会掩盖原始异常，且 Python 的 ``__exit__`` 返回 True
    会吞掉用户异常 —— 这里刻意不吞用户异常，只吞发送器异常）；
  - 新增 ``released`` / ``events`` 可观测状态与幂等保证（重复 close
    只发一次）。对齐上游「一次 guard 对应一次释放」。

许可：Apache-2.0（NOTICE 第 11 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from typing import Callable, List, Optional

# 对齐上游事件名
TRANSCRIPT_COPY_CLOSED = "TranscriptCopyClosed"


class CopyInputGuard:
    """持有一个发送器，退出作用域时发出 ``TranscriptCopyClosed``。

    用法（对齐 Rust 的 scope guard）::

        with CopyInputGuard(sender) as guard:
            ...  # 排队提交在此期间保持暂停
        # 此处 guaranteed 已发出释放事件，即使上面抛了异常
    """

    __slots__ = ("_sender", "_released", "_events", "_last_error")

    def __init__(self, sender: Callable[[str], object]):
        if not callable(sender):
            raise TypeError("CopyInputGuard 需要可调用的发送器")
        self._sender = sender
        self._released = False
        self._events: List[str] = []

    # ------------------------------------------------------------ 生命周期
    def __enter__(self) -> "CopyInputGuard":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # 关键：绝不通过返回 True 吞掉用户异常；只保证释放动作发生。
        self.release()
        return False

    def close(self) -> None:
        """显式释放（与 ``with`` 等价）。"""
        self.release()

    def release(self) -> bool:
        """幂等发出释放事件，返回本次是否真的发出。

        发送器异常被吞掉并**仍然标记为已释放** —— 否则一次失败的释放
        会让排队提交永久暂停（fail-open 到更糟的状态）。异常内容不进
        事件流，但通过 ``last_error`` 可观测。
        """
        if self._released:
            return False
        self._released = True
        try:
            self._sender(TRANSCRIPT_COPY_CLOSED)
            self._events.append(TRANSCRIPT_COPY_CLOSED)
        except Exception as err:  # noqa: BLE001 - 析构路径绝不抛
            self._last_error = repr(err)
            self._events.append(f"{TRANSCRIPT_COPY_CLOSED}:send_failed")
        return True

    def __del__(self):  # pragma: no cover - 解释器退出时序不确定
        try:
            self.release()
        except Exception:
            pass

    # ------------------------------------------------------------ 可观测
    @property
    def released(self) -> bool:
        return self._released

    @property
    def events(self) -> List[str]:
        return list(self._events)

    @property
    def last_error(self) -> Optional[str]:
        """本地化增强：发送器失败原因（不进事件流）。"""
        return getattr(self, "_last_error", None)


class QueuedSubmissions:
    """本地化增强：把「暂停/恢复排队提交」显式建模，便于测试上游语义。

    上游由 app 层维护这个状态；这里给一个最小实现，让 guard 的契约
    可以被独立回归，而不需要整条 app 事件链。
    """

    __slots__ = ("_paused", "_count")

    def __init__(self):
        self._paused = True
        self._count = 0

    def pause(self) -> None:
        self._paused = True

    def on_event(self, event: str) -> None:
        if event == TRANSCRIPT_COPY_CLOSED:
            self._paused = False
            self._count += 1

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def resume_count(self) -> int:
        return self._count


def guard_with(submissions: "QueuedSubmissions") -> CopyInputGuard:
    """便利构造：guard 释放时自动恢复排队提交。"""
    return CopyInputGuard(submissions.on_event)
