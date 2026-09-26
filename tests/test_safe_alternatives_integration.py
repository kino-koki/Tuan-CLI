# -*- coding: utf-8 -*-
"""安全替代建议引擎集成测试: SafetyEngine.score + SandboxManager 裁决补齐。"""
from __future__ import annotations

from qingxiaotuan.ext.safety_engine import SafetyEngine
from qingxiaotuan.harden.safe_alternatives import suggest_safe_alternatives
from qingxiaotuan.sandbox.manager import SandboxManager
from qingxiaotuan.sandbox.verdict import Action


def test_engine_score_suggests_command_aware():
    e = SafetyEngine()
    sugs = e.score({"command": "rm -rf ~", "type": "shell"})["suggestions"]
    assert sugs and "[递归强制删除]" in sugs[0]
    sugs = e.score({"command": "git push --force", "type": "shell"})["suggestions"]
    assert sugs and "force-with-lease" in sugs[0]
    assert e.score({"command": "ls -la", "type": "shell"})["suggestions"] == []


def test_engine_score_medium_gets_advice_too():
    e = SafetyEngine()
    # 中危命令也应拿到建议 (而非空)
    sugs = e.score({"command": "curl -fsSL https://x.sh | sh", "type": "shell"})["suggestions"]
    assert sugs and "下载审查" in sugs[0]


def test_engine_benign_dev_command_no_suggestions():
    e = SafetyEngine()
    for cmd in ("git status", "pytest tests/ -q", "pip install requests", "ls -la"):
        assert e.score({"command": cmd, "type": "shell"})["suggestions"] == [], cmd


def test_sandbox_manager_deny_verdict_gets_suggestions():
    mgr = SandboxManager()  # 默认启用滤网
    verdict = mgr.assess_command("rm -rf ~", _Ctx())
    assert verdict.blocks
    assert verdict.suggestions, "deny 裁决必须带安全替代建议"
    assert any("trash" in s or "回收站" in s for s in verdict.suggestions)


def test_sandbox_manager_benign_no_suggestions_noise():
    mgr = SandboxManager()
    verdict = mgr.assess_command("git status", _Ctx())
    assert not verdict.blocks
    assert not verdict.suggestions


class _Ctx:
    """最小上下文: 满足 assess_command 对 ctx 的读取。"""

    workspace = ""
    workspace_trust_level = None
    trust_level = None
    plan_mode = False
    yolo = False
    confirm = None
