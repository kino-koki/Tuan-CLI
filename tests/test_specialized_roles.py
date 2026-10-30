"""SpecializedRoles 专项测试 —— 专业化角色系统。

覆盖 tuan_cli.core.specialized_roles:
- AgentRole.to_system_extra (质量标准/协作提示)
- 预定义 ROLES 注册 (reviewer/tester/debugger/architect/security_auditor/documenter/implementer)
- get_role / list_roles
- suggest_role 关键词匹配 (各分支 + 默认 implementer)
"""

from __future__ import annotations

import pytest

from tuan_cli.core.specialized_roles import (
    ARCHITECT,
    DEBUGGER,
    DOCUMENTER,
    IMPLEMENTER,
    REVIEWER,
    ROLES,
    SECURITY_AUDITOR,
    TESTER,
    AgentRole,
    get_role,
    list_roles,
    suggest_role,
)


# ---------------------------------------------------------------- AgentRole

def test_to_system_extra_basic():
    r = AgentRole(
        role_id="x", name="专家", description="测试专家",
        system_prompt="sp",
    )
    extra = r.to_system_extra()
    assert "你的角色是 专家" in extra
    assert "测试专家" in extra
    assert "质量标准" not in extra  # 无质量标准则不输出


def test_to_system_extra_with_criteria_and_hints():
    r = AgentRole(
        role_id="x", name="专家", description="desc",
        system_prompt="sp",
        quality_criteria=["标准A", "标准B"],
        collaboration_hints=["提示1"],
    )
    extra = r.to_system_extra()
    assert "质量标准:" in extra
    assert "- 标准A" in extra
    assert "- 标准B" in extra
    assert "协作提示:" in extra
    assert "- 提示1" in extra


def test_agent_role_defaults():
    r = AgentRole(role_id="x", name="n", description="d", system_prompt="sp")
    assert r.recommended_tools == set()
    assert r.excluded_tools == set()
    assert r.quality_criteria == []
    assert r.collaboration_hints == []
    assert r.max_iterations == 15
    assert r.preferred_model_tier == "any"


# ---------------------------------------------------------------- 预定义角色

def test_all_predefined_roles_registered():
    expected = {
        "reviewer", "tester", "debugger", "architect",
        "security_auditor", "documenter", "implementer",
    }
    assert set(ROLES.keys()) == expected


def test_predefined_roles_quality():
    assert REVIEWER.role_id == "reviewer"
    assert "read_file" in REVIEWER.recommended_tools
    assert "run_shell" in REVIEWER.excluded_tools
    assert REVIEWER.max_iterations == 10
    assert REVIEWER.preferred_model_tier == "strong"
    assert len(REVIEWER.quality_criteria) >= 3


def test_predefined_roles_implementer_default():
    assert IMPLEMENTER.role_id == "implementer"
    assert IMPLEMENTER.preferred_model_tier == "weak"


def test_predefined_roles_architect():
    assert ARCHITECT.role_id == "architect"
    assert ARCHITECT.max_iterations == 8
    assert "write_file" in ARCHITECT.excluded_tools


def test_predefined_roles_security():
    assert SECURITY_AUDITOR.role_id == "security_auditor"
    assert SECURITY_AUDITOR.preferred_model_tier == "strong"


def test_predefined_roles_documenter():
    assert DOCUMENTER.role_id == "documenter"
    assert DOCUMENTER.preferred_model_tier == "weak"


def test_predefined_roles_tester_debugger():
    assert TESTER.role_id == "tester"
    assert DEBUGGER.role_id == "debugger"
    assert "run_shell" in TESTER.recommended_tools


# ---------------------------------------------------------------- get_role / list_roles

def test_get_role_known():
    assert get_role("reviewer") is REVIEWER
    assert get_role("implementer") is IMPLEMENTER


def test_get_role_unknown_returns_none():
    assert get_role("nope") is None


def test_list_roles_returns_all():
    roles = list_roles()
    assert len(roles) == 7
    assert {r.role_id for r in roles} == set(ROLES.keys())


# ---------------------------------------------------------------- suggest_role

@pytest.mark.parametrize("desc,expected", [
    ("请审查这段代码", "reviewer"),
    ("review the pr", "reviewer"),
    ("需要审计安全配置", "security_auditor"),  # "安全" 命中 security_auditor (reviewer 关键词无"审计")
    ("写单元测试", "tester"),
    ("run pytest", "tester"),
    ("coverage 不足", "tester"),
    ("调试这个 bug", "debugger"),
    ("fix the error", "debugger"),
    ("查看 traceback", "debugger"),
    ("设计新架构", "architect"),
    ("refactor 这个模块", "architect"),
    # "检查" 在 reviewer 关键词中排在 security_auditor 之前, 顺序优先 -> reviewer
    ("检查安全漏洞", "reviewer"),
    ("vulnerability scan", "security_auditor"),
    ("写文档", "documenter"),
    ("update readme", "documenter"),
    ("实现新功能", "implementer"),
    ("编写代码", "implementer"),
])
def test_suggest_role_keyword_match(desc, expected):
    assert suggest_role(desc) == expected


def test_suggest_role_default_implementer():
    assert suggest_role("完全无关的描述") == "implementer"


def test_suggest_role_case_insensitive():
    assert suggest_role("RUN PYTEST") == "tester"
    assert suggest_role("Design System") == "architect"
