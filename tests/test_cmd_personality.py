"""cmd_personality 单元测试 —— 人设管理 CLI。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_personality as P


def _args(**kw) -> SimpleNamespace:
    base = dict(personality_cmd=None, name="")
    base.update(kw)
    return SimpleNamespace(**base)


# ============================================================ cmd_personality list


class TestPersonalityList:
    def test_list_ok(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        assert P.cmd_personality(_args(personality_cmd="list")) == 0

    def test_default_is_list(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        assert P.cmd_personality(_args()) == 0


# ============================================================ cmd_personality show


class TestPersonalityShow:
    def test_show_ok(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        assert P.cmd_personality(_args(personality_cmd="show")) == 0


# ============================================================ cmd_personality set


class TestPersonalitySet:
    def test_no_name(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        assert P.cmd_personality(_args(personality_cmd="set")) == 1

    def test_set_ok(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        monkeypatch.setattr("tuan_cli.app.build_kernel",
                            lambda: SimpleNamespace(
                                require=lambda k: SimpleNamespace(),
                                get=lambda k: SimpleNamespace(
                                    update_user=lambda k, v: None)))
        assert P.cmd_personality(_args(personality_cmd="set", name="苏格拉底")) == 0

    def test_set_kernel_fail(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        monkeypatch.setattr("tuan_cli.app.build_kernel",
                            lambda: (_ for _ in ()).throw(RuntimeError("no")))
        assert P.cmd_personality(_args(personality_cmd="set", name="x")) == 1


# ============================================================ cmd_personality auto


class TestPersonalityAuto:
    def test_auto_ok(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        monkeypatch.setattr("tuan_cli.app.build_kernel",
                            lambda: SimpleNamespace(
                                require=lambda k: SimpleNamespace(),
                                get=lambda k: SimpleNamespace(
                                    update_user=lambda k, v: None)))
        assert P.cmd_personality(_args(personality_cmd="auto")) == 0

    def test_auto_kernel_fail(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        monkeypatch.setattr("tuan_cli.app.build_kernel",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert P.cmd_personality(_args(personality_cmd="auto")) == 1


# ============================================================ unknown


class TestPersonalityUnknown:
    def test_unknown(self, monkeypatch):
        import builtins
        monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
        assert P.cmd_personality(_args(personality_cmd="bogus")) == 1
