"""审批策略树 (ApprovalPolicyTree) —— 策略可编程的分层审批 + 审计联动。

阶段 C「人机协同审批增强」的核心: 把审批从"二选一确认"升级为
**按风险等级分层策略 + 可编程规则 + 审计追溯**。

与 ``ui/approval_overlay.py`` 的关系 (互补, 不重复):
- ``approval_overlay.py`` = **交互契约层**: 呈现 DiffPreview / 权限域, 路由用户的
  显式决策 (ONCE/SESSION/DENY/ABORT...), **不判定安全性**;
- 本模块 = **策略裁决层**: 在交互层之前, 按风险等级分层路由 (自动放行 /
  需人工 / 硬拒绝), 规则可编程 (策略树), 并把每次裁决写入审计事件流。
即: 策略树先决定"这个操作要不要问人、怎么问、是否允许", overlay 再负责"怎么呈现"。

设计 (fail-safe, 安全叙事不可弱化):
- 分层: ``allow`` (白名单自动放行) / ``ask`` (需人工) / ``deny`` (硬红线);
- 规则匹配顺序: 显式规则 (前缀/精确) → 风险等级 → 默认层;
- 任何不确定/解析失败 → 落到 ``ask`` 或 ``deny`` (绝不 fall-through 到 allow);
- 每条裁决 append-only 写入审计事件流 (who/what/decision/timestamp)。

用法::

    policy = ApprovalPolicyTree(
        rules=[ApprovalRule(pattern="git push", layer=Layer.DENY)],
        default_layer=Layer.ASK,
    )
    decision = policy.decide("git commit -m 'x'", actor="human")
    # decision.layer == Layer.ALLOW (git commit 在白名单)
    # decision.audit_event 已生成, 由调用方写入审计存储
"""

from __future__ import annotations

import fnmatch
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import logging
log = logging.getLogger(__name__)


class RiskLayer(str, Enum):
    """审批风险分层。"""

    ALLOW = "allow"   # 白名单: 自动放行, 无需人工
    ASK = "ask"       # 需人工确认
    DENY = "deny"     # 硬红线: 拒绝执行


@dataclass(frozen=True)
class ApprovalRule:
    """一条可编程审批规则。

    ``pattern`` 支持通配符 (``*``/``?``) 前缀匹配, 或 ``exact:<str>`` 精确匹配。
    ``layer`` 决定该规则命中时的裁决层; ``reason`` 用于审计可读性。
    """

    pattern: str
    layer: RiskLayer
    reason: str = ""
    priority: int = 0   # 越大越优先

    def matches(self, action: str) -> bool:
        if self.pattern.startswith("exact:"):
            return action == self.pattern[len("exact:"):]
        if self.pattern.endswith(":*"):
            # 前缀 + 通配 (覆盖前缀匹配)
            prefix = self.pattern[:-1]
            return fnmatch.fnmatch(action, self.pattern)
        return fnmatch.fnmatch(action, self.pattern)


@dataclass
class AuditEvent:
    """一次审批裁决的审计事件 (append-only)。"""

    event_id: str
    action: str
    decision: str
    reason: str
    actor: str
    context: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "decision": self.decision,
            "reason": self.reason,
            "actor": self.actor,
            "context": dict(self.context),
            "ts": round(self.ts, 3),
        }


@dataclass
class ApprovalDecision:
    """一次审批的裁决结果。"""

    action: str
    layer: RiskLayer
    rule: Optional[ApprovalRule] = None
    reason: str = ""
    needs_human: bool = False
    audit_event: Optional[AuditEvent] = None

    @property
    def allowed(self) -> bool:
        return self.layer == RiskLayer.ALLOW

    @property
    def needs_approval(self) -> bool:
        return self.layer == RiskLayer.ASK


class ApprovalPolicyTree:
    """策略可编程的分层审批裁决器 + 审计联动。

    匹配顺序:
    1. 按 ``priority`` 降序遍历规则, 命中即裁决 (显式规则 > 默认层);
    2. 无规则命中 → 用 ``default_layer`` (默认 ASK, fail-safe);
    3. 每次裁决生成审计事件 (可被调用方落盘)。

    安全约束: 规则解析异常/空动作 → 保守落到 DENY 或 ASK, 绝不 allow。
    """

    def __init__(
        self,
        rules: Optional[List[ApprovalRule]] = None,
        default_layer: RiskLayer = RiskLayer.ASK,
        audit_sink: Optional[List[AuditEvent]] = None,
    ) -> None:
        self._rules: List[ApprovalRule] = list(rules) if rules else []
        self._rules.sort(key=lambda r: r.priority, reverse=True)
        self._default_layer = default_layer
        self._sink = audit_sink if audit_sink is not None else []

    @property
    def rules(self) -> List[ApprovalRule]:
        return list(self._rules)

    @property
    def default_layer(self) -> RiskLayer:
        return self._default_layer

    def add_rule(self, rule: ApprovalRule) -> None:
        """动态追加规则 (按 priority 重新排序)。"""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def decide(self, action: str, actor: str = "system",
               context: Optional[Dict[str, Any]] = None) -> ApprovalDecision:
        """裁决一个动作。空/异常动作保守拒绝。"""
        ctx = dict(context or {})
        if not action or not str(action).strip():
            event = self._audit("", RiskLayer.DENY, "empty action", actor, ctx)
            return ApprovalDecision(action=action, layer=RiskLayer.DENY,
                                    reason="empty action", audit_event=event)

        for rule in self._rules:
            try:
                if rule.matches(action):
                    reason = rule.reason or f"rule matched: {rule.pattern}"
                    event = self._audit(action, rule.layer, reason, actor, ctx)
                    return ApprovalDecision(
                        action=action, layer=rule.layer, rule=rule,
                        reason=reason,
                        needs_human=(rule.layer == RiskLayer.ASK),
                        audit_event=event)
            except Exception as exc:  # noqa: BLE001 - 规则解析失败 -> 保守不匹配
                log.debug("ApprovalPolicyTree.decide(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                continue

        event = self._audit(action, self._default_layer,
                             "default layer", actor, ctx)
        return ApprovalDecision(
            action=action, layer=self._default_layer,
            reason="default layer",
            needs_human=(self._default_layer == RiskLayer.ASK),
            audit_event=event)

    def _audit(self, action: str, layer: RiskLayer, reason: str,
               actor: str, context: Dict[str, Any]) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            action=action,
            decision=layer.value,
            reason=reason,
            actor=actor,
            context=dict(context),
            ts=time.time(),
        )
        # append-only: 追加到审计事件流, 不覆盖历史
        self._sink.append(event)
        return event

    def audit_log(self) -> List[Dict[str, Any]]:
        """导出审计事件流 (只读快照)。"""
        return [e.to_dict() for e in self._sink]
