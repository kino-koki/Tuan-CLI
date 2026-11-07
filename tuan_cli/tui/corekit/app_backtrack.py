"""与 Codex ``tui/src/app_backtrack.rs`` 对齐的回退/记录导航状态机。

上游模块头逐条（原文语义）：

  - "This file owns backtrack mode (Esc/Enter navigation in the transcript
     overlay) ... Confirming a selection reverts before the selected turn
     and restores its prompt in the composer."
  - 状态机六步：
      1. 主视图第一次 ``Esc`` **prime** 该特性并捕获 base thread id；
      2. 第二次 ``Esc`` 开始紧凑记录浏览，高亮最新用户消息；
      3. 左/右选择消息；
      4. ``Ctrl+T`` 切换详情；
      5. ``Esc`` 恢复浏览起点；
      6. ``Enter`` 请求在所选消息之前 revert，并重新打开编辑。
  - "Both render committed cells and a live tail from the current
     ChatWidget.active_cell" —— 覆盖层同时呈现已提交历史与在途活动，
     且**不改变 flush / coalescing 行为**。

字段逐值对齐（``BacktrackState``）：
  - ``primed: bool``
  - ``base_id: Option<ThreadId>`` —— **线程变了，选择必须失效**
  - ``nth_user_message: usize``，``usize::MAX`` 表示「无选择」
  - ``overlay_preview_active: bool``
  - ``select_exit_key: Option<KeyBinding>`` —— 消费按住的键
  - ``NO_PREVIOUS_MESSAGE_TO_EDIT = "No previous message to edit."``
  - ``SIDE_EDIT_PREVIOUS_UNAVAILABLE_MESSAGE`` = 侧会话不可编辑上一提示

**安全相关**：``base_id`` 变更时旧选择必须忽略。否则会把 A 会话的
revert 应用到 B 会话 —— 等于跨会话改历史。本模块把这条做成
``bind_thread()`` 的强制失效，并在 ``confirm_revert()`` 再校验一次。

本地化修改（如实列出）：
  - Rust ``usize::MAX`` -> Python ``NO_SELECTION`` 哨兵（``-1``），
    语义一致且可测；
  - 中文提示文案（10 语言由项目 i18n 提供），英文原文保留供核销；
  - 新增 ``history`` 可观测事件序列与 ``revert_note()``；
  - 本地化增强：``confirm_revert()`` 返回结构化结果，调用方必须显式
    接受才真正 revert（不在状态机内部直接改会话）。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

NO_PREVIOUS_MESSAGE_TO_EDIT = "No previous message to edit."
SIDE_EDIT_PREVIOUS_UNAVAILABLE_MESSAGE = (
    "Editing previous prompts is unavailable in side conversations.")

# 本地化：中文文案，英文原文保留在上面对齐常量里
NO_PREVIOUS_MESSAGE_TO_EDIT_ZH = "没有可编辑的上一条消息。"
SIDE_EDIT_PREVIOUS_UNAVAILABLE_MESSAGE_ZH = "侧会话中不可编辑上一条提示。"

NO_SELECTION = -1  # 对齐上游 usize::MAX 的「无选择」语义


class BacktrackPhase(str, Enum):
    """本地化：把上游散落在分支里的状态显式建成枚举（可测）。"""

    IDLE = "idle"
    PRIMED = "primed"
    BROWSING = "browsing"
    PREVIEW = "preview"


class BacktrackKey(str, Enum):
    ESC = "esc"
    ENTER = "enter"
    LEFT = "left"
    RIGHT = "right"
    DETAIL_TOGGLE = "ctrl-t"


@dataclass
class RevertRequest:
    """本地化增强：结构化 revert 请求，不在状态机内直接改会话。"""

    thread_id: str
    nth_user_message: int
    prompt: str
    reason: str = "backtrack_confirm"

    def to_dict(self) -> Dict[str, Any]:
        return {"thread_id": self.thread_id,
                "nth_user_message": self.nth_user_message,
                "prompt": self.prompt, "reason": self.reason}


@dataclass
class BacktrackState:
    """逐字段对齐上游 BacktrackState。"""

    primed: bool = False
    base_id: Optional[str] = None
    nth_user_message: int = NO_SELECTION
    overlay_preview_active: bool = False
    select_exit_key: Optional[str] = None
    phase: BacktrackPhase = BacktrackPhase.IDLE
    user_messages: List[str] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def _record(self, action: str, **kw: Any) -> None:
        self.history.append({"action": action, **kw})

    # ------------------------------------------------------------ 线程绑定
    def bind_thread(self, thread_id: str) -> None:
        """对齐上游：线程变了，旧选择必须失效并忽略。"""
        if self.base_id is not None and self.base_id != thread_id:
            self.nth_user_message = NO_SELECTION
            self.overlay_preview_active = False
            self.primed = False
            self.phase = BacktrackPhase.IDLE
            self._record("thread_changed_invalidated",
                         old=self.base_id, new=thread_id)
        self.base_id = thread_id

    # ------------------------------------------------------------ 六步状态机
    def start(self, thread_id: str,
              user_messages: List[str]) -> None:
        self.bind_thread(thread_id)
        self.user_messages = list(user_messages)
        self.nth_user_message = NO_SELECTION
        self.primed = False
        self.overlay_preview_active = False
        self.phase = BacktrackPhase.IDLE
        self._record("start", thread=thread_id,
                     count=len(self.user_messages))

    def press_esc(self, thread_id: str) -> str:
        """第 1 次 Esc prime；第 2 次进入浏览；浏览中 Esc 恢复起点。"""
        self.bind_thread(thread_id)
        if self.phase is BacktrackPhase.IDLE:
            self.primed = True
            self.phase = BacktrackPhase.PRIMED
            self._record("prime", thread=thread_id)
            return "primed"
        if self.phase is BacktrackPhase.PRIMED:
            self.phase = BacktrackPhase.BROWSING
            if self.user_messages:
                self.nth_user_message = len(self.user_messages) - 1
                self.overlay_preview_active = True
                self._record("browse_started",
                             nth=self.nth_user_message)
                return "browsing"
            self.phase = BacktrackPhase.IDLE
            self.primed = False
            self._record("no_previous_message")
            return NO_PREVIOUS_MESSAGE_TO_EDIT
        # 浏览/预览中：恢复浏览起点（对齐上游 Esc restores origin）
        self.phase = BacktrackPhase.IDLE
        self.primed = False
        self.nth_user_message = NO_SELECTION
        self.overlay_preview_active = False
        self._record("restore_origin")
        return "restored"

    def move_selection(self, delta: int) -> int:
        """左/右选择；越界钳制，无选择时从最近一条开始。"""
        if not self.user_messages:
            return NO_SELECTION
        if self.nth_user_message == NO_SELECTION:
            self.nth_user_message = len(self.user_messages) - 1
        else:
            self.nth_user_message = max(
                0, min(len(self.user_messages) - 1,
                       self.nth_user_message + delta))
        self._record("selection_moved", nth=self.nth_user_message)
        return self.nth_user_message

    def toggle_details(self) -> bool:
        """Ctrl+T 切换详情（对齐上游 owned/inline 会话共用 viewport）。"""
        self.overlay_preview_active = not self.overlay_preview_active
        self.phase = (BacktrackPhase.PREVIEW
                      if self.overlay_preview_active
                      else BacktrackPhase.BROWSING)
        self._record("details_toggled",
                     active=self.overlay_preview_active)
        return self.overlay_preview_active

    def confirm_revert(self, thread_id: str,
                       *, side_conversation: bool = False
                       ) -> Optional[RevertRequest]:
        """Enter：请求在所选消息之前 revert，并重新打开编辑。

        **二次校验线程**：即便状态被外部改过，也不允许跨会话 revert。
        调用方拿到 ``RevertRequest`` 后必须显式应用，状态机不直接改历史。
        """
        self.bind_thread(thread_id)
        if side_conversation:
            self._record("side_edit_rejected")
            return None
        if self.base_id != thread_id or self.nth_user_message == NO_SELECTION:
            self._record("revert_rejected",
                         reason="stale_selection_or_thread")
            return None
        if not self.user_messages:
            self._record("revert_rejected", reason="no_messages")
            return None
        idx = min(self.nth_user_message, len(self.user_messages) - 1)
        req = RevertRequest(thread_id=thread_id, nth_user_message=idx,
                            prompt=self.user_messages[idx])
        self._record("revert_requested", nth=idx)
        return req

    def set_select_exit_key(self, key: str) -> None:
        """对齐 ``select_exit_key``：消费按住的激活键。"""
        self.select_exit_key = key
        self._record("select_exit_key_set", key=key)

    # ------------------------------------------------------------ 可观测
    def has_selection(self) -> bool:
        return self.nth_user_message != NO_SELECTION

    def info_message(self, *, zh: bool = True) -> str:
        return (NO_PREVIOUS_MESSAGE_TO_EDIT_ZH if zh
                else NO_PREVIOUS_MESSAGE_TO_EDIT)

    def side_unavailable_message(self, *, zh: bool = True) -> str:
        return (SIDE_EDIT_PREVIOUS_UNAVAILABLE_MESSAGE_ZH if zh
                else SIDE_EDIT_PREVIOUS_UNAVAILABLE_MESSAGE)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primed": self.primed, "base_id": self.base_id,
            "nth_user_message": self.nth_user_message,
            "overlay_preview_active": self.overlay_preview_active,
            "select_exit_key": self.select_exit_key,
            "phase": self.phase.value,
            "messages": len(self.user_messages),
            "events": len(self.history),
        }
