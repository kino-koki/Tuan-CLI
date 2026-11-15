"""cmd_hooks 单元测试 —— 用户级 Hooks 管理 CLI。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_hooks as P


def _args(**kw) -> SimpleNamespace:
    base = dict(hook_cmd=None, workspace=None, event=None, tool=None,
                tool_input=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(P, "ui", SimpleNamespace(info=lambda *a, **k: None))


class _FakeHookManager:
    def __init__(self, config, workspace, kernel=None):
        self.config = config
        self.workspace = workspace
        self.enabled = False
        self.allow_blocking = False
        self.allow_edit_args = False

    def list_hooks(self):
        return []

    def enabled_for(self, event):
        return False


def _fake_kernel(config_data=None):
    cfg = SimpleNamespace(get=lambda key, default=None: default)
    return SimpleNamespace(require=lambda k: cfg, get=lambda k: None)


# ============================================================ list


class TestHooksList:
    def test_build_fail(self, monkeypatch):
        monkeypatch.setattr(P, "build_kernel",
                            lambda: (_ for _ in ()).throw(RuntimeError("no")))
        assert P.cmd_hooks(_args(hook_cmd="list")) == 1

    def test_no_hooks(self, monkeypatch):
        monkeypatch.setattr(P, "build_kernel", lambda: _fake_kernel())
        monkeypatch.setattr(P, "HookManager", _FakeHookManager)
        assert P.cmd_hooks(_args(hook_cmd="list")) == 0

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(P, "build_kernel", lambda: _fake_kernel())
        monkeypatch.setattr(P, "HookManager", _FakeHookManager)
        assert P.cmd_hooks(_args(hook_cmd="list")) == 0

    def test_with_hooks(self, monkeypatch):
        class _FullMgr(_FakeHookManager):
            def __init__(self, config, workspace, kernel=None):
                super().__init__(config, workspace, kernel)
                self.enabled = True
                self.allow_blocking = True

            def list_hooks(self):
                return [
                    dict(event="PreToolUse", matcher="Bash",
                         blocking=True, allow_edit_args=False,
                         command=["audit.sh"], description="audit commands"),
                    dict(event="SessionStart", matcher="*",
                         blocking=False, allow_edit_args=True,
                         command=["notify.sh"], description=""),
                ]
        monkeypatch.setattr(P, "build_kernel", lambda: _fake_kernel())
        monkeypatch.setattr(P, "HookManager", _FullMgr)
        assert P.cmd_hooks(_args(hook_cmd="list")) == 0


# ============================================================ test


class TestHooksTest:
    def test_bad_json(self, monkeypatch):
        monkeypatch.setattr(P, "build_kernel", lambda: _fake_kernel())
        assert P.cmd_hooks(_args(hook_cmd="test", tool_input="not json")) == 1

    def test_build_fail(self, monkeypatch):
        monkeypatch.setattr(P, "build_kernel",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert P.cmd_hooks(_args(hook_cmd="test")) == 1

    def test_event_not_configured(self, monkeypatch):
        monkeypatch.setattr(P, "build_kernel", lambda: _fake_kernel())
        monkeypatch.setattr(P, "HookManager", _FakeHookManager)
        assert P.cmd_hooks(_args(hook_cmd="test", event="SessionStart")) == 0


# ============================================================ enable/disable


class TestHooksEnableDisable:
    def test_enable(self, monkeypatch):
        cfg = SimpleNamespace(set_user=lambda k, v: None)
        monkeypatch.setattr("tuan_cli.config.Config", lambda: cfg)
        assert P.cmd_hooks(_args(hook_cmd="enable")) == 0

    def test_disable(self, monkeypatch):
        cfg = SimpleNamespace(set_user=lambda k, v: None)
        monkeypatch.setattr("tuan_cli.config.Config", lambda: cfg)
        assert P.cmd_hooks(_args(hook_cmd="disable")) == 0

    def test_config_fail(self, monkeypatch):
        monkeypatch.setattr("tuan_cli.config.Config",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert P.cmd_hooks(_args(hook_cmd="enable")) == 1


# ============================================================ dispatch


class TestHooksDispatch:
    def test_unknown(self):
        assert P.cmd_hooks(_args(hook_cmd="bogus")) == 1

    def test_none_is_unknown(self):
        assert P.cmd_hooks(_args()) == 1
