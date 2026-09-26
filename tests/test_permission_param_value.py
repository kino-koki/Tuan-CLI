"""测试: Tool(param:value) 精确粒度权限匹配 (对标 Claude Code 三层权限)。

覆盖:
- 基本匹配: tool glob + param 精确命中
- value glob 通配 (rm -rf* / *.env)
- 嵌套参数 (config.model, 点号路径)
- 参数缺失 / 值不匹配时规则不生效 (回退)
- deny / ask / allow 三种 action
- 与旧式 tool+pattern 规则共存 (向后兼容)
"""

from __future__ import annotations

from qingxiaotuan.runtime.tools.permission import match_param_value
from qingxiaotuan.tools.permissions import PermissionPolicy


class _Cfg:
    def __init__(self, rules):
        self.rules = rules

    def get(self, key, default=None):
        return self.rules if key == "permissions.rules" else default


def _policy(rules) -> PermissionPolicy:
    return PermissionPolicy(_Cfg(rules))


# --------------------------------------------------------- runtime 层 match_param_value

def test_match_param_value_basic():
    rule = {"tool": "run_shell", "param": "command", "value": "rm -rf*", "action": "deny"}
    assert match_param_value(rule, "run_shell", {"command": "rm -rf /"}) is True
    assert match_param_value(rule, "run_shell", {"command": "git status"}) is False
    # 工具名不命中
    assert match_param_value(rule, "edit_file", {"command": "rm -rf /"}) is False


def test_match_param_value_returns_none_for_legacy_rules():
    # 无 param/value 字段 -> None, 调用方走旧 pattern 逻辑
    legacy = {"tool": "run_shell", "pattern": "git *", "action": "allow"}
    assert match_param_value(legacy, "run_shell", {"command": "git push"}) is None


def test_match_param_value_nested():
    rule = {"tool": "deploy", "param": "config.model", "value": "prod-*", "action": "ask"}
    args = {"config": {"model": "prod-v3", "region": "cn"}}
    assert match_param_value(rule, "deploy", args) is True
    assert match_param_value(rule, "deploy", {"config": {"model": "stg-v1"}}) is False
    # 嵌套路径缺失
    assert match_param_value(rule, "deploy", {"config": {}}) is False


# --------------------------------------------------------- 生产决策层 (tools/permissions)

def test_live_policy_deny_on_param_value_match():
    pol = _policy([
        {"tool": "run_shell", "param": "command", "value": "rm -rf*", "action": "deny"},
    ])
    assert pol.match_rule("run_shell", {"command": "rm -rf build"}) == "deny"
    # 不匹配 -> None (走默认决策)
    assert pol.match_rule("run_shell", {"command": "git status"}) is None


def test_live_policy_glob_value_and_ask():
    pol = _policy([
        {"tool": "edit_file", "param": "file_path", "value": "*.env", "action": "ask"},
    ])
    assert pol.match_rule("edit_file", {"file_path": ".env"}) == "ask"
    assert pol.match_rule("edit_file", {"file_path": "secrets/prod.env"}) == "ask"
    assert pol.match_rule("edit_file", {"file_path": "README.md"}) is None


def test_live_policy_allow_action():
    pol = _policy([
        {"tool": "web_fetch", "param": "url", "value": "https://example.com/*", "action": "allow"},
    ])
    assert pol.match_rule("web_fetch", {"url": "https://example.com/x"}) == "allow"
    assert pol.match_rule("web_fetch", {"url": "https://evil.com/x"}) is None


def test_param_value_miss_falls_through_to_other_rules():
    # deny 规则未命中参数 -> 后面的 allow 规则仍可生效
    pol = _policy([
        {"tool": "run_shell", "param": "command", "value": "rm -rf*", "action": "deny"},
        {"tool": "run_shell", "action": "allow"},
    ])
    # 安全命令: deny 未命中 -> allow 命中
    assert pol.match_rule("run_shell", {"command": "pytest -q"}) == "allow"
    # 危险命令: deny 命中, deny > allow
    assert pol.match_rule("run_shell", {"command": "rm -rf /"}) == "deny"


def test_legacy_pattern_rules_still_work():
    pol = _policy([
        {"tool": "run_shell", "pattern": "git *", "action": "allow"},
    ])
    assert pol.match_rule("run_shell", {"command": "git push origin"}) == "allow"
    assert pol.match_rule("run_shell", {"command": "rm -rf build"}) is None


def test_inspect_reports_matched_rules():
    pol = _policy([
        {"tool": "run_shell", "param": "command", "value": "rm -rf*", "action": "deny"},
        {"tool": "run_shell", "action": "allow"},
    ])
    result = pol.inspect("run_shell", {"command": "rm -rf /"})
    assert result["action"] == "deny"
    assert len(result["hits"]) == 2  # param 规则与通用 allow 都命中
    result2 = pol.inspect("run_shell", {"command": "pytest -q"})
    assert result2["action"] == "allow"
    assert [h["index"] for h in result2["hits"]] == [1]
