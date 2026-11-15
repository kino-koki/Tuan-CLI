"""cmd_loop tests -- Loop system observability CLI (list/current/info/hooks/markers)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from tuan_cli.cli import cmd_loop as P


def _args(**kw):
    base = dict(loop_cmd=None, json=False, name=None, test=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- dispatch

class TestDispatch:
    def test_unknown_sub(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="nope"))
        assert rc == 1
        assert "未知" in capsys.readouterr().out

    def test_default_list(self, capsys):
        rc = P.cmd_loop(_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "Loop" in out


# ---------------------------------------------------------------- list

class TestList:
    def test_list_text(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "react" in out or "planner" in out
        assert "当前" in out

    def test_list_json(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="list", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "count" in d and "current" in d and "loops" in d
        assert d["count"] >= 2
        names = [l["name"] for l in d["loops"]]
        assert "react" in names
        assert "plan_execute" in names


# ---------------------------------------------------------------- current

class TestCurrent:
    def test_current_text(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="current"))
        assert rc == 0
        assert "当前 Loop" in capsys.readouterr().out

    def test_current_json(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="current", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "current" in d
        assert "description" in d


# ---------------------------------------------------------------- info

class TestInfo:
    def test_info_known(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="info", name="react"))
        assert rc == 0
        assert "react" in capsys.readouterr().out

    def test_info_unknown(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="info", name="nope"))
        assert rc == 1
        assert "未知 Loop" in capsys.readouterr().out

    def test_info_json(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="info", name="react", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["name"] == "react"
        assert "description" in d


# ---------------------------------------------------------------- hooks

class TestHooks:
    def test_hooks_text(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="hooks"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "生命周期钩子" in out
        assert "should_nudge" in out

    def test_hooks_json(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="hooks", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        hooks = d["hooks"]
        assert len(hooks) >= 2
        for h in hooks:
            assert "name" in h
            assert "should_nudge" in h
            assert "on_task_start" in h
            assert "on_task_end" in h

    def test_hooks_filter_by_name(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="hooks", name="react"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "react" in out

    def test_hooks_filter_unknown(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="hooks", name="nope", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["hooks"] == []


# ---------------------------------------------------------------- markers

class TestMarkers:
    def test_markers_text(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="markers"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "完成标记" in out

    def test_markers_json(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="markers", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "count" in d and "markers" in d
        assert d["count"] > 0

    def test_markers_test_hit(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="markers", test="任务已完成"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "已完成" in out

    def test_markers_test_miss(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="markers", test="继续工作"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "未完成" in out

    def test_markers_test_json(self, capsys):
        rc = P.cmd_loop(_args(loop_cmd="markers", test="done", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "is_done" in d
        assert "matched" in d
