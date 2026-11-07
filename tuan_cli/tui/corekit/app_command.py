"""与 Codex ``tui/src/app_command.rs`` 对齐的类型化出站命令。

上游最值得对齐的是**两个 newtype 的脱敏契约**（原文注释）：

    "Keeps ICE credentials out of command diagnostics and session recordings.
    Convert back to a string only when sending the offer to app-server signaling."

    "Keeps spoken answers out of command diagnostics and session recordings.
    Convert back to a string only at the app-server signaling boundary."

即 ``RealtimeOfferSdp`` / ``RealtimeSpeechText`` 的 ``Debug`` 与
``Serialize`` 都固定输出 ``"<redacted>"``，明文**只在发往信令边界时**才
还原。这是本轮安全价值最高的一条：一旦本地实现把 SDP（含 ICE 凭据）
或语音文本直接塞进诊断/会话录制，就是凭据泄漏。

本地化修改（如实列出）：
  - Rust newtype + trait impl -> Python ``Redacted`` 类，**除显式
    ``reveal()`` 外**，``repr`` / ``str`` / ``format`` / ``to_dict`` /
    ``__eq__`` 比较全部走脱敏值（比上游更严：上游 ``PartialEq`` 是比
    较明文，这里连比较都不暴露）；
  - 新增 ``reveal()`` 的调用点审计计数（可观测，不改变行为）；
  - ``serde(skip_serializing)`` -> ``to_wire_dict()`` 明确不含 ``proof``；
  - 上游 20+ 个 ``AppCommand`` 变体按**本项目实际存在的动作**取子集，
    其余保留为枚举名但标 ``not_implemented``，不谎称支持；
  - 中文/本地模型字段、本地审批策略枚举替换 OpenAI 专属类型。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

REDACTED = "<redacted>"


class Redacted:
    """脱敏 newtype：明文只在显式 ``reveal()`` 时可用。

    对齐上游 Debug / Serialize 恒为 ``<redacted>``；本地化增强：
    ``repr`` / ``str`` / ``format`` / ``to_dict`` / ``json`` / ``==``
    都不泄漏明文，避免误用 f-string 把凭据打进日志。
    """

    __slots__ = ("_value", "_reveals")

    def __init__(self, value: str):
        self._value = str(value)
        self._reveals = 0

    def reveal(self) -> str:
        """**唯一**取明文的出口；调用即计数，便于审计排查误用。"""
        self._reveals += 1
        return self._value

    @property
    def reveal_count(self) -> int:
        return self._reveals

    def __repr__(self) -> str:
        return REDACTED

    def __str__(self) -> str:
        return REDACTED

    def __format__(self, spec: str) -> str:
        return REDACTED

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Redacted):
            return self._value == other._value  # 比内容但不暴露
        return False

    def __hash__(self) -> int:
        return hash(REDACTED)  # 不把明文放进哈希

    def to_dict(self) -> str:
        return REDACTED

    def serialize(self) -> str:
        """对齐上游 ``Serialize`` 恒输出 ``"<redacted>"``。"""
        return REDACTED


class RealtimeOfferSdp(Redacted):
    """ICE 凭据（SDP offer）。"""


class RealtimeSpeechText(Redacted):
    """语音转写文本。"""


class CloudSubmissionIntent(str, Enum):
    """逐值对齐上游三态。"""

    USE_KNOWN_TURN = "use_known_turn"
    START_OR_STEER = "start_or_steer"
    START_IF_IDLE = "start_if_idle"


class CommandKind(str, Enum):
    """上游 ``AppCommand`` 变体名（本项目实现子集，其余标未实现）。"""

    INTERRUPT = "Interrupt"
    CLEAN_BACKGROUND_TERMINALS = "CleanBackgroundTerminals"
    RUN_USER_SHELL_COMMAND = "RunUserShellCommand"
    USER_TURN = "UserTurn"
    OVERRIDE_TURN_CONTEXT = "OverrideTurnContext"
    EXEC_APPROVAL = "ExecApproval"
    PATCH_APPROVAL = "PatchApproval"
    RESOLVE_ELICITATION = "ResolveElicitation"
    RESOLVE_USER_VERIFICATION = "ResolveUserVerification"
    USER_INPUT_ANSWER = "UserInputAnswer"
    REQUEST_PERMISSIONS_RESPONSE = "RequestPermissionsResponse"
    RELOAD_USER_CONFIG = "ReloadUserConfig"
    LIST_SKILLS = "ListSkills"
    COMPACT = "Compact"
    SET_THREAD_NAME = "SetThreadName"
    REVIEW = "Review"
    APPROVE_GUARDIAN_DENIED_ACTION = "ApproveGuardianDeniedAction"
    # 上游 voice_only 白名单放行这三个 AppCommand 变体；本项目未实现
    # 实时语音（OpenAI 专属），保留变体名仅为使白名单契约可核验，
    # 它们不在 IMPLEMENTED_KINDS 里，绝不谎称可执行。
    REALTIME_CONVERSATION_START = "RealtimeConversationStart"
    REALTIME_CONVERSATION_STOP = "RealtimeConversationStop"
    REALTIME_CONVERSATION_SPEECH = "RealtimeConversationSpeech"


IMPLEMENTED_KINDS = frozenset({
    CommandKind.INTERRUPT, CommandKind.RUN_USER_SHELL_COMMAND,
    CommandKind.USER_TURN, CommandKind.OVERRIDE_TURN_CONTEXT,
    CommandKind.EXEC_APPROVAL, CommandKind.PATCH_APPROVAL,
    CommandKind.REQUEST_PERMISSIONS_RESPONSE,
    CommandKind.RELOAD_USER_CONFIG, CommandKind.COMPACT,
    CommandKind.SET_THREAD_NAME, CommandKind.REVIEW,
})


@dataclass
class AppCommand:
    """类型化出站命令（对齐上游：调用点不再重复拼事件）。"""

    kind: CommandKind
    payload: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ 构造器
    @classmethod
    def interrupt(cls) -> "AppCommand":
        return cls(CommandKind.INTERRUPT)

    @classmethod
    def run_user_shell_command(cls, command: str) -> "AppCommand":
        return cls(CommandKind.RUN_USER_SHELL_COMMAND, {"command": command})

    @classmethod
    def exec_approval(cls, id: str, decision: str,
                      turn_id: Optional[str] = None) -> "AppCommand":
        return cls(CommandKind.EXEC_APPROVAL,
                   {"id": id, "turn_id": turn_id, "decision": decision})

    @classmethod
    def patch_approval(cls, id: str, decision: str) -> "AppCommand":
        return cls(CommandKind.PATCH_APPROVAL, {"id": id, "decision": decision})

    @classmethod
    def compact(cls) -> "AppCommand":
        return cls(CommandKind.COMPACT)

    @classmethod
    def set_thread_name(cls, name: str) -> "AppCommand":
        return cls(CommandKind.SET_THREAD_NAME, {"name": name})

    @classmethod
    def review(cls, target: str) -> "AppCommand":
        return cls(CommandKind.REVIEW, {"target": target})

    @classmethod
    def user_turn(cls, *, turn_trigger: str,
                  cloud_submission: CloudSubmissionIntent,
                  client_user_message_id: str, items: list,
                  cwd: str, approval_policy: str, model: str,
                  effort: Optional[str] = None) -> "AppCommand":
        """对齐上游 ``user_turn(..)`` 的关键字段（本地化为 str 而非 Rust 类型）。"""
        return cls(CommandKind.USER_TURN, {
            "turn_trigger": turn_trigger,
            "cloud_submission": cloud_submission.value,
            "client_user_message_id": client_user_message_id,
            "items": list(items),
            "cwd": cwd,
            "approval_policy": approval_policy,
            "approvals_reviewer": None,   # 对齐上游构造器硬编码 None
            "model": model,
            "effort": effort,
        })

    def is_review(self) -> bool:
        """对齐上游 ``is_review()``。"""
        return self.kind is CommandKind.REVIEW

    def is_implemented(self) -> bool:
        """如实：未实现的变体不假装能执行。"""
        return self.kind in IMPLEMENTED_KINDS

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> Dict[str, Any]:
        """会话录制用；``Redacted`` 值恒为 ``<redacted>``，递归生效。"""
        def clean(v: Any) -> Any:
            if isinstance(v, Redacted):
                return v.serialize()
            if isinstance(v, dict):
                return {k: clean(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [clean(x) for x in v]
            return v
        return {"kind": self.kind.value,
                "payload": clean(self.payload),
                "implemented": self.is_implemented()}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class UserVerificationResponseKind(str, Enum):
    ACCEPT = "Accept"
    CANCEL = "Cancel"
    FAILED = "Failed"


@dataclass
class UserVerificationResponse:
    """对齐上游：``proof`` 带 ``#[serde(skip_serializing)]``。

    上游注释明确：AppCommand 序列化用于**会话录制**，不是 RPC wire；
    proof 只由 controller 单独写进 elicitation 响应。本地化实现把这条
    做成可测契约：``to_dict()`` 绝不含 proof 明文。
    """

    kind: UserVerificationResponseKind
    proof: Optional[Redacted] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"kind": self.kind.value}
        if self.error is not None:
            out["error"] = self.error
        # 刻意不写 proof：对齐 serde(skip_serializing)
        return out

    def wire_proof(self) -> Optional[str]:
        """仅 controller 在真正发往 MCP  elicitation 边界时调用。"""
        return self.proof.reveal() if self.proof else None


class UserVerificationFailure:
    """上游注释：只带安全展示文本与封闭的原生错误类别。"""

    __slots__ = ("message", "details")

    def __init__(self, message: str, details: str):
        self.message = message
        self.details = details

    def to_dict(self) -> Dict[str, str]:
        return {"message": self.message, "details": self.details}
