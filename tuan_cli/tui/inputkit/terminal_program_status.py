"""与 Codex ``tui/src/terminal_program_status.rs`` 对齐的终端生命周期状态。

上游模块头（功能性契约）：

    "Emits Codex lifecycle state through terminal status protocols.
    OSC 7501 reports lifecycle state and blocking reasons to terminal
    sessions. Direct iTerm2 sessions also receive OSC 21337 status,
    including bounded activity text. The process-wide cache is used for
    exit, panic, and terminal handoff cleanup."

对齐的逐值/逐分支事实：
  - ``MIN_VTE_VERSION_WITH_SAFE_OSC = 5400``（VTE 0.54 起安全忽略未知 OSC）；
  - ``ProgramStatus``：Idle / Working / Blocked(kind) / Done / Error；
  - ``ProgramStatusKind``：Permission / Question / Auth；
  - iTerm label：Idle/Done/Error -> ``Idle``，Working -> ``Working``，
    Blocked -> ``Waiting``；
  - iTerm indicator：``#00d75f`` / ``#ff9500`` / ``#5f87ff``；
  - protocol state：idle / working / blocked / done / error；
  - ``SessionStatusState.update`` 去重：status 与 detail 都相同就不重复写；
    **写终端与改缓存必须原子**（上游用 Mutex 防 panic-hook 与 draw 交错）；
  - ``invalidate()`` 只把非 Cleared 状态改成 Invalidated，使切换回进程后
    重新发一次；
  - ``sanitize_iterm_session_detail`` 转义 ``;`` 与 ``\\``（防 OSC 注入）；
  - 支持判定：stdout 必须是 TTY；VTE 版本 >= 5400 或未知后端；
    ``STY`` 存在（screen 活跃）时禁用 iTerm 状态。

本地化修改（如实列出）：
  - 不用 crossterm ``execute!``，改为生成 OSC 字节并交给可注入 writer；
    **默认 writer 是 no-op**，避免库被 import 就往用户终端写转义序列；
  - 进程级单例用模块级状态 + ``threading.RLock``（对齐 Mutex 语义）；
  - 新增 ``support_for()`` 纯函数，让能力探测可确定性测试；
  - detail 默认长度上限 256 并做控制字符剥离（本地化增强：上游只做
    标题净化 + 转义，这里额外防 OSC/BEL 注入）。**不放松任何转义**。

安全注记：OSC 序列会被终端解释执行，detail 必须当作不可信输入处理；
本项目默认不发射，只有显式 ``configure(writer=...)`` 且 TTY 时才发。

许可：Apache-2.0（NOTICE 第 11 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Tuple

MIN_VTE_VERSION_WITH_SAFE_OSC = 5400
MAX_DETAIL_CHARS = 256  # 本地化增强（上游无显式上限）

_PROTOCOL_STATES = {
    "idle": "idle", "working": "working", "blocked": "blocked",
    "done": "done", "error": "error",
}


class ProgramStatusKind(str, Enum):
    PERMISSION = "permission"
    QUESTION = "question"
    AUTH = "auth"


@dataclass(frozen=True)
class ProgramStatus:
    """对齐上游枚举；Blocked 携带 kind（Python 用字段而非 Rust 变体）。"""

    state: str
    kind: Optional[ProgramStatusKind] = None

    @classmethod
    def idle(cls) -> "ProgramStatus":
        return cls("idle")

    @classmethod
    def working(cls) -> "ProgramStatus":
        return cls("working")

    @classmethod
    def blocked(cls, kind: ProgramStatusKind) -> "ProgramStatus":
        return cls("blocked", kind)

    @classmethod
    def done(cls) -> "ProgramStatus":
        return cls("done")

    @classmethod
    def error(cls) -> "ProgramStatus":
        return cls("error")

    def iterm_label(self) -> str:
        if self.state in ("idle", "done", "error"):
            return "Idle"
        if self.state == "working":
            return "Working"
        return "Waiting"

    def iterm_indicator(self) -> str:
        if self.state in ("idle", "done", "error"):
            return "#00d75f"
        if self.state == "working":
            return "#ff9500"
        return "#5f87ff"

    def protocol_state(self) -> str:
        return _PROTOCOL_STATES.get(self.state, "idle")


class CachedStatus(str, Enum):
    CLEARED = "cleared"
    REPORTED = "reported"
    INVALIDATED = "invalidated"


@dataclass
class TerminalProgramStatusSupport:
    """对齐上游结构体；逐字段语义一致。"""

    osc_7501: bool = False
    osc_21337: bool = False


def support_for(stdout_is_terminal: bool,
                vte_version: Optional[int],
                screen_active: bool,
                *, iterm_capable: bool = True) -> TerminalProgramStatusSupport:
    """纯函数能力探测（对齐上游 ``terminal_program_status_support``）。

    - osc_7501：stdout 是 TTY 且（无 VTE 后端 / VTE >= 5400）；
    - osc_21337：在 osc_7501 基础上，还需非 screen 环境且终端支持 iTerm。
    """
    osc_7501 = stdout_is_terminal and (
        vte_version is None or vte_version >= MIN_VTE_VERSION_WITH_SAFE_OSC)
    osc_21337 = osc_7501 and (not screen_active) and iterm_capable
    return TerminalProgramStatusSupport(osc_7501, osc_21337)


def sanitize_terminal_title(text: str) -> str:
    """本地化的标题净化：剥离控制字符 / OSC / BEL / CSI，截断长度。"""
    out = []
    for ch in text[:MAX_DETAIL_CHARS]:
        cp = ord(ch)
        if ch in ("\x07", "\x1b", "\x9b") or cp < 32 or cp == 127:
            continue
        out.append(ch)
    return "".join(out)


def sanitize_iterm_session_detail(detail: str) -> str:
    """对齐上游：先净化标题，再转义 ``;`` 与 ``\\``。"""
    clean = sanitize_terminal_title(detail)
    escaped = []
    for ch in clean:
        if ch in (";", "\\"):
            escaped.append("\\")
        escaped.append(ch)
    return "".join(escaped)


def _osc7501(status: ProgramStatus, detail: str,
             emit_iterm: bool) -> str:
    """生成 OSC 7501 / 21337 字节（本地化：字符串而非 crossterm 命令）。

    结构对齐上游协议名与字段；**detail 已转义**，绝不含裸 BEL/OSC。
    """
    base = (f"\x1b]7501;state={status.protocol_state()};"
            f"label={status.iterm_label()};"
            f"indicator={status.iterm_indicator()}")
    if status.kind is not None:
        base += f";reason={status.kind.value}"
    seq = base + "\x07"
    if emit_iterm:
        seq += (f"\x1b]21337;status={status.iterm_label()};"
                f"detail={detail}\x07")
    return seq


class _SessionStatusState:
    """进程级缓存（对齐上游静态单例 + Mutex）。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._status = CachedStatus.CLEARED
        self._detail = ""
        self._emits = 0

    def update(self, status: CachedStatus, detail: str,
               emit: Callable[[], None]) -> bool:
        """写终端与改缓存在同一把锁内完成；返回本次是否真的发射。"""
        with self._lock:
            if self._status == status and self._detail == detail:
                return False
            emit()  # 本地化：emit 异常时不改缓存，下次重试
            self._status = status
            self._detail = detail
            self._emits += 1
            return True

    def invalidate(self) -> None:
        with self._lock:
            if self._status is not CachedStatus.CLEARED:
                self._status = CachedStatus.INVALIDATED

    def snapshot(self) -> Tuple[str, str, int]:
        with self._lock:
            return self._status.value, self._detail, self._emits


_SESSION_STATUS_STATE = _SessionStatusState()
_writer: Optional[Callable[[str], None]] = None
_support: Optional[TerminalProgramStatusSupport] = None


def configure(*, writer: Optional[Callable[[str], None]] = None,
              support: Optional[TerminalProgramStatusSupport] = None) -> None:
    """显式启用（安全默认：不 configure 就完全不发射）。

    ``writer`` 通常传 ``sys.stdout.write``；``support`` 可由调用方按
    ``support_for()`` 结果注入，避免库自己探测环境产生副作用。
    """
    global _writer, _support
    _writer = writer
    _support = support


def current_support() -> TerminalProgramStatusSupport:
    """未 configure 时按真实环境探测（只读，不写终端）。"""
    if _support is not None:
        return _support
    try:
        import sys
        is_tty = bool(sys.stdout.isatty())
    except Exception:  # noqa: BLE001
        is_tty = False
    return support_for(is_tty, None, os.environ.get("STY") is not None)


def set_terminal_program_status(status: ProgramStatus,
                                detail: Optional[str] = None) -> bool:
    """对齐上游入口；返回是否发射（未启用/不支持/去重命中都返回 False）。"""
    support = current_support()
    if not support.osc_7501 or _writer is None:
        return False
    clean = sanitize_iterm_session_detail(detail or "") \
        if support.osc_21337 else ""
    seq = _osc7501(status, clean, support.osc_21337)

    def emit() -> None:
        _writer(seq)  # type: ignore[misc]

    return _SESSION_STATUS_STATE.update(CachedStatus.REPORTED, clean, emit)


def clear_terminal_program_status() -> bool:
    """对齐上游入口：清除并缓存 Cleared。"""
    support = current_support()
    if not support.osc_7501 or _writer is None:
        return False
    seq = "\x1b]7501;state=idle;label=Idle;indicator=#00d75f\x07"
    if support.osc_21337:
        seq += "\x1b]21337;status=Idle;detail=\x07"

    def emit() -> None:
        _writer(seq)  # type: ignore[misc]

    return _SESSION_STATUS_STATE.update(CachedStatus.CLEARED, "", emit)


def invalidate_terminal_program_status() -> None:
    """对齐上游：终端被别的进程接管后，使下次 draw 重新发状态。"""
    _SESSION_STATUS_STATE.invalidate()


def session_status_snapshot() -> Tuple[str, str, int]:
    """本地化增强：可观测缓存状态（测试/审计用）。"""
    return _SESSION_STATUS_STATE.snapshot()


def _reset_for_tests() -> None:
    """仅供测试：把模块级状态恢复初值，避免跨用例污染。"""
    global _writer, _support
    _writer = None
    _support = None
    _SESSION_STATUS_STATE._status = CachedStatus.CLEARED
    _SESSION_STATUS_STATE._detail = ""
    _SESSION_STATUS_STATE._emits = 0
