"""E6 / E8 / R8 回归: 权限规则负向排除、MCP 工具名、安全配置强校验、异常 fail-closed。"""
from __future__ import annotations

import sys

import pytest

from tuan_cli.tools.permissions import PermissionPolicy, _effective_tool_name


class _Cfg:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)


def _policy(rules):
    return PermissionPolicy(_Cfg({"permissions.rules": rules}))


# ------------------------------------------------------------------ E6 负向排除
class TestNegativeRules:
    def test_exclude_blocks_a_broad_allow_rule(self):
        rules = [{"tool": "run_shell", "pattern": "git *", "action": "allow",
                  "exclude": "git push --force*"}]
        p = _policy(rules)
        assert p.match_rule("run_shell", {"command": "git status"}) == "allow"
        assert p.match_rule("run_shell", {"command": "git push --force origin main"}) is None

    def test_pattern_bang_syntax(self):
        rules = [{"tool": "run_shell", "pattern": "!git push --force*",
                  "action": "allow"}]
        p = _policy(rules)
        # "!..." 是排除模式, 不再作为正向匹配条件: 普通命令命中 allow, 被排除的不命中
        assert p.match_rule("run_shell", {"command": "git status"}) == "allow"
        assert p.match_rule("run_shell", {"command": "git push --force"}) is None

    def test_deny_rule_ignores_exclude_fail_closed(self):
        """拒绝规则不允许被 exclude 放宽。"""
        rules = [{"tool": "run_shell", "action": "deny", "exclude": "echo *"}]
        p = _policy(rules)
        assert p.match_rule("run_shell", {"command": "echo hi"}) == "deny"

    def test_exclude_matches_effective_mcp_name(self):
        rules = [{"tool": "mcp__*", "action": "allow", "exclude": "mcp__untrusted__*"}]
        p = _policy(rules)
        assert p.match_rule("mcp_call", {"server": "trusted", "tool": "read"}) == "allow"
        assert p.match_rule("mcp_call", {"server": "untrusted", "tool": "exec"}) is None

    def test_priority_still_deny_over_allow(self):
        rules = [
            {"tool": "run_shell", "pattern": "git *", "action": "allow", "exclude": "git push*"},
            {"tool": "run_shell", "action": "deny", "pattern": "git push*"},
        ]
        p = _policy(rules)
        assert p.match_rule("run_shell", {"command": "git push origin"}) == "deny"

    def test_inspect_reflects_exclude(self):
        rules = [{"tool": "run_shell", "pattern": "git *", "action": "allow",
                  "exclude": "git push --force*"}]
        p = _policy(rules)
        assert p.inspect("run_shell", {"command": "git status"})["action"] == "allow"
        assert p.inspect("run_shell", {"command": "git push --force"})["hits"] == []

    def test_invalid_rule_still_skipped(self):
        p = _policy([{"tool": "run_shell", "action": "typo"}, "not-a-dict"])
        assert p.match_rule("run_shell", {"command": "echo hi"}) is None


# ------------------------------------------------------------------ E6 MCP 工具名
class TestMcpToolNames:
    def test_effective_name(self):
        assert _effective_tool_name("mcp_call", {"server": "fs", "tool": "write"}) \
            == "mcp__fs__write"
        assert _effective_tool_name("mcp_call", {}) == "mcp_call"
        assert _effective_tool_name("run_shell", {"server": "x"}) == "run_shell"

    def test_rule_can_target_one_server(self):
        rules = [{"tool": "mcp__untrusted__*", "action": "deny"}]
        p = _policy(rules)
        assert p.match_rule("mcp_call", {"server": "untrusted", "tool": "exec"}) == "deny"
        assert p.match_rule("mcp_call", {"server": "trusted", "tool": "read"}) is None

    def test_param_rules_still_work(self):
        rules = [{"tool": "mcp_call", "param": "server", "value": "blocked*",
                  "action": "deny"}]
        p = _policy(rules)
        assert p.match_rule("mcp_call", {"server": "blocked-one", "tool": "x"}) == "deny"


# ------------------------------------------------------------------ R8 fail-closed
class TestHardeningEngineUnavailable:
    def test_yolo_does_not_auto_approve_when_engine_missing(self, monkeypatch):
        """红线引擎不可用 -> 绝不自动批准 (旧实现 except: pass 后 YOLO 放行)。"""
        monkeypatch.setitem(sys.modules, "tuan_cli.ext.safety_engine", None)
        p = PermissionPolicy(None)
        d = p.decide(
            type("T", (), {"name": "run_shell", "dangerous": True,
                           "yolo_confirm": False})(),
            {"command": "x" * 10001}, yolo=True)
        assert d.action == "confirm"
        assert "fail-closed" in d.reason


# ------------------------------------------------------------------ E8 schema
class _SchemaCfg:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur


class TestSecuritySchema:
    def test_clean_config_has_no_errors(self):
        from tuan_cli.config.security_schema import validate_security_config
        cfg = _SchemaCfg({"sandbox": {
            "enabled": True, "backend": "auto", "enforce_required": True,
            "allowed_domains": ["pypi.org"],
            "resource": {"deny_network_by_default": True,
                         "isolate_copy_threshold": "high", "max_timeout": 300},
        }})
        errors, _ = validate_security_config(cfg)
        assert errors == []

    def test_disabled_sandbox_is_error(self):
        from tuan_cli.config.security_schema import validate_security_config
        errors, _ = validate_security_config(
            _SchemaCfg({"sandbox": {"enabled": False}}))
        assert any("sandbox.enabled" in e and "裸执行" in e for e in errors)

    def test_enforce_required_false_is_error(self):
        from tuan_cli.config.security_schema import validate_security_config
        errors, _ = validate_security_config(
            _SchemaCfg({"sandbox": {"enforce_required": False}}))
        assert any("enforce_required" in e for e in errors)

    def test_unknown_backend_is_error(self):
        from tuan_cli.config.security_schema import validate_security_config
        errors, _ = validate_security_config(
            _SchemaCfg({"sandbox": {"backend": "magic"}}))
        assert any("backend" in e for e in errors)

    def test_malformed_rules_are_errors_not_silent(self):
        from tuan_cli.config.security_schema import validate_security_config
        cfg = _SchemaCfg({"permissions": {"rules": [
            {"tool": "run_shell", "action": "alow"},   # 拼写错误
            "not-a-dict",
            {"tool": "run_shell"},                     # 缺 action
        ]}})
        errors, warnings = validate_security_config(cfg)
        assert len(errors) >= 3
        assert any("静默跳过" in e for e in errors)

    def test_unknown_rule_key_warns(self):
        from tuan_cli.config.security_schema import validate_security_config
        _, warnings = validate_security_config(
            _SchemaCfg({"permissions": {"rules": [
                {"tool": "*", "action": "deny", "actionn": "allow"}]}}))
        assert any("未知键" in w for w in warnings)

    def test_default_deny_network_is_warning_only(self):
        from tuan_cli.config.security_schema import validate_security_config
        errors, warnings = validate_security_config(
            _SchemaCfg({"sandbox": {"resource": {"deny_network_by_default": False}}}))
        assert errors == []
        assert any("deny_network_by_default" in w for w in warnings)

    def test_type_errors(self):
        from tuan_cli.config.security_schema import validate_security_config
        cfg = _SchemaCfg({
            "sandbox": {"enabled": "yes", "allowed_domains": "pypi.org",
                        "resource": {"max_timeout": -1,
                                     "isolate_copy_threshold": "extreme"}},
            "permissions": {"rules": {"tool": "*"}},
        })
        errors, _ = validate_security_config(cfg)
        assert len(errors) >= 5

    def test_missing_fields_are_quiet(self):
        from tuan_cli.config.security_schema import validate_security_config
        errors, warnings = validate_security_config(_SchemaCfg({}))
        assert errors == [] and warnings == []

    def test_wired_into_config_validate(self):
        """`tuan config validate` 必须能看到安全配置的错误。"""
        from tuan_cli.config.validate import validate
        from tuan_cli.models import is_known_provider  # noqa: F401
        cfg = _SchemaCfg({
            "model": {"model": "m", "provider": "deepseek", "base_url": "https://x"},
            "sandbox": {"enabled": False},
        })
        errors, _ = validate(cfg)
        assert any("sandbox.enabled" in e for e in errors)
