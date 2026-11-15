"""``tuan permissions`` CLI 的单元测试 (cmd_permissions.py)。

覆盖:
1. list 子命令: 空规则 / 有规则 / 非法规则跳过
2. test 子命令: JSON 参数解析 / 命中规则 / 未命中 / 优先级 deny > ask > allow
3. _fmt_rule 格式化 (param 形式 vs pattern 形式)

不依赖真实 config.yaml, 通过 monkeypatch Config 构造注入 rules。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tuan_cli.cli import cmd_permissions as P


def _args(sub: str = "list", tool: str = "", args_json: str = "{}",
          profile: str = "default", patch: str = None) -> SimpleNamespace:
    return SimpleNamespace(permissions_cmd=sub, tool=tool, args_json=args_json,
                           profile=profile, patch=patch)


class _FakeConfig:
    """只回答 permissions.rules 的假 Config。"""

    def __init__(self, rules):
        self._rules = rules

    def get(self, key, default=None):
        if key == "permissions.rules":
            return self._rules
        return default


def _patch_config(monkeypatch, rules) -> None:
    # cmd_permissions 里是 `from ..config import Config` 函数内导入,
    # 所以要 patch 源模块 tuan_cli.config.Config 而非 P.Config。
    import tuan_cli.config as _cfgmod

    monkeypatch.setattr(_cfgmod, "Config",
                        lambda profile="default", patch_file=None: _FakeConfig(rules))


# ============================================================ list 子命令


class TestList:
    """list 子命令: 列出 permissions.rules。"""

    def test_empty_rules(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [])
        rc = P.cmd_permissions(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "0 条" in out
        assert "(空)" in out

    def test_shows_rules(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [
            {"tool": "run_shell", "param": "command", "value": "rm -rf*", "action": "deny"},
            {"tool": "read_file", "pattern": "/etc/*", "action": "ask"},
        ])
        rc = P.cmd_permissions(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "2 条" in out
        assert "run_shell" in out
        assert "read_file" in out

    def test_skips_non_dict_rules(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [
            {"tool": "run_shell", "action": "deny"},
            "not-a-dict",
            42,
        ])
        rc = P.cmd_permissions(_args())
        out = capsys.readouterr().out
        assert rc == 0
        # 只打印 1 条 dict 规则
        assert out.count("#") == 1

    def test_default_sub_is_list(self, monkeypatch) -> None:
        _patch_config(monkeypatch, [])
        # 无 permissions_cmd 时默认走 list
        args = SimpleNamespace(tool="", args_json="{}", profile="default", patch=None)
        args.permissions_cmd = getattr(args, "permissions_cmd", "list")
        rc = P.cmd_permissions(args)
        assert rc == 0


# ============================================================ test 子命令


class TestTestSubcommand:
    """test 子命令: 测试某次工具调用会命中哪条规则 (只读, 不执行)。"""

    def test_json_parse_error(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [])
        rc = P.cmd_permissions(_args(sub="test", tool="run_shell", args_json="{invalid"))
        out = capsys.readouterr().out
        assert rc == 2
        assert "参数解析失败" in out

    def test_json_array_rejected(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [])
        rc = P.cmd_permissions(_args(sub="test", tool="run_shell", args_json="[1,2]"))
        out = capsys.readouterr().out
        assert rc == 2
        assert "JSON 对象" in out

    def test_no_rule_hit(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [
            {"tool": "run_shell", "param": "command", "value": "git *", "action": "allow"},
        ])
        rc = P.cmd_permissions(_args(sub="test", tool="read_file",
                                     args_json='{"path": "/etc/passwd"}'))
        out = capsys.readouterr().out
        assert rc == 0
        assert "无规则命中" in out

    def test_rule_hit_deny(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [
            {"tool": "run_shell", "param": "command", "value": "rm -rf*", "action": "deny"},
        ])
        rc = P.cmd_permissions(_args(sub="test", tool="run_shell",
                                     args_json='{"command": "rm -rf /"}'))
        out = capsys.readouterr().out
        assert rc == 0
        assert "命中 1 条" in out
        assert "deny" in out

    def test_priority_deny_over_allow(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [
            {"tool": "run_shell", "param": "command", "value": "git *", "action": "allow"},
            {"tool": "run_shell", "param": "command", "value": "git push --force*", "action": "deny"},
        ])
        rc = P.cmd_permissions(_args(sub="test", tool="run_shell",
                                     args_json='{"command": "git push --force"}'))
        out = capsys.readouterr().out
        assert rc == 0
        assert "最终动作: deny" in out

    def test_priority_ask_over_allow(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [
            {"tool": "run_shell", "param": "command", "value": "*", "action": "allow"},
            {"tool": "run_shell", "param": "command", "value": "rm *", "action": "ask"},
        ])
        rc = P.cmd_permissions(_args(sub="test", tool="run_shell",
                                     args_json='{"command": "rm -rf /tmp/x"}'))
        out = capsys.readouterr().out
        assert rc == 0
        assert "最终动作: ask" in out

    def test_multiple_hits_shown(self, monkeypatch, capsys) -> None:
        _patch_config(monkeypatch, [
            {"tool": "*", "action": "ask"},
            {"tool": "run_shell", "param": "command", "value": "git *", "action": "allow"},
        ])
        rc = P.cmd_permissions(_args(sub="test", tool="run_shell",
                                     args_json='{"command": "git status"}'))
        out = capsys.readouterr().out
        assert rc == 0
        assert "命中 2 条" in out
        assert "#0" in out and "#1" in out


# ============================================================ _fmt_rule


class TestFmtRule:
    """_fmt_rule 格式化 (param 形式 vs pattern 形式)。"""

    def test_param_form(self) -> None:
        rule = {"tool": "run_shell", "param": "command", "value": "rm -rf*", "action": "deny"}
        s = P._fmt_rule(rule)
        assert "deny" in s
        assert "run_shell(command=rm -rf*)" in s

    def test_pattern_form(self) -> None:
        rule = {"tool": "read_file", "pattern": "/etc/*", "action": "ask"}
        s = P._fmt_rule(rule)
        assert "ask" in s
        assert "read_file:/etc/*" in s

    def test_missing_fields_default(self) -> None:
        rule = {"tool": "run_shell", "action": "deny"}
        s = P._fmt_rule(rule)
        assert "run_shell" in s
        assert "deny" in s
