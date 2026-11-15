"""cmd_safe 测试 —— 安全总入口 (status/list/allow/deny/blacklist/suggest)。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from tuan_cli.cli import cmd_safe as P


# ---------------------------------------------------------------- fakes

class FakeWhitelist:
    def __init__(self, entries: List[Dict[str, str]] = None):
        self._entries = list(entries or [])
        self._path = "<mem>"

    def list(self):
        return list(self._entries)

    def add(self, command: str, description: str = "") -> bool:
        for e in self._entries:
            if e["command"].lower() == command.lower():
                return False
        self._entries.append({"command": command, "description": description})
        return True

    def remove(self, command: str) -> bool:
        for i, e in enumerate(self._entries):
            if e["command"].lower() == command.lower():
                self._entries.pop(i)
                return True
        return False


class FakeSafetyEngine:
    CRITICAL_PATTERNS = [(r"rm\s+-rf\s+/", "rm_rf_root")]
    HIGH_PATTERNS = [(r"dd\s+if=", "dd_raw")]
    MEDIUM_PATTERNS = [(r"shutdown", "shutdown_cmd")]

    def __init__(self, *a, **kw):
        pass

    def list_methods(self):
        return {"version": "1.0", "capabilities": ["score", "guard"]}

    def score(self, payload):
        cmd = payload.get("command", "")
        if "rm -rf /" in cmd:
            return {"risk": "critical", "score": 100, "block": True,
                    "reasons": ["删除根目录"], "suggestions": ["改用 trash-cli"]}
        if "curl | sh" in cmd:
            return {"risk": "high", "score": 70, "block": False,
                    "reasons": ["管道执行"], "suggestions": ["先下载再审计"]}
        return {"risk": "low", "score": 0, "block": False,
                "reasons": [], "suggestions": []}

    def is_redline(self, command: str) -> bool:
        return command in ("rm -rf /", ":(){ :|:& };:")


class FakeBlacklistOverride:
    _suppressed: set = set()

    def list_suppressed(self):
        return list(self._suppressed)

    def is_suppressed(self, label):
        return label in self._suppressed

    def suppress(self, keyword):
        if keyword in self._suppressed:
            return False
        self._suppressed.add(keyword)
        return True

    def release(self, keyword):
        if keyword in self._suppressed:
            self._suppressed.discard(keyword)
            return True
        return False


@pytest.fixture(autouse=True)
def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr("tuan_cli.core.whitelist.WhitelistManager",
                        lambda *a, **kw: FakeWhitelist([]))
    monkeypatch.setattr("tuan_cli.ext.safety_engine.SafetyEngine", FakeSafetyEngine)
    monkeypatch.setattr("tuan_cli.ext.safety_engine.is_redline",
                        lambda c: c in ("rm -rf /",))
    monkeypatch.setattr("tuan_cli.core.blacklist_override.list_suppressed",
                        lambda: [])
    monkeypatch.setattr("tuan_cli.core.blacklist_override.is_suppressed",
                        lambda label: False)
    monkeypatch.setattr("tuan_cli.core.blacklist_override.suppress",
                        lambda kw: True)
    monkeypatch.setattr("tuan_cli.core.blacklist_override.release",
                        lambda kw: True)
    # security_bus 与 security_policy 用 monkeypatch.setattr 动态处理


def _args(**kw):
    base = dict(safe_cmd=None, command=None, description=None, keyword=None,
                json=False, quick=False, out=None, check=False, full=False,
                release=False)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- 分发

class TestDispatch:
    def test_unknown_sub(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="nope"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "未知子命令" in out

    def test_default_status(self, capsys):
        rc = P.cmd_safe(_args())
        assert rc == 0
        assert "安全总览" in capsys.readouterr().out


# ---------------------------------------------------------------- status

class TestStatus:
    def test_status_ok(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="status"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "安全总览" in out
        assert "白名单" in out


# ---------------------------------------------------------------- list / allow / deny

class TestWhitelist:
    def test_list_empty(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="list"))
        assert rc == 0
        assert "白名单为空" in capsys.readouterr().out

    def test_list_entries(self, capsys, monkeypatch):
        monkeypatch.setattr("tuan_cli.core.whitelist.WhitelistManager",
                            lambda *a, **k: FakeWhitelist([
                                {"command": "pytest", "description": "测试"}]))
        rc = P.cmd_safe(_args(safe_cmd="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "pytest" in out

    def test_allow_ok(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="allow", command="pytest"))
        assert rc == 0
        assert "已加入白名单" in capsys.readouterr().out

    def test_allow_redline(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="allow", command="rm -rf /"))
        assert rc == 1
        assert "红线" in capsys.readouterr().out

    def test_allow_missing_command(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="allow"))
        assert rc == 1
        assert "用法" in capsys.readouterr().out

    def test_deny_ok(self, capsys, monkeypatch):
        monkeypatch.setattr("tuan_cli.core.whitelist.WhitelistManager",
                            lambda *a, **k: FakeWhitelist([
                                {"command": "pytest", "description": ""}]))
        rc = P.cmd_safe(_args(safe_cmd="deny", command="pytest"))
        assert rc == 0
        assert "已从白名单移除" in capsys.readouterr().out

    def test_deny_missing(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="deny", command="nonexistent"))
        assert rc == 0
        assert "不在白名单" in capsys.readouterr().out


# ---------------------------------------------------------------- blacklist

class TestBlacklist:
    def test_blacklist(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="blacklist"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "内置黑名单" in out


# ---------------------------------------------------------------- reduce / restore

class TestReduceRestore:
    def test_reduce_ok(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="reduce", keyword="dd"))
        assert rc == 0
        assert "已抑制" in capsys.readouterr().out

    def test_reduce_missing(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="reduce"))
        assert rc == 1
        assert "用法" in capsys.readouterr().out

    def test_restore_ok(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="restore", keyword="dd"))
        assert rc == 0
        assert "已恢复" in capsys.readouterr().out


# ---------------------------------------------------------------- suggest

class TestSuggest:
    def test_suggest_safe_command(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="suggest", command="ls -la"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "ls -la" in out

    def test_suggest_dangerous(self, capsys):
        rc = P.cmd_safe(_args(safe_cmd="suggest", command="rm -rf /"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "将被拦截" in out
        assert "替代" in out
