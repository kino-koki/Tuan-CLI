"""与 Codex ``tui/src/activation_key_guard.rs`` 对齐的激活键抑制器。

上游模块头（功能性契约，逐条对齐）：

    "Keep a held activation key from triggering another action.
    Terminals with enhanced keyboard reporting distinguish a held `Repeat`
    from a fresh `Press`. A view transition on a press-only terminal can use
    a bounded window to block ambiguous presses."

即：一次「按下某个激活键触发视图切换」之后，在有限时间窗内把**同一个
物理键**的后续事件吞掉，避免按住不放导致连续切换视图。

本地化修改（如实列出）：
  - 上游 ``Instant`` -> Python ``time.monotonic()`` 浮点秒（可注入时钟，
    便于确定性测试，不让回归依赖墙上时间）；
  - ``is_same_physical_key`` 用 ``KeyBinding`` 的规范化表示比较，忽略
    shift 与大小写差异（对齐上游「物理键」语义，本地化增强）；
  - 新增 ``suppression_reason()`` 可观测接口，供安全审计记录「为何吞掉
    一次按键」，不改变裁决行为。

许可：Apache-2.0（NOTICE 第 11 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

# 逐值对齐上游常量
INITIAL_GUARD_SECONDS = 1.0
LEGACY_REPEAT_GUARD_SECONDS = 1.0


class KeyEventKind(str, Enum):
    """对齐 crossterm ``KeyEventKind``。"""

    PRESS = "press"
    REPEAT = "repeat"
    RELEASE = "release"


class ActivationKeySuppression(str, Enum):
    """对齐上游枚举。"""

    VIEW_TRANSITION = "view_transition"
    REPORTED_REPEATS = "reported_repeats"


def normalize_physical_key(spec: str) -> str:
    """把键位规格归一化成「物理键」身份，用于跨修饰键比较。

    本地化增强：去掉 ``shift-``（按下 A 与 a 是同一个物理键）、统一下划线
    与大小写、去掉 ``keypad-`` 前缀。纯展示用的键位提示不应传进来。
    """
    s = (spec or "").strip().lower().replace("_", "-")
    parts = [p for p in s.split("-") if p and p != "shift"
             and p != "keypad"]
    return "-".join(parts)


class KeyBinding:
    """最小键位绑定（对齐上游 ``key_hint::KeyBinding`` 的用途）。"""

    __slots__ = ("spec",)

    def __init__(self, spec: str):
        self.spec = spec

    def is_same_physical_key(self, other: "KeyBinding") -> bool:
        return normalize_physical_key(self.spec) == \
               normalize_physical_key(other.spec)

    def __repr__(self) -> str:  # pragma: no cover
        return f"KeyBinding({self.spec!r})"


@dataclass
class _ConsumeResult:
    suppressed: bool
    reason: str = ""


class ActivationKeyGuard:
    """逐状态对齐上游 ``ActivationKeyGuard``。

    ``new_at(key, now, reported_repeats_only)``：
      - ``block_until = now + INITIAL_GUARD``（checked_add 溢出回退 now）；
      - ``legacy_repeat_fallback = not reported_repeats_only``；
      - ``active = True``。

    ``consume(key, kind)`` 的完整分支（与上游一一对应）：
      1. 非 active -> False；
      2. 同物理键 + Release -> 失活并吞掉（True）；
      3. 同物理键 + 无 legacy 回退 + Press -> 失活、不吞（False）；
      4. 同物理键 + Repeat，或 now <= block_until -> 延长窗口并吞掉（True）；
      5. 同物理键但窗口已过 -> 失活、不吞（False）；
      6. 别的键 + Press/Repeat -> 失活、不吞（False）。
    """

    __slots__ = ("_key", "_block_until", "_legacy_repeat_fallback",
                 "_active", "_clock", "_last_result")

    def __init__(self, key: KeyBinding, *, now: Optional[float] = None,
                 reported_repeats_only: bool = False,
                 clock: Optional[Callable[[], float]] = None):
        self._clock = clock or time.monotonic
        t = self._clock() if now is None else now
        self._key = key
        # 对齐 checked_add：溢出/异常时回退到 now
        try:
            self._block_until = t + INITIAL_GUARD_SECONDS
        except (OverflowError, TypeError):
            self._block_until = t
        self._legacy_repeat_fallback = not reported_repeats_only
        self._active = True
        self._last_result = _ConsumeResult(False)

    @classmethod
    def new_at(cls, key: KeyBinding, now: float,
               reported_repeats_only: bool,
               clock: Optional[Callable[[], float]] = None) -> "ActivationKeyGuard":
        """对齐上游构造器签名（确定性时间入口）。"""
        return cls(key, now=now, reported_repeats_only=reported_repeats_only,
                   clock=clock)

    def consume(self, key: KeyBinding, kind: KeyEventKind,
                *, now: Optional[float] = None) -> bool:
        """消费一次按键事件；返回 True 表示**应被抑制**。"""
        return self.consume_at(key, kind,
                               self._clock() if now is None else now)

    def consume_at(self, key: KeyBinding, kind: KeyEventKind,
                   now: float) -> bool:
        if not self._active:
            self._last_result = _ConsumeResult(False, "inactive")
            return False

        same = self._key.is_same_physical_key(key)
        if same:
            if kind is KeyEventKind.RELEASE:
                self._active = False
                self._last_result = _ConsumeResult(True, "release_clears_guard")
                return True
            # 无 legacy 回退时，只有 Reported Repeat 才算「按住」
            if not self._legacy_repeat_fallback and kind is KeyEventKind.PRESS:
                self._active = False
                self._last_result = _ConsumeResult(
                    False, "reported_repeats_only_fresh_press")
                return False
            if kind is KeyEventKind.REPEAT or now <= self._block_until:
                try:
                    repeat_until = now + LEGACY_REPEAT_GUARD_SECONDS
                except (OverflowError, TypeError):
                    repeat_until = now
                self._block_until = max(self._block_until, repeat_until)
                self._last_result = _ConsumeResult(
                    True, "reported_repeat" if kind is KeyEventKind.REPEAT
                    else "within_initial_guard")
                return True
            self._active = False
            self._last_result = _ConsumeResult(False, "guard_window_expired")
            return False

        if kind in (KeyEventKind.PRESS, KeyEventKind.REPEAT):
            self._active = False
            self._last_result = _ConsumeResult(False, "different_key_ends_guard")
        return False

    def is_active(self) -> bool:
        """对齐上游 ``is_active(self)``（按值消费语义）。"""
        return self._active

    def suppression_reason(self) -> str:
        """本地化增强：最近一次裁决的原因，供审计/调试；不改变行为。"""
        return self._last_result.reason

    def block_until(self) -> float:
        """本地化增强：当前抑制窗口终点（可观测）。"""
        return self._block_until
