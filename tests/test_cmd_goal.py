"""cmd_goal 单元测试 —— 持久化 Goal 状态只读查看 CLI。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_goal as P


def _args(**kw) -> SimpleNamespace:
    base = dict(goal_cmd=None, json=False, workspace=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _goal_state(**kw):
    base = dict(
        goal_id="g1", description="Build feature X", status="in_progress",
        iterations=3, created_at="2025-01-15T10:00:00Z",
        steps=[
            {"id": "1", "description": "Plan", "status": "done"},
            {"id": "2", "description": "Implement", "status": "in_progress"},
            {"id": "3", "description": "Test", "status": "pending"},
        ],
    )
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _patch_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("TUAN_WORKSPACE", str(tmp_path))
    return tmp_path


def _write_goal(tmp_path, state):
    ppath = tmp_path / ".tuan" / "goal.json"
    ppath.parent.mkdir(parents=True, exist_ok=True)
    ppath.write_text(json.dumps(state), encoding="utf-8")


# ============================================================ _fmt_status


class TestFmtStatus:
    def test_known(self):
        assert P._fmt_status("done") == "☑ 已完成"
        assert P._fmt_status("pending") == "☐ 待办"
        assert P._fmt_status("in_progress") == "◔ 进行中"
        assert P._fmt_status("failed") == "✗ 失败"

    def test_unknown(self):
        assert P._fmt_status("bogus") == "☐ bogus"


# ============================================================ _progress


class TestProgress:
    def test_empty(self):
        assert P._progress({"steps": []}) == (0, 0, 0)

    def test_partial(self):
        state = {"steps": [{"status": "done"}, {"status": "pending"}]}
        done, total, pct = P._progress(state)
        assert done == 1 and total == 2 and pct == 50

    def test_all_done(self):
        state = {"steps": [{"status": "done"}] * 3}
        done, total, pct = P._progress(state)
        assert done == 3 and total == 3 and pct == 100


# ============================================================ _load


class TestLoad:
    def test_missing_file(self, tmp_path):
        assert P._load(tmp_path / ".tuan" / "goal.json") is None

    def test_valid_state(self, tmp_path):
        _write_goal(tmp_path, _goal_state())
        path = tmp_path / ".tuan" / "goal.json"
        state = P._load(path)
        assert state is not None
        assert state["goal_id"] == "g1"

    def test_malformed_json(self, tmp_path):
        ppath = tmp_path / ".tuan" / "goal.json"
        ppath.parent.mkdir(parents=True)
        ppath.write_text("not json", encoding="utf-8")
        assert P._load(ppath) is None

    def test_missing_description(self, tmp_path):
        ppath = tmp_path / ".tuan" / "goal.json"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(json.dumps({"steps": []}), encoding="utf-8")
        assert P._load(ppath) is None

    def test_missing_steps(self, tmp_path):
        ppath = tmp_path / ".tuan" / "goal.json"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(json.dumps({"description": "x"}), encoding="utf-8")
        assert P._load(ppath) is None


# ============================================================ cmd_goal status


class TestGoalStatus:
    def test_no_goal_text(self):
        assert P.cmd_goal(_args(goal_cmd="status")) == 0

    def test_no_goal_json(self, capsys):
        assert P.cmd_goal(_args(goal_cmd="status", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["initialized"] is False
        assert data["active"] is False

    def test_with_goal_text(self, tmp_path):
        _write_goal(tmp_path, _goal_state())
        assert P.cmd_goal(_args(goal_cmd="status")) == 0

    def test_with_goal_json(self, tmp_path, capsys):
        _write_goal(tmp_path, _goal_state())
        assert P.cmd_goal(_args(goal_cmd="status", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["initialized"] is True
        assert data["active"] is True
        assert data["progress"]["done"] == 1
        assert data["progress"]["total"] == 3
        assert data["progress"]["percent"] == 33
        assert len(data["remaining"]) == 2

    def test_with_notes(self, tmp_path):
        state = _goal_state(steps=[
            {"id": "1", "description": "Plan", "status": "done", "note": "all good"},
            {"id": "2", "description": "Build", "status": "pending"},
        ])
        _write_goal(tmp_path, state)
        assert P.cmd_goal(_args(goal_cmd="status")) == 0

    def test_completed_goal(self, tmp_path):
        state = _goal_state(status="done", steps=[
            {"id": "1", "description": "A", "status": "done"},
        ])
        _write_goal(tmp_path, state)
        assert P.cmd_goal(_args(goal_cmd="status")) == 0

    def test_custom_workspace(self, tmp_path):
        _write_goal(tmp_path, _goal_state())
        assert P.cmd_goal(_args(goal_cmd="status",
                                workspace=str(tmp_path))) == 0


# ============================================================ cmd_goal steps


class TestGoalSteps:
    def test_no_goal_text(self):
        assert P.cmd_goal(_args(goal_cmd="steps")) == 0

    def test_no_goal_json(self, capsys):
        assert P.cmd_goal(_args(goal_cmd="steps", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["initialized"] is False

    def test_with_remaining(self, tmp_path):
        _write_goal(tmp_path, _goal_state())
        assert P.cmd_goal(_args(goal_cmd="steps")) == 0

    def test_all_done(self, tmp_path):
        state = _goal_state(steps=[{"id": "1", "description": "A", "status": "done"}])
        _write_goal(tmp_path, state)
        assert P.cmd_goal(_args(goal_cmd="steps")) == 0

    def test_steps_json(self, tmp_path, capsys):
        _write_goal(tmp_path, _goal_state())
        assert P.cmd_goal(_args(goal_cmd="steps", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["remaining"]) == 2


# ============================================================ unknown


class TestGoalUnknown:
    def test_unknown(self):
        assert P.cmd_goal(_args(goal_cmd="bogus")) == 1

    def test_default_is_status(self):
        assert P.cmd_goal(_args()) == 0
