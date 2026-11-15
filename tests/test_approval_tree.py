"""阶段 C 测试: 人机协同审批增强 (approval_policy)。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuan_cli.ui.approval_policy import (  # noqa: E402
    ApprovalPolicyTree,
    ApprovalRule,
    RiskLayer,
)


# ------------------------------------------------------------- 分层路由
class TestLayerRouting:
    def test_allow_layer_auto_passes(self):
        tree = ApprovalPolicyTree(
            rules=[ApprovalRule(pattern="git status", layer=RiskLayer.ALLOW)],
            default_layer=RiskLayer.ASK,
        )
        d = tree.decide("git status")
        assert d.layer == RiskLayer.ALLOW
        assert d.allowed is True
        assert d.needs_human is False

    def test_ask_layer_needs_human(self):
        tree = ApprovalPolicyTree(default_layer=RiskLayer.ASK)
        d = tree.decide("rm -rf /tmp/x")
        assert d.layer == RiskLayer.ASK
        assert d.needs_approval is True
        assert d.needs_human is True

    def test_deny_layer_rejects(self):
        tree = ApprovalPolicyTree(
            rules=[ApprovalRule(pattern="exact:rm -rf /", layer=RiskLayer.DENY)],
            default_layer=RiskLayer.ALLOW,
        )
        d = tree.decide("rm -rf /")
        assert d.layer == RiskLayer.DENY
        assert d.allowed is False

    def test_default_layer_is_fail_safe_ask(self):
        # 不指定 default_layer => 保守 ASK (绝不 fall-through 到 allow)
        tree = ApprovalPolicyTree()
        d = tree.decide("some unknown action")
        assert d.layer == RiskLayer.ASK

    def test_empty_action_is_denied(self):
        tree = ApprovalPolicyTree(default_layer=RiskLayer.ALLOW)
        d = tree.decide("")
        assert d.layer == RiskLayer.DENY
        d2 = tree.decide("   ")
        assert d2.layer == RiskLayer.DENY


# ------------------------------------------------------------- 规则优先级
class TestRulePriority:
    def test_higher_priority_rule_wins(self):
        tree = ApprovalPolicyTree(rules=[
            ApprovalRule(pattern="git *", layer=RiskLayer.ALLOW, priority=1),
            ApprovalRule(pattern="git push --force", layer=RiskLayer.DENY,
                         priority=10),
        ])
        # push --force 命中高优先级 DENY 规则
        assert tree.decide("git push --force").layer == RiskLayer.DENY
        # 普通 git 命令命中低优先级 ALLOW
        assert tree.decide("git status").layer == RiskLayer.ALLOW

    def test_wildcard_prefix_matching(self):
        tree = ApprovalPolicyTree(
            rules=[ApprovalRule(pattern="git *", layer=RiskLayer.ALLOW)])
        assert tree.decide("git commit -m x").layer == RiskLayer.ALLOW
        assert tree.decide("gh pr list").layer == RiskLayer.ASK

    def test_exact_match(self):
        # 默认 ALLOW: 只有精确命中规则的 git push 需审批, 其它放行
        tree = ApprovalPolicyTree(
            rules=[ApprovalRule(pattern="exact:git push", layer=RiskLayer.ASK)],
            default_layer=RiskLayer.ALLOW)
        assert tree.decide("git push").needs_approval
        assert not tree.decide("git pull").needs_approval
        assert tree.decide("git pull").layer == RiskLayer.ALLOW

    def test_dynamic_rule_insert(self):
        tree = ApprovalPolicyTree(rules=[
            ApprovalRule(pattern="git *", layer=RiskLayer.ALLOW, priority=1)])
        assert tree.decide("git push").layer == RiskLayer.ALLOW
        tree.add_rule(ApprovalRule(
            pattern="git push", layer=RiskLayer.ASK, priority=5))
        assert tree.decide("git push").needs_approval


# ------------------------------------------------------------- 审计联动
class TestAuditLinkage:
    def test_each_decision_writes_audit_event(self):
        tree = ApprovalPolicyTree(default_layer=RiskLayer.ASK)
        tree.decide("git status", actor="human", context={"cwd": "/tmp"})
        tree.decide("rm -rf /", actor="agent")
        log = tree.audit_log()
        assert len(log) == 2
        assert log[0]["decision"] == "ask"
        assert log[1]["decision"] == "ask"
        assert log[0]["actor"] == "human"
        assert log[0]["context"] == {"cwd": "/tmp"}
        assert log[1]["actor"] == "agent"
        assert log[0]["ts"] > 0

    def test_audit_append_only_no_overwrite(self):
        tree = ApprovalPolicyTree(rules=[
            ApprovalRule(pattern="git status", layer=RiskLayer.ALLOW)])
        tree.decide("git status", actor="a")
        first_id = tree.audit_log()[0]["event_id"]
        tree.decide("git status", actor="a")
        log = tree.audit_log()
        assert len(log) == 2
        # 每条事件有独立 ID (append-only)
        assert log[0]["event_id"] == first_id
        assert log[0]["event_id"] != log[1]["event_id"]

    def test_rule_reason_propagates_to_audit(self):
        tree = ApprovalPolicyTree(rules=[
            ApprovalRule(pattern="git push", layer=RiskLayer.DENY,
                          reason="force push is banned")])
        tree.decide("git push")
        log = tree.audit_log()
        assert log[0]["reason"] == "force push is banned"
        assert log[0]["decision"] == "deny"

    def test_external_sink_collects_events(self):
        sink = []
        tree = ApprovalPolicyTree(rules=[
            ApprovalRule(pattern="git *", layer=RiskLayer.ALLOW)],
            audit_sink=sink)
        tree.decide("git commit")
        assert len(sink) == 1
        assert sink[0].to_dict()["decision"] == "allow"
