"""Tuan TUI 应用核心对齐层（第 12 轮）。

逐模块对齐 OpenAI Codex ``codex-rs/tui/src`` 的 ``core_app`` 组 9 个
待办模块，用纯 Python 独立实现，零 Rust 源码复制。每个模块的 docstring
都列出上游契约与本地化修改点；许可见 ``NOTICE`` 第 12 条。

| 上游模块 | 本包模块 | 对齐要点 |
|---|---|---|
| ``app.rs`` | ``app`` | 32768 通道容量、AppRunControl/ExitReason/AppExitInfo、可恢复判定、**既有安全接线保护** |
| ``app_backtrack.rs`` | ``app_backtrack`` | 六步 Esc/Enter 状态机、base_id 变更失效、两条提示常量 |
| ``app_command.rs`` | ``app_command`` | Redacted newtype（Debug/Serialize 恒 ``<redacted>``）、命令类型化、proof 不进录制 |
| ``app_event.rs`` | ``app_event`` | 类型化事件、Ops 不双记、ExitMode/FeedbackCategory 等分类 |
| ``app_event_sender.rs`` | ``app_event_sender`` | voice_only 白名单优先丢弃、吞错记日志、10 个便捷方法 |
| ``app_info.rs`` | ``app_info`` | wire→domain 显式转换、15/6/11/1/3 字段、严格未知字段拒绝 |
| ``chatwidget.rs`` | ``chatwidget`` | committed + active cell / live tail 缓存、双生命周期 busy |
| ``cli.rs`` | ``cli`` | 公开/内部 flag 分离、**两条审批冲突规则 fail-closed** |
| ``resize_reflow_cap.rs`` | ``resize_reflow_cap`` | 1000/9001/3500/10000 四档、三态配置、VSCode probe 优先 |

**本轮硬约束**：对齐 core_app **不得破坏前 11 轮修好的安全接线**。
``app.assert_wiring_intact()`` 真实 import 现有模块逐项验证
（``build_permission_policy`` / ``_DenyAllMCPPolicy`` / ``ctx.confirm`` /
审批卡片 / 副本确认 / ABORT 显式决策），并接入 ``corekit_validate()``
与回归集。任何「为了对齐而重写入口」的改动都会先被测试拦下。

本地化边界：渲染后端、中文文案、OpenAI 专属能力标 ``not_applicable``、
动态类型的严格字段白名单、有界队列、脱敏增强。**键位、常量数值、
状态机分支、契约语义不改**。
"""
from __future__ import annotations

from . import (
    app, app_backtrack, app_command, app_event, app_event_sender,
    app_info, chatwidget, cli, resize_reflow_cap,
)

__all__ = [
    "app", "app_backtrack", "app_command", "app_event",
    "app_event_sender", "app_info", "chatwidget", "cli",
    "resize_reflow_cap", "corekit_report", "corekit_validate",
    "MODULES",
]

MODULES = (
    "app", "app_backtrack", "app_command", "app_event",
    "app_event_sender", "app_info", "chatwidget", "cli",
    "resize_reflow_cap",
)


def corekit_report() -> dict:
    """可观测入口：被 ``tuan tui parity`` 消费。"""
    wiring = app.verify_existing_security_wiring()
    return {
        "modules": len(MODULES),
        "upstream_group": "core_app",
        "app": app.app_constants(),
        "commands": {
            "kinds": len(app_command.CommandKind),
            "implemented": len(app_command.IMPLEMENTED_KINDS),
            "cloud_intents": len(app_command.CloudSubmissionIntent),
            "redacted": app_command.REDACTED,
        },
        "events": app_event.event_catalog(),
        "sender_capacity": app_event_sender.DEFAULT_QUEUE_CAPACITY,
        "app_info_fields": app_info.field_counts(),
        "cli": {
            "public_flags": len(cli.PUBLIC_FLAGS),
            "internal_skip": len(cli.INTERNAL_SKIP_ARGS),
            "conflict_rules": len(cli.CONFLICT_RULES),
        },
        "resize_caps": resize_reflow_cap.constants(),
        "chatwidget": chatwidget.chatwidget_constants(),
        "security_wiring": {"intact": wiring.intact,
                            "checks": wiring.checks,
                            "problems": wiring.problems},
    }


def corekit_validate() -> list[str]:
    """自检：常量、契约与**既有安全接线**是否自洽。"""
    problems: list[str] = []

    # ---- 逐值常量核销
    if app.THREAD_EVENT_CHANNEL_CAPACITY != 32768:
        problems.append("app 通道容量不等于 32768")
    if app.EXTERNAL_EDITOR_HINT != "Save and close external editor to continue.":
        problems.append("外部编辑器提示不等于上游原文")
    if app_event_sender.DEFAULT_QUEUE_CAPACITY != 32768:
        problems.append("sender 队列容量与 app 常量不一致")
    caps = resize_reflow_cap.constants()
    if (caps["vscode"], caps["windows_terminal"], caps["wezterm"],
        caps["alacritty"]) != (1000, 9001, 3500, 10000):
        problems.append("resize reflow 四档常量不对")
    cw = chatwidget.chatwidget_constants()
    if cw["max_transcript_bytes"] != 1024:
        problems.append("MAX_TRANSCRIPT_BYTES 不等于 1024")
    if cw["default_status_line_items"] != [
            "model-with-reasoning", "current-dir", "thread-name"]:
        problems.append("默认状态栏三项不对")
    if cw["ambient_pet_wrap_gap_columns"] != 2:
        problems.append("AMBIENT_PET_WRAP_GAP_COLUMNS 不等于 2")
    if app_info.field_counts() != {
            "app_info": 15, "branding": 6, "metadata": 11,
            "review": 1, "screenshot": 3}:
        problems.append("app_info 字段数量不对")
    if len(cli.CONFLICT_RULES) != 2:
        problems.append("CLI 审批冲突规则不是 2 条")

    # ---- 安全契约核销
    secret = app_command.RealtimeOfferSdp("ICE-CREDENTIAL-SECRET")
    if (repr(secret) != "<redacted>" or str(secret) != "<redacted>"
            or f"{secret}" != "<redacted>"
            or secret.serialize() != "<redacted>"):
        problems.append("Redacted newtype 泄漏明文")
    op = app_command.AppCommand.run_user_shell_command("echo x")
    if "ICE" in op.to_json():
        problems.append("命令录制出现未脱敏内容")
    resp = app_command.UserVerificationResponse(
        app_command.UserVerificationResponseKind.ACCEPT,
        proof=app_command.RealtimeOfferSdp("PROOF"))
    if "PROOF" in str(resp.to_dict()):
        problems.append("UserVerificationResponse.to_dict 泄漏 proof")

    bad, issues = cli.parse_args(
        ["--yolo", "--ask-for-approval", "on-request"])
    if not issues or bad.is_safe_to_start():
        problems.append("CLI 未拒绝 绕过审批 + 指定审批策略 的组合")
    bad2, issues2 = cli.parse_args(
        ["--auto-review", "--ask-for-approval", "on-request"])
    if not issues2 or bad2.is_safe_to_start():
        problems.append("CLI 未拒绝 auto_review + 指定审批策略 的组合")

    if app_backtrack.BacktrackPhase.IDLE.value != "idle":
        problems.append("backtrack 状态枚举异常")
    if app_event.ExitMode.IMMEDIATE.value != "Immediate":
        problems.append("ExitMode 枚举异常")

    # ---- 既有安全接线（本轮硬约束）
    wiring = app.verify_existing_security_wiring()
    if not wiring.intact:
        problems.extend(f"既有安全接线: {p}" for p in wiring.problems)
    return problems
