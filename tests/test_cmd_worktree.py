"""cmd_worktree 单元测试 —— git worktree 并行实验 CLI。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_worktree as P


def _args(**kw) -> SimpleNamespace:
    base = dict(worktree_cmd=None, name="", workspace=None)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeLayer:
    def __init__(self, ws):
        self.ws = ws
        self.created = []

    def create(self, name):
        self.created.append(name)
        return SimpleNamespace(path=f".tuan/worktrees/{name}", branch=name)

    def remove(self, name):
        return f".tuan/worktrees/{name}"

    def switch(self, name):
        return f".tuan/worktrees/{name}"

    def list(self):
        return [
            SimpleNamespace(name="exp-1", head="abc1234", branch="exp-1",
                            path=".tuan/worktrees/exp-1"),
            SimpleNamespace(name="exp-2", head="def5678", branch="exp-2",
                            path=".tuan/worktrees/exp-2"),
        ]


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
    monkeypatch.setattr("tuan_cli.core.worktree_layer.WorktreeLayer", _FakeLayer)


# ============================================================ create


class TestWorktreeCreate:
    def test_no_name(self):
        assert P.cmd_worktree(_args(worktree_cmd="create")) == 1

    def test_create_ok(self):
        assert P.cmd_worktree(_args(worktree_cmd="create", name="feature")) == 0

    def test_create_error(self, monkeypatch):
        from tuan_cli.core.worktree_layer import WorktreeError
        class _FailLayer(_FakeLayer):
            def create(self, name):
                raise WorktreeError("not a git repo")
        monkeypatch.setattr("tuan_cli.core.worktree_layer.WorktreeLayer", _FailLayer)
        assert P.cmd_worktree(_args(worktree_cmd="create", name="x")) == 1


# ============================================================ remove


class TestWorktreeRemove:
    def test_no_name(self):
        assert P.cmd_worktree(_args(worktree_cmd="remove")) == 1

    def test_remove_ok(self):
        assert P.cmd_worktree(_args(worktree_cmd="remove", name="x")) == 0

    def test_remove_error(self, monkeypatch):
        from tuan_cli.core.worktree_layer import WorktreeError
        class _FailLayer(_FakeLayer):
            def remove(self, name):
                raise WorktreeError("not found")
        monkeypatch.setattr("tuan_cli.core.worktree_layer.WorktreeLayer", _FailLayer)
        assert P.cmd_worktree(_args(worktree_cmd="remove", name="x")) == 1


# ============================================================ switch


class TestWorktreeSwitch:
    def test_no_name(self):
        assert P.cmd_worktree(_args(worktree_cmd="switch")) == 1

    def test_switch_ok(self):
        assert P.cmd_worktree(_args(worktree_cmd="switch", name="x")) == 0


# ============================================================ list


class TestWorktreeList:
    def test_empty(self, monkeypatch):
        class _EmptyLayer(_FakeLayer):
            def list(self):
                return []
        monkeypatch.setattr("tuan_cli.core.worktree_layer.WorktreeLayer", _EmptyLayer)
        assert P.cmd_worktree(_args(worktree_cmd="list")) == 0

    def test_with_items(self):
        assert P.cmd_worktree(_args(worktree_cmd="list")) == 0

    def test_default_is_list(self):
        assert P.cmd_worktree(_args()) == 0
