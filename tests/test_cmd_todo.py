"""cmd_todo 单元测试 —— 持久化任务清单只读查看 CLI。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_todo as P


def _args(**kw) -> SimpleNamespace:
    base = dict(todo_cmd=None, json=False, workspace=None, index=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _patch_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("TUAN_WORKSPACE", str(tmp_path))
    return tmp_path


def _write_todos(tmp_path, todos):
    ppath = tmp_path / ".tuan" / "todo.json"
    ppath.parent.mkdir(parents=True, exist_ok=True)
    ppath.write_text(json.dumps(todos), encoding="utf-8")


# ============================================================ _by_status


class TestByStatus:
    def test_empty(self):
        assert P._by_status([]) == {}

    def test_counts(self):
        todos = [
            {"status": "pending"},
            {"status": "pending"},
            {"status": "completed"},
            {"status": "in_progress"},
        ]
        r = P._by_status(todos)
        assert r["pending"] == 2
        assert r["completed"] == 1
        assert r["in_progress"] == 1


# ============================================================ _progress


class TestProgress:
    def test_empty(self):
        assert P._progress([]) == (0, 0, 0)

    def test_all_done(self):
        todos = [{"status": "completed"}, {"status": "completed"}]
        done, total, pct = P._progress(todos)
        assert done == 2 and total == 2 and pct == 100

    def test_partial(self):
        todos = [{"status": "completed"}, {"status": "pending"}]
        done, total, pct = P._progress(todos)
        assert done == 1 and total == 2 and pct == 50

    def test_none_done(self):
        todos = [{"status": "pending"}, {"status": "in_progress"}]
        done, total, pct = P._progress(todos)
        assert done == 0 and total == 2 and pct == 0


# ============================================================ cmd_todo list


class TestTodoList:
    def test_empty_text(self):
        assert P.cmd_todo(_args(todo_cmd="list")) == 0

    def test_empty_json(self, capsys):
        assert P.cmd_todo(_args(todo_cmd="list", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["initialized"] is False
        assert data["total"] == 0

    def test_file_exists_but_empty(self, tmp_path):
        _write_todos(tmp_path, [])
        assert P.cmd_todo(_args(todo_cmd="list")) == 0

    def test_with_todos_text(self, tmp_path):
        _write_todos(tmp_path, [
            {"id": "1", "content": "step A", "status": "completed"},
            {"id": "2", "content": "step B", "status": "in_progress"},
            {"id": "3", "content": "step C", "status": "pending"},
        ])
        assert P.cmd_todo(_args(todo_cmd="list")) == 0

    def test_with_todos_json(self, tmp_path, capsys):
        todos = [{"id": "1", "content": "A", "status": "completed"}]
        _write_todos(tmp_path, todos)
        assert P.cmd_todo(_args(todo_cmd="list", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 1
        assert data["initialized"] is True
        assert data["progress"][0] == 1
        assert data["progress"][2] == 100


# ============================================================ cmd_todo show


class TestTodoShow:
    def test_missing_file(self):
        assert P.cmd_todo(_args(todo_cmd="show", index="1")) == 0

    def test_no_index(self, tmp_path):
        _write_todos(tmp_path, [{"id": "1", "content": "A", "status": "pending"}])
        assert P.cmd_todo(_args(todo_cmd="show")) == 1

    def test_bad_index(self, tmp_path):
        _write_todos(tmp_path, [{"id": "1", "content": "A", "status": "pending"}])
        assert P.cmd_todo(_args(todo_cmd="show", index="abc")) == 1

    def test_index_out_of_range(self, tmp_path):
        _write_todos(tmp_path, [{"id": "1", "content": "A", "status": "pending"}])
        assert P.cmd_todo(_args(todo_cmd="show", index="5")) == 1

    def test_index_zero(self, tmp_path):
        _write_todos(tmp_path, [{"id": "1", "content": "A", "status": "pending"}])
        assert P.cmd_todo(_args(todo_cmd="show", index="0")) == 1

    def test_show_text(self, tmp_path):
        _write_todos(tmp_path, [
            {"id": "1", "content": "step", "status": "in_progress", "priority": "high"},
        ])
        assert P.cmd_todo(_args(todo_cmd="show", index="1")) == 0

    def test_show_json(self, tmp_path, capsys):
        _write_todos(tmp_path, [
            {"id": "1", "content": "step", "status": "completed"},
        ])
        assert P.cmd_todo(_args(todo_cmd="show", index="1", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["index"] == 1
        assert data["item"]["content"] == "step"


# ============================================================ unknown


class TestTodoUnknown:
    def test_unknown(self):
        assert P.cmd_todo(_args(todo_cmd="bogus")) == 1

    def test_default_is_list(self):
        assert P.cmd_todo(_args()) == 0
