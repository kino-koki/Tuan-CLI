"""与 Codex ``tui/src/app_event.rs`` 对齐的应用事件契约。

上游 ``AppEvent`` 是一个约 1951 行、数百变体的巨大 enum，其中大量是
OpenAI 专属（账号、订阅、连接器、插件市场、宠物、worktree 等）。本模块
**不复制变体清单**，而是对齐其**可验证的契约骨架**：

  - 事件是一等类型化值，调用点不拼裸字符串；
  - ``SubmitThreadOp`` 携带 ``thread_id + op``（sender 的便捷方法都走它）；
  - ``CodexOp`` 携带 ``AppCommand``，且 **session log 不重复记录 Op**
    （上游注释：「Avoid double-logging Ops; those are logged at the point
    of submission」）；
  - ``TranscriptCopyClosed`` 是第 11 轮 ``copy_input_guard`` 的释放事件；
  - ``ExitMode`` 三态（ShutdownFirst / ShutdownAfterInterrupt / Immediate），
    **Immediate 明确跳过 shutdown、可能丢在途工作**；
  - ``RunningTaskExitAction`` 三态、``FeedbackCategory`` 五类、
    ``SideStartMode`` 两态；
  - ``KEY_EVENT_KINDS`` / 事件分组用于下游路由。

本地化修改（如实列出）：
  - 用 ``dataclass + Enum`` 替代 Rust enum + 字段变体；
  - 只保留本地 CLI 用得到的事件名，OpenAI 专属事件记为
    ``NOT_APPLICABLE_EVENTS``（不假装实现）；
  - 新增 ``EventCategory`` 分组与 ``is_loggable_inbound()`` 判定，把上游
    「Op 不双记」做成可测函数而不是散落在 sender 里的分支；
  - 新增 ``validate_thread_op()``：**线程 id 缺失/为空时拒绝**提交，
    避免把 A 会话的操作错投到 B（本地化安全增强）。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional

from .app_command import AppCommand

TRANSCRIPT_COPY_CLOSED = "TranscriptCopyClosed"


class ExitMode(str, Enum):
    """逐值对齐上游；Immediate 的语义风险在文档里如实保留。"""

    SHUTDOWN_FIRST = "ShutdownFirst"
    SHUTDOWN_AFTER_INTERRUPT = "ShutdownAfterInterrupt"
    IMMEDIATE = "Immediate"


class RunningTaskExitAction(str, Enum):
    CANCEL_TASK = "CancelTask"
    RUN_IN_BACKGROUND = "RunInBackground"
    EXIT = "Exit"


class FeedbackCategory(str, Enum):
    BAD_RESULT = "BadResult"
    GOOD_RESULT = "GoodResult"
    BUG = "Bug"
    SAFETY_CHECK = "SafetyCheck"
    OTHER = "Other"


class SideStartMode(str, Enum):
    REUSE = "Reuse"
    NEW = "New"


class EventCategory(str, Enum):
    """本地化分组（上游无此类型，供路由/可观测用）。"""

    LIFECYCLE = "lifecycle"
    THREAD_OP = "thread_op"
    CODEX_OP = "codex_op"
    TRANSCRIPT = "transcript"
    APPROVAL = "approval"
    UI = "ui"
    REALTIME = "realtime"


# 上游 voice_only 白名单里放行的事件（逐名对齐 app_event_sender.rs）
VOICE_ONLY_ALLOWLIST: FrozenSet[str] = frozenset({
    "RealtimeConversationStart", "RealtimeConversationStop",
    "RealtimeConversationSpeech", "RealtimeWebrtcOfferCreated",
    "RealtimeWebrtcConnected", "StopRealtimeConversation",
    "RealtimeSessionLockStopped", "RealtimeConversationStateChanged",
    "BackgroundVoiceError", "SyncThreadGitBranch", "RefreshRateLimits",
})

# OpenAI 专属事件名：明确记为不适用，不假装实现
NOT_APPLICABLE_EVENTS: FrozenSet[str] = frozenset({
    "AccountEmailLoaded", "OpenDaemonMenu", "ConfirmDaemonRestart",
    "OpenAppLink", "OpenDesktopThread", "SendAddCreditsNudgeEmail",
    "FetchConnectorsList", "FetchPluginsList", "FetchHooksList",
    "PetSelected", "PetPreviewRequested", "OpenPluginsList",
    "OpenMarketplaceAddLoading", "OpenMarketplaceRemoveConfirm",
    "OpenMarketplaceUpgradeLoading", "OpenPluginDetailLoading",
})

LOCAL_EVENT_NAMES: FrozenSet[str] = frozenset({
    TRANSCRIPT_COPY_CLOSED, "SubmitThreadOp", "CodexOp", "Exit",
    "InsertHistory", "RefreshViewedThread", "NewSession", "ClearUi",
    "SelectTranscriptCopy", "CopySelection", "LookupMessageHistoryEntry",
    "LookupMessageHistoryBatch", "ExportTranscript", "UpdateWarnings",
    "OpenUrlInBrowser", "FileSearchResult", "TaskSearchResult",
    "ApproveRecentAutoReviewDenial", "RunningTaskExit",
    "RevertSessionForPromptEdit", "FinishPromptRevert",
    "ClearUiAndSubmitUserMessage", "OpenThreadGoalMenu",
    "SetThreadGoalDraft", "SetThreadGoalStatus", "ClearThreadGoal",
})


@dataclass(frozen=True)
class AppEvent:
    """类型化事件值。``name`` 对齐上游变体名，``data`` 携带字段。"""

    name: str
    data: Dict[str, Any] = field(default_factory=dict)
    category: EventCategory = EventCategory.UI

    @classmethod
    def codex_op(cls, op: AppCommand) -> "AppEvent":
        """对齐 ``AppEvent::CodexOp(AppCommand)``。"""
        return cls("CodexOp", {"op": op}, EventCategory.CODEX_OP)

    @classmethod
    def submit_thread_op(cls, thread_id: str,
                         op: AppCommand) -> "AppEvent":
        """对齐 ``AppEvent::SubmitThreadOp { thread_id, op }``。"""
        return cls("SubmitThreadOp", {"thread_id": thread_id, "op": op},
                   EventCategory.THREAD_OP)

    @classmethod
    def transcript_copy_closed(cls) -> "AppEvent":
        """第 11 轮 ``CopyInputGuard`` 的释放事件。"""
        return cls(TRANSCRIPT_COPY_CLOSED, {}, EventCategory.TRANSCRIPT)

    def is_voice_allowed(self) -> bool:
        """对齐上游 voice_only 白名单判定。

        上游放行两类：若干具名事件，以及 ``CodexOp`` 里三个
        ``RealtimeConversation*`` 命令变体。本项目未实现实时语音，
        后一类仅作契约占位（``CommandKind`` 里标为未实现）。
        """
        if self.name in VOICE_ONLY_ALLOWLIST:
            return True
        if self.category is EventCategory.CODEX_OP:
            op = self.data.get("op")
            kind = getattr(op, "kind", None)
            return kind is not None and kind.value in (
                "RealtimeConversationStart", "RealtimeConversationStop",
                "RealtimeConversationSpeech")
        return False

    def is_loggable_inbound(self) -> bool:
        """对齐上游「Ops 不双记」；且 OpenAI 专属/未登记事件不记。

        本地化增强：未在本地事件表中的名字一律**不记**，避免把未知
        事件（可能携带敏感字段）写进会话日志。
        """
        if self.category is EventCategory.CODEX_OP:
            return False
        return self.name in LOCAL_EVENT_NAMES or \
            self.name in VOICE_ONLY_ALLOWLIST

    def to_dict(self) -> Dict[str, Any]:
        """录制用；``AppCommand`` 走自己的脱敏序列化。"""
        def clean(v: Any) -> Any:
            if isinstance(v, AppCommand):
                return v.to_dict()
            if isinstance(v, dict):
                return {k: clean(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [clean(x) for x in v]
            return v
        return {"name": self.name, "category": self.category.value,
                "data": clean(self.data)}


def validate_thread_op(event: AppEvent) -> Optional[str]:
    """本地化安全增强：线程操作必须有非空 thread_id。

    返回问题描述或 ``None``。对齐上游 ``BacktrackState.base_id`` 的
    「线程变了就作废旧选择」思路，把同样的保护前置到提交边界。
    """
    if event.category is not EventCategory.THREAD_OP:
        return None
    tid = event.data.get("thread_id")
    if not isinstance(tid, str) or not tid.strip():
        return "SubmitThreadOp 缺少 thread_id（拒绝跨会话误投）"
    if not isinstance(event.data.get("op"), AppCommand):
        return "SubmitThreadOp 缺少 AppCommand"
    return None


def event_catalog() -> Dict[str, int]:
    """可观测：事件名集合规模，供 parity 自检。"""
    return {
        "local_events": len(LOCAL_EVENT_NAMES),
        "voice_allowlist": len(VOICE_ONLY_ALLOWLIST),
        "not_applicable": len(NOT_APPLICABLE_EVENTS),
        "exit_modes": len(ExitMode),
        "feedback_categories": len(FeedbackCategory),
        "running_task_actions": len(RunningTaskExitAction),
    }
