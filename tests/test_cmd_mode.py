"""cmd_mode 单元测试 —— 五模式切换 CLI。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_mode as P


def _args(**kw) -> SimpleNamespace:
    base = dict(mode_cmd=None, mode_id=None, force=False)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr("tuan_cli.cli.cmd_mode.Console", _FakeConsole)


class _FakeConsole:
    def __init__(self, *a, **k):
        pass
    def print(self, *a, **k):
        pass


# ============================================================ _disp_len


class TestDispLen:
    def test_ascii(self):
        assert P._disp_len("hello") == 5

    def test_cjk(self):
        assert P._disp_len("中文") == 4

    def test_mixed(self):
        assert P._disp_len("ab中cd") == 6


# ============================================================ _pad


class TestPad:
    def test_short(self):
        assert P._pad("hi", 5) == "hi   "

    def test_exact(self):
        assert P._pad("hello", 5) == "hello"

    def test_cjk(self):
        assert P._pad("中", 4) == "中  "


# ============================================================ _platform


class TestPlatform:
    def test_returns_str(self):
        assert isinstance(P._platform(), str)


# ============================================================ _cap_text


class TestCapText:
    def test_denied(self):
        assert "禁用" in P._cap_text("chat", "shell", False)

    def test_denied_boundless(self):
        r = P._cap_text("boundless", "shell", False)
        assert "平台策略" in r

    def test_allowed_with_qualifier(self):
        r = P._cap_text("chat", "memory_write", True)
        assert "允许" in r
        assert "沙箱" in r

    def test_allowed_no_qualifier(self):
        r = P._cap_text("chat", "shell", True)
        assert "允许" in r


# ============================================================ cmd_mode dispatch


class TestModeList:
    def test_list(self):
        assert P.cmd_mode(_args(mode_cmd="list")) == 0


class TestModeCurrent:
    def test_current_ok(self, monkeypatch):
        monkeypatch.setattr(P, "_read_current", lambda: "chat")
        assert P.cmd_mode(_args(mode_cmd="current")) == 0

    def test_current_value_error(self, monkeypatch):
        monkeypatch.setattr(P, "_read_current",
                            lambda: (_ for _ in ()).throw(ValueError("bad")))
        assert P.cmd_mode(_args(mode_cmd="current")) == 1

    def test_current_other_error(self, monkeypatch):
        monkeypatch.setattr(P, "_read_current",
                            lambda: (_ for _ in ()).throw(RuntimeError("oops")))
        assert P.cmd_mode(_args(mode_cmd="current")) == 1


class TestModeShow:
    def test_show_current(self, monkeypatch):
        monkeypatch.setattr(P, "_read_current", lambda: "chat")
        assert P.cmd_mode(_args(mode_cmd="show")) == 0

    def test_show_explicit(self, monkeypatch):
        assert P.cmd_mode(_args(mode_cmd="show", mode_id="chat")) == 0

    def test_show_bad_id(self, monkeypatch):
        assert P.cmd_mode(_args(mode_cmd="show", mode_id="bogus")) == 1

    def test_show_read_error(self, monkeypatch):
        monkeypatch.setattr(P, "_read_current",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert P.cmd_mode(_args(mode_cmd="show")) == 1


class TestModeSwitch:
    def test_no_target(self, monkeypatch):
        assert P.cmd_mode(_args(mode_cmd="switch")) == 2

    def test_bad_target(self, monkeypatch):
        assert P.cmd_mode(_args(mode_cmd="switch", mode_id="bogus")) == 1

    def test_switch_ok(self, monkeypatch):
        monkeypatch.setattr(P, "switch_mode",
                            lambda target, **k: (True, "ok"))
        assert P.cmd_mode(_args(mode_cmd="switch", mode_id="chat")) == 0

    def test_switch_denied(self, monkeypatch):
        monkeypatch.setattr(P, "switch_mode",
                            lambda target, **k: (False, "denied"))
        assert P.cmd_mode(_args(mode_cmd="switch", mode_id="boundless")) == 1

    def test_switch_value_error(self, monkeypatch):
        monkeypatch.setattr(P, "switch_mode",
                            lambda target, **k: (_ for _ in ()).throw(ValueError("v")))
        assert P.cmd_mode(_args(mode_cmd="switch", mode_id="boundless")) == 1

    def test_switch_other_error(self, monkeypatch):
        monkeypatch.setattr(P, "switch_mode",
                            lambda target, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert P.cmd_mode(_args(mode_cmd="switch", mode_id="boundless")) == 1

    def test_switch_kernel_fail_ok(self, monkeypatch):
        monkeypatch.setattr(P, "switch_mode", lambda target, **k: (True, "ok"))
        assert P.cmd_mode(_args(mode_cmd="switch", mode_id="chat")) == 0


class TestModeUsage:
    def test_none(self):
        assert P.cmd_mode(_args()) == 2

    def test_unknown(self):
        assert P.cmd_mode(_args(mode_cmd="bogus")) == 2
