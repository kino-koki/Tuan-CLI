"""与 Codex ``tui/src/chatwidget.rs`` 对齐的聊天界面状态契约。

上游模块头逐条（原文语义）：

  - "`ChatWidget` consumes protocol events, builds and updates history
     cells, and drives rendering for both the main viewport and overlay UIs."
  - "The UI has both committed transcript cells (finalized `HistoryCell`s)
     and an in-flight active cell (`ChatWidget.active_cell`) that can mutate
     in place while streaming ... The transcript overlay renders committed
     cells plus a cached, render-only live tail derived from the current
     active cell so in-flight tool calls are visible immediately."
  - "The cache key is designed to change when the active cell mutates in
     place or when its transcript output is time-dependent so the overlay
     can refresh its cached tail without rebuilding it on every draw."
  - **双生命周期忙状态**（本轮最值钱的一条）：
      "The bottom pane exposes a single 'task running' indicator that
       drives the spinner and interrupt hints. This module treats that
       indicator as derived UI-busy state: it is set while an agent turn
       is in progress and while MCP server startup is in progress.
       Those lifecycles are tracked independently (`agent_turn_running`
       and `mcp_startup_status`) and synchronized via
       `update_task_running_state`."

若把这两个状态压成一个布尔，MCP 启动期间界面会误报「空闲」，用户可能
重复提交或以为工具已挂 —— 这是真实的状态机缺陷。本模块把它做成可测的
**派生**状态：任一为真则 task_running 为真。

逐值常量：
  - ``DEFAULT_MODEL_DISPLAY_NAME = "loading"``
  - ``DEFAULT_STATUS_LINE_ITEMS = ["model-with-reasoning", "current-dir",
    "thread-name"]``（3 项）
  - ``AMBIENT_PET_WRAP_GAP_COLUMNS = 2``
  - ``MAX_TRANSCRIPT_BYTES = 1024``
  - ``MAX_REPLAY_TRANSCRIPT_CELLS = MAX_PENDING_TRANSCRIPT_CELLS + 2``
    （上游 realtime 子模块，值依赖另一个常量，这里如实记录表达式）

本地化修改（如实列出）：
  - ratatui 渲染 / HistoryCell -> 字符串列表 + 可注入 render；
  - 中文状态栏文案（项目 i18n），三项语义不变；
  - ``MAX_REPLAY_TRANSCRIPT_CELLS`` 的上游依赖常量本地**不存在**，
    因此取 `MAX_PENDING_TRANSCRIPT_CELLS = 8` 的显式本地默认并算出 10，
    文档如实标注这是本地化取值而非逐值复制；
  - 新增 ``live_tail_key()`` 的确定性实现与 ``stats()`` 可观测；
  - 本地化增强：提交 cell 时做 **MAX_TRANSCRIPT_BYTES 截断**且保留
    尾部（对齐上游 realtime 的 transcript 截断意图）。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

DEFAULT_MODEL_DISPLAY_NAME = "loading"
DEFAULT_STATUS_LINE_ITEMS = (
    "model-with-reasoning", "current-dir", "thread-name",
)
AMBIENT_PET_WRAP_GAP_COLUMNS = 2
MAX_TRANSCRIPT_BYTES = 1024

# 上游 MAX_REPLAY_TRANSCRIPT_CELLS = MAX_PENDING_TRANSCRIPT_CELLS + 2；
# 后者在 realtime 子模块，本项目未实现实时语音，显式取本地默认 8。
MAX_PENDING_TRANSCRIPT_CELLS = 8
MAX_REPLAY_TRANSCRIPT_CELLS = MAX_PENDING_TRANSCRIPT_CELLS + 2

USER_SHELL_COMMAND_HELP_TITLE_ZH = "命令前加 ! 可在本地执行"
USER_SHELL_COMMAND_HELP_HINT_ZH = "示例：!ls"


class McpStartupStatus(str, Enum):
    """本地化：把上游「MCP 启动状态」建成显式枚举。"""

    IDLE = "idle"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


@dataclass
class ActiveCell:
    """对齐 ``ChatWidget.active_cell``：可在流式过程中原地变化。"""

    text: str = ""
    mutations: int = 0
    time_dependent: bool = False

    def append(self, chunk: str) -> None:
        self.text += chunk
        self.mutations += 1

    def transcript_key(self) -> tuple:
        """对齐上游缓存键设计：内容变化或时间依赖时键必须变。"""
        return (len(self.text), self.mutations, self.text[:64],
                self.time_dependent)

    def transcript_lines(self) -> List[str]:
        if not self.text:
            return []
        return self.text.splitlines()[-MAX_REPLAY_TRANSCRIPT_CELLS:]


@dataclass
class ChatWidget:
    """聊天界面的可验证契约骨架。"""

    committed_cells: List[str] = field(default_factory=list)
    active_cell: ActiveCell = field(default_factory=ActiveCell)
    agent_turn_running: bool = False
    mcp_startup_status: McpStartupStatus = McpStartupStatus.IDLE
    task_running: bool = False
    model_display_name: str = DEFAULT_MODEL_DISPLAY_NAME
    status_line_items: tuple = DEFAULT_STATUS_LINE_ITEMS
    _cached_tail_key: Optional[tuple] = None
    _cached_tail: List[str] = field(default_factory=list)
    _stats: Dict[str, int] = field(default_factory=lambda: {
        "commits": 0, "tail_rebuilds": 0, "tail_reuses": 0,
        "busy_updates": 0, "transcript_truncations": 0})

    # ------------------------------------------------------------ committed / live
    def commit_cell(self, text: str) -> str:
        """提交一个 finalized HistoryCell；超长按尾部截断。"""
        encoded = text.encode("utf-8", "replace")
        if len(encoded) > MAX_TRANSCRIPT_BYTES:
            text = encoded[-MAX_TRANSCRIPT_BYTES:].decode("utf-8", "replace")
            self._stats["transcript_truncations"] += 1
        self.committed_cells.append(text)
        self._stats["commits"] += 1
        return text

    def append_active(self, chunk: str) -> None:
        self.active_cell.append(chunk)

    def live_tail(self) -> List[str]:
        """对齐上游：committed + 缓存的 render-only live tail。

        缓存键变化时重建，否则复用（不每帧重建）。
        """
        key = self.active_cell.transcript_key()
        # 上游：缓存键在 active cell 原地变化**或**输出随时间变化时都要变，
        # 这样覆盖层能刷新缓存尾而不必每帧重建。时间依赖时强制重建。
        if key != self._cached_tail_key or self.active_cell.time_dependent:
            self._cached_tail = self.active_cell.transcript_lines()
            self._cached_tail_key = key
            self._stats["tail_rebuilds"] += 1
        else:
            self._stats["tail_reuses"] += 1
        return list(self._cached_tail)

    def overlay_lines(self) -> List[str]:
        return list(self.committed_cells) + self.live_tail()

    # ------------------------------------------------------------ 双生命周期
    def update_task_running_state(self) -> bool:
        """对齐上游：单一 busy 指示器由两个独立生命周期**派生**。"""
        self.task_running = (
            self.agent_turn_running
            or self.mcp_startup_status is McpStartupStatus.STARTING)
        self._stats["busy_updates"] += 1
        return self.task_running

    def set_agent_turn_running(self, running: bool) -> bool:
        self.agent_turn_running = bool(running)
        return self.update_task_running_state()

    def set_mcp_startup_status(self, status: McpStartupStatus) -> bool:
        self.mcp_startup_status = status
        return self.update_task_running_state()

    def finish_active_cell(self) -> None:
        """把在途 cell 提交并清空（对齐 flush 边界，不改 coalescing）。"""
        if self.active_cell.text:
            self.commit_cell(self.active_cell.text)
        self.active_cell = ActiveCell()
        self._cached_tail_key = None
        self._cached_tail = []

    # ------------------------------------------------------------ 可观测
    def stats(self) -> Dict[str, Any]:
        return {**self._stats,
                "committed": len(self.committed_cells),
                "live_tail_len": len(self._cached_tail),
                "task_running": self.task_running,
                "mcp_startup": self.mcp_startup_status.value}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_display_name": self.model_display_name,
            "status_line_items": list(self.status_line_items),
            "agent_turn_running": self.agent_turn_running,
            "mcp_startup_status": self.mcp_startup_status.value,
            "task_running": self.task_running,
            "committed_cells": len(self.committed_cells),
        }


def chatwidget_constants() -> Dict[str, Any]:
    return {
        "default_model_display_name": DEFAULT_MODEL_DISPLAY_NAME,
        "default_status_line_items": list(DEFAULT_STATUS_LINE_ITEMS),
        "ambient_pet_wrap_gap_columns": AMBIENT_PET_WRAP_GAP_COLUMNS,
        "max_transcript_bytes": MAX_TRANSCRIPT_BYTES,
        "max_replay_transcript_cells": MAX_REPLAY_TRANSCRIPT_CELLS,
        "max_pending_transcript_cells": MAX_PENDING_TRANSCRIPT_CELLS,
    }
