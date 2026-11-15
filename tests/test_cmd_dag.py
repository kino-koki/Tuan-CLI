"""cmd_dag 单元测试 —— 任务依赖图可观测性 CLI。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_dag as P


def _args(**kw) -> SimpleNamespace:
    base = dict(dag_cmd=None, plan="", json=False, **{"break": False})
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)


# ============================================================ _demo_tasks


class TestDemoTasks:
    def test_structure(self):
        tasks = P._demo_tasks()
        assert len(tasks) == 6
        assert all("id" in t and "prompt" in t for t in tasks)
        assert tasks[0]["id"] == "T1"
        assert "depends_on" not in tasks[0] or tasks[0].get("depends_on", "") == ""


# ============================================================ _load_plan


class TestLoadPlan:
    def test_from_file(self, tmp_path):
        plan = [{"id": "A", "title": "t", "prompt": "p", "depends_on": ""}]
        f = tmp_path / "plan.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        result = P._load_plan(str(f))
        assert len(result) == 1
        assert result[0]["id"] == "A"

    def test_at_prefix(self, tmp_path):
        plan = [{"id": "B", "title": "t", "prompt": "p"}]
        f = tmp_path / "p.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        result = P._load_plan("@" + str(f))
        assert result[0]["id"] == "B"

    def test_inline_json(self):
        raw = json.dumps([{"id": "X", "title": "t", "prompt": "p"}])
        result = P._load_plan(raw)
        assert result[0]["id"] == "X"

    def test_not_found(self):
        with pytest.raises(ValueError, match="无法解析"):
            P._load_plan("/nonexistent/path/plan.json")

    def test_not_array(self, tmp_path):
        f = tmp_path / "p.json"
        f.write_text(json.dumps({"not": "array"}), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON 数组"):
            P._load_plan(str(f))

    def test_item_not_dict(self, tmp_path):
        f = tmp_path / "p.json"
        f.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError, match="对象"):
            P._load_plan(str(f))


# ============================================================ cmd_dag dispatch


class TestCmdDagDemo:
    def test_demo_text(self):
        assert P.cmd_dag(_args(dag_cmd="demo")) == 0

    def test_demo_json(self, capsys):
        assert P.cmd_dag(_args(dag_cmd="demo", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert "tasks" in data
        assert len(data["tasks"]) == 6
        assert "critical_path" in data
        assert "waves" in data


class TestCmdDagPlan:
    def test_plan_from_file(self, tmp_path):
        plan = [
            {"id": "A", "title": "t1", "prompt": "p"},
            {"id": "B", "title": "t2", "prompt": "p", "depends_on": "A"},
        ]
        f = tmp_path / "plan.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        assert P.cmd_dag(_args(dag_cmd="plan", plan=str(f))) == 0

    def test_plan_json(self, tmp_path, capsys):
        plan = [{"id": "A", "title": "t", "prompt": "p"}]
        f = tmp_path / "plan.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        assert P.cmd_dag(_args(dag_cmd="plan", plan=str(f), json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["tasks"]) == 1

    def test_plan_error(self):
        assert P.cmd_dag(_args(dag_cmd="plan", plan="/no/such/file")) == 1

    def test_plan_empty(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text(json.dumps([]), encoding="utf-8")
        assert P.cmd_dag(_args(dag_cmd="plan", plan=str(f))) == 0


class TestCmdDagCheck:
    def test_check_ok(self, tmp_path):
        plan = [{"id": "A", "title": "t", "prompt": "p"},
                {"id": "B", "title": "t", "prompt": "p", "depends_on": "A"}]
        f = tmp_path / "ok.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        assert P.cmd_dag(_args(dag_cmd="check", plan=str(f))) == 0

    def test_check_cycle(self, tmp_path):
        plan = [{"id": "A", "title": "t", "prompt": "p", "depends_on": "B"},
                {"id": "B", "title": "t", "prompt": "p", "depends_on": "A"}]
        f = tmp_path / "cycle.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        assert P.cmd_dag(_args(dag_cmd="check", plan=str(f))) == 1

    def test_check_json_ok(self, tmp_path, capsys):
        plan = [{"id": "A", "title": "t", "prompt": "p"}]
        f = tmp_path / "p.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        assert P.cmd_dag(_args(dag_cmd="check", plan=str(f), json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is True

    def test_check_json_cycle(self, tmp_path, capsys):
        plan = [{"id": "A", "title": "t", "prompt": "p", "depends_on": "B"},
                {"id": "B", "title": "t", "prompt": "p", "depends_on": "A"}]
        f = tmp_path / "c.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        assert P.cmd_dag(_args(dag_cmd="check", plan=str(f), json=True)) == 1
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert len(data["cycles"]) > 0

    def test_check_error(self):
        assert P.cmd_dag(_args(dag_cmd="check", plan="/bad/path")) == 1


class TestCmdDagDefault:
    def test_default_is_demo(self):
        assert P.cmd_dag(_args()) == 0
