"""cmd_boundary 单元测试 —— 四层边界决策预判 CLI。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_boundary as P


def _args(**kw) -> SimpleNamespace:
    base = dict(boundary_cmd=None, task="", json=False)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(P, "Config", lambda **kw: SimpleNamespace(
        get=lambda key, default=None: default))


# ============================================================ _isolate_reason


class TestIsolateReason:
    def test_empty(self):
        assert P._isolate_reason("") == "未触发"

    def test_long_task(self):
        r = P._isolate_reason("a" * 501)
        assert "501" in r

    def test_keyword_simultaneous(self):
        assert "同时" in P._isolate_reason("实现A 同时实现B")

    def test_keyword_parallel(self):
        assert "并行" in P._isolate_reason("并行处理多个任务")

    def test_no_trigger(self):
        assert P._isolate_reason("写一个简短的函数") == "未触发"


# ============================================================ _worktree_reason


class TestWorktreeReason:
    def test_empty(self):
        assert P._worktree_reason("") == "未触发"

    def test_plan_a(self):
        assert "方案a" in P._worktree_reason("用方案A实现")

    def test_compare(self):
        assert "对比" in P._worktree_reason("对比两种方法")

    def test_alternative(self):
        assert "另一种" in P._worktree_reason("试试另一种思路")

    def test_no_trigger(self):
        assert P._worktree_reason("写一个函数") == "未触发"


# ============================================================ cmd_boundary check


class TestBoundaryCheck:
    def test_empty_task(self):
        assert P.cmd_boundary(_args(boundary_cmd="check")) == 1

    def test_simple_task_text(self):
        assert P.cmd_boundary(_args(boundary_cmd="check", task="写函数")) == 0

    def test_parallel_task_text(self):
        assert P.cmd_boundary(_args(boundary_cmd="check",
                                    task="方案A用Redis 方案B用Memcached")) == 0

    def test_json_mode(self, capsys):
        assert P.cmd_boundary(_args(boundary_cmd="check", task="同时做两件事",
                                    json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["isolate_subagent"] is True
        assert "isolate_reason" in data
        assert "worktree_reason" in data
        assert data["chat_handoff_threshold"] >= 1


# ============================================================ cmd_boundary status


class TestBoundaryStatus:
    def test_text(self):
        assert P.cmd_boundary(_args(boundary_cmd="status")) == 0

    def test_json(self, capsys):
        assert P.cmd_boundary(_args(boundary_cmd="status", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert "project.auto_init" in data
        assert "subagent.auto_isolate" in data
        assert "worktree.auto_create" in data
        assert "chat.handoff_threshold" in data


# ============================================================ dispatch


class TestBoundaryDispatch:
    def test_default_is_check(self):
        assert P.cmd_boundary(_args(task="test")) == 0

    def test_unknown(self):
        assert P.cmd_boundary(_args(boundary_cmd="bogus")) == 1
