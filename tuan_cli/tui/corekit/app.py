"""与 Codex ``tui/src/app.rs`` 对齐的顶层应用状态机骨架。

上游模块头：

    "Top-level TUI application state and runtime wiring. This module owns
    the `App` struct, shared imports, and the high-level run loop that
    coordinates the focused app submodules."

逐值/逐分支对齐：
  - ``THREAD_EVENT_CHANNEL_CAPACITY = 32768``；
  - ``EXTERNAL_EDITOR_HINT = "Save and close external editor to continue."``；
  - ``AppRunControl``：Continue / Exit(ExitReason)；
  - ``ExitReason``：UserRequested / TurnInterrupted / Fatal(String)；
  - ``AppExitInfo`` 字段：token_usage / thread_id / resume_hint /
    disconnect_info / update_action / exit_reason；
  - ``AppExitInfo::fatal(message)`` 把其他字段全置空；
  - ``rollout_path_is_resumable``：**文件存在、是普通文件、且长度 > 0**
    才可恢复（空文件不算）；
  - ``App`` 持有 ``ChatWidget`` / ``AppEventSender`` / ``BacktrackState`` /
    运行时策略覆盖（``RuntimeApprovalPolicyOverride`` 等）。

**本模块最重要的约束（用户明确要求）**：对齐 core_app 不得破坏本项目
前 11 轮修好的安全接线。因此本模块**不替换**任何现有运行时对象，只提供
``verify_existing_security_wiring()``：真实 import 现有模块，逐项断言
``build_permission_policy``、``_DenyAllMCPPolicy``、``ctx.confirm`` 通道、
``make_confirm_callable``、审批覆盖层 ``ABORT`` 语义仍存在且可用。
这条断言进回归集，以后任何「为了对齐而重写入口」的改动都会先被拦下。

本地化修改（如实列出）：
  - tokio run loop / crossterm -> 可注入的 ``dispatch()`` + 纯状态机；
  - 上游 ``App`` 有上百字段，这里只保留**可验证的契约骨架**，
    OpenAI 专属（account / subscription / worktree / daemon）不实现；
  - 新增 ``SecurityWiringReport`` 与 ``assert_wiring_intact()``；
  - 本地化增强：``Fatal`` 原因进审计事件（纯观测，不改裁决）。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .app_event_sender import AppEventSender

THREAD_EVENT_CHANNEL_CAPACITY = 32768
EXTERNAL_EDITOR_HINT = "Save and close external editor to continue."


class AppRunControl(str, Enum):
    CONTINUE = "Continue"
    EXIT = "Exit"


class ExitReason(str, Enum):
    USER_REQUESTED = "UserRequested"
    TURN_INTERRUPTED = "TurnInterrupted"
    FATAL = "Fatal"


@dataclass
class AppExitInfo:
    """对齐 ``AppExitInfo`` 六字段。"""

    token_usage: Dict[str, Any] = field(default_factory=dict)
    thread_id: Optional[str] = None
    resume_hint: Optional[Dict[str, Any]] = None
    disconnect_info: Optional[Dict[str, Any]] = None
    update_action: Optional[Any] = None
    exit_reason: ExitReason = ExitReason.USER_REQUESTED
    fatal_message: Optional[str] = None

    @classmethod
    def fatal(cls, message: str) -> "AppExitInfo":
        """对齐上游：其余字段全部置空。"""
        return cls(exit_reason=ExitReason.FATAL, fatal_message=message)


def rollout_path_is_resumable(path: str) -> bool:
    """对齐上游：存在 + 普通文件 + len > 0（空文件不算）。"""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def resumable_thread(thread_id: Optional[str],
                     thread_name: Optional[str],
                     rollout_path: Optional[str]
                     ) -> Optional[Dict[str, Any]]:
    """对齐上游 ``resumable_thread()`` 的 Option 链。"""
    if not thread_id or not rollout_path:
        return None
    if not rollout_path_is_resumable(rollout_path):
        return None
    return {"thread_id": thread_id, "thread_name": thread_name}


@dataclass
class AppState:
    """``App`` 的可验证契约骨架（不替换现有运行时对象）。"""

    thread_id: Optional[str] = None
    run_control: AppRunControl = AppRunControl.CONTINUE
    exit_info: Optional[AppExitInfo] = None
    backtrack_primed: bool = False
    task_running: bool = False
    overlay: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)

    def request_exit(self, reason: ExitReason,
                     message: Optional[str] = None) -> AppExitInfo:
        info = (AppExitInfo.fatal(message or "fatal")
                if reason is ExitReason.FATAL
                else AppExitInfo(exit_reason=reason))
        self.run_control = AppRunControl.EXIT
        self.exit_info = info
        if reason is ExitReason.FATAL:
            # 本地化增强：纯观测事件，不参与裁决
            self.events.append({"kind": "fatal", "reason": message or ""})
        return info

    def dispatch(self, event_name: str,
                 handler: Optional[Callable[[str], Any]] = None) -> Any:
        """最小 run loop：把事件交给可注入 handler。"""
        self.events.append({"kind": "event", "name": event_name})
        if handler is not None:
            return handler(event_name)
        return None


# ---------------------------------------------------------------- 接线保护
@dataclass
class SecurityWiringReport:
    """本地化：逐项记录既有安全接线是否完好。"""

    checks: Dict[str, bool] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)

    @property
    def intact(self) -> bool:
        return not self.problems and all(self.checks.values())


def verify_existing_security_wiring() -> SecurityWiringReport:
    """**本轮关键保护**：真实 import，确认前 11 轮的安全接线没被改掉。

    检查项（每项都对应一个已修过的真实缺陷）：
      1. ``build_permission_policy`` 存在且可调用 —— E1 主链路注入；
      2. ``_DenyAllMCPPolicy`` 存在且 ``authorize`` 返回 deny —— 策略层
         初始化失败时 fail-closed，不退回到裸 mcp_call；
      3. ``tools.base`` 里 ``ctx.confirm`` 仍是审批通道；
      4. ``ui.approval_overlay.make_confirm_callable`` 存在 —— E7 卡片接线；
      5. ``sandbox.isolation.confirm_apply`` 存在 —— 副本模式确认；
      6. 审批覆盖层 ``ABORT`` 仍是显式决策（Esc/取消绝不变成同意）。
    """
    r = SecurityWiringReport()
    try:
        from tuan_cli.tools.permission_fusion import (
            build_permission_policy, _DenyAllMCPPolicy)
        r.checks["build_permission_policy"] = callable(build_permission_policy)
        from tuan_cli.tools.mcp.policy import AuthorizationDecision
        d = _DenyAllMCPPolicy("probe").authorize("s", "t")
        r.checks["deny_all_policy"] = (
            isinstance(d, AuthorizationDecision)
            and getattr(d, "action", None) == "deny")
    except Exception as exc:  # noqa: BLE001
        r.problems.append(f"权限策略注入不可用: {type(exc).__name__}: {exc}")

    try:
        import inspect
        from tuan_cli.tools import base as tools_base
        src = inspect.getsource(tools_base)
        r.checks["ctx_confirm_channel"] = "ctx.confirm" in src
    except Exception as exc:  # noqa: BLE001
        r.problems.append(f"ctx.confirm 接线不可读: {type(exc).__name__}: {exc}")

    try:
        from tuan_cli.ui.approval_overlay import make_confirm_callable
        r.checks["approval_card_wiring"] = callable(make_confirm_callable)
    except Exception as exc:  # noqa: BLE001
        r.problems.append(f"审批卡片接线不可用: {type(exc).__name__}: {exc}")

    try:
        from tuan_cli.sandbox.isolation import confirm_apply
        r.checks["copy_diff_apply_confirm"] = callable(confirm_apply)
    except Exception as exc:  # noqa: BLE001
        r.problems.append(f"副本确认接线不可用: {type(exc).__name__}: {exc}")

    try:
        from tuan_cli.ui.approval_overlay import (
            ApprovalDecision, ApprovalRequest, resolve_decision)
        req = ApprovalRequest(kind="exec", title="wiring probe")
        r.checks["abort_is_explicit"] = (
            hasattr(ApprovalDecision, "ABORT")
            # 上游契约 2：无输入 / Esc 绝不能变成同意
            and resolve_decision(None, req) is ApprovalDecision.ABORT
            and resolve_decision("esc", req) is ApprovalDecision.ABORT
            and not ApprovalDecision.ABORT.granted)
    except Exception as exc:  # noqa: BLE001
        r.problems.append(f"ABORT 决策不可用: {type(exc).__name__}: {exc}")

    for k, v in list(r.checks.items()):
        if not v:
            r.problems.append(f"安全接线检查未通过: {k}")
    return r


def assert_wiring_intact() -> SecurityWiringReport:
    """供回归集调用：接线不全就抛，防止「对齐」把侧门重新打开。"""
    r = verify_existing_security_wiring()
    if not r.intact:
        raise RuntimeError("既有安全接线被破坏: " + "; ".join(r.problems))
    return r


def app_constants() -> Dict[str, Any]:
    return {
        "thread_event_channel_capacity": THREAD_EVENT_CHANNEL_CAPACITY,
        "external_editor_hint": EXTERNAL_EDITOR_HINT,
        "run_controls": [c.value for c in AppRunControl],
        "exit_reasons": [e.value for e in ExitReason],
    }
