"""B2: ``permissions.denyInsteadOfPrompting`` —— 无人值守时拒绝并继续 turn。

对齐 Claude Code v2.1.319 新增能力：本该等待审批的调用**直接拒绝并继续
turn**，无人值守不会卡死在 permission prompt 上。

Tuan 旧行为（``SandboxManager.assess_tool``）：CONFIRM 且没有 confirm
通道时返回 ``(True, "...需要人工确认但没有确认通道...")``。拒绝是真的，
但两个语义缺失：

1. 没有**显式开关**，headless 部署无法选择「拒绝并继续」还是「挂起等待」；
2. 「继续 turn」没有结构化表达，上层只看到 denied=True，容易把整个
   turn 终止掉；也没有可查询的抑制记录。

本模块把决策做成纯函数 + 结构化结果，由 manager 接线；**默认关闭**
（``enabled=False``），开启是显式行为变更，配置校验会报 warning。

设计约束：
  - 绝不把「拒绝」放宽成「放行」：``denied=True`` 是硬事实；
  - 「继续 turn」只写在 ``continue_turn`` / ``suppressed_prompt`` 字段和
    ``verdict.extra``，不改动 ``(denied, block_msg)`` 的既有契约；
  - 配置值严格类型校验，未知 scope / 非 bool 一律拒绝，不静默回落；
  - 不记录命令原文、不记录密钥。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

SCOPE_NO_CHANNEL = "no_confirm_channel"
SCOPE_ALL = "all_confirmations"
VALID_SCOPES = (SCOPE_NO_CHANNEL, SCOPE_ALL)

REASON_TEMPLATE = (
    "[denyInsteadOfPrompting] 无人值守：已拒绝本次需确认的工具调用"
    "（continue_turn=True, suppressed_prompt=True）；原因: {why}"
)


@dataclass(frozen=True)
class UnattendedPolicy:
    enabled: bool = False
    scope: str = SCOPE_NO_CHANNEL

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.enabled, bool):
            errors.append("permissions.denyInsteadOfPrompting 应为 bool")
        if self.scope not in VALID_SCOPES:
            errors.append(
                f"permissions.denyInsteadOfPromptingScope={self.scope!r} "
                f"不在 {VALID_SCOPES} 中")
        return errors

    @classmethod
    def from_mapping(cls, config: Any) -> "UnattendedPolicy":
        """从配置字典解析，兼容三种键位置。

        支持：
          - ``permissions.denyInsteadOfPrompting``（CC 口径，扁平键）
          - ``denyInsteadOfPrompting``（沙箱策略内简写）
          - ``sandbox.unattended.deny_instead_of_prompting``（嵌套）

        严格类型：非 bool 的 enabled 视为 **False 并记无效**，
        绝不 ``bool("false")`` 那种静默转真。
        """
        if not isinstance(config, Mapping):
            return cls()
        enabled_raw: Any = None
        scope_raw: Any = None
        for key in ("permissions.denyInsteadOfPrompting", "denyInsteadOfPrompting"):
            if key in config:
                enabled_raw = config[key]
                break
        un = config.get("unattended")
        if isinstance(un, Mapping):
            if enabled_raw is None and "deny_instead_of_prompting" in un:
                enabled_raw = un["deny_instead_of_prompting"]
            if scope_raw is None and "scope" in un:
                scope_raw = un["scope"]
        for key in ("permissions.denyInsteadOfPromptingScope",
                    "denyInsteadOfPromptingScope"):
            if key in config:
                scope_raw = config[key]
                break
        enabled = enabled_raw if isinstance(enabled_raw, bool) else False
        scope = scope_raw if isinstance(scope_raw, str) and scope_raw in VALID_SCOPES \
            else SCOPE_NO_CHANNEL
        return cls(enabled=enabled, scope=scope)

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "scope": self.scope}


@dataclass(frozen=True)
class UnattendedOutcome:
    denied: bool
    reason: str
    continue_turn: bool
    suppressed_prompt: bool
    policy: str
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "denied": self.denied,
            "reason": self.reason,
            "continue_turn": self.continue_turn,
            "suppressed_prompt": self.suppressed_prompt,
            "policy": self.policy,
            "applied": self.applied,
        }


def resolve_confirm(verdict: Any, *, has_confirm_channel: bool,
                    policy: Optional[UnattendedPolicy] = None
                    ) -> UnattendedOutcome:
    """把一次 CONFIRM 裁决解析成无人值守决策。

    ``applied=False`` 时 manager 必须保持原有确认路径，零行为变化。
    """
    p = policy if policy is not None else UnattendedPolicy()
    errs = p.validate()
    if errs:
        # 配置非法 → fail-closed 拒绝，且明确说明，不静默沿用
        return UnattendedOutcome(
            denied=True,
            reason="[denyInsteadOfPrompting] 策略配置非法, fail-closed: "
                   + "; ".join(errs),
            continue_turn=False, suppressed_prompt=False,
            policy="invalid", applied=True)
    if not p.enabled:
        return UnattendedOutcome(denied=False, reason="", continue_turn=False,
                                 suppressed_prompt=False, policy="disabled",
                                 applied=False)
    triggered = (not has_confirm_channel) or p.scope == SCOPE_ALL
    if not triggered:
        return UnattendedOutcome(denied=False, reason="", continue_turn=False,
                                 suppressed_prompt=False, policy=p.scope,
                                 applied=False)
    why = str(getattr(verdict, "reason", "") or "需要人工确认")[:240]
    return UnattendedOutcome(
        denied=True,
        reason=REASON_TEMPLATE.format(why=why),
        continue_turn=True,
        suppressed_prompt=True,
        policy=p.scope,
        applied=True,
    )
