"""``tuan aggregate`` CLI 的单元测试 (cmd_aggregate.py)。

多 Agent 结果聚合可观测性。覆盖:
1. _load_results: 文件路径 / @前缀 / 内联 JSON / 非 list / 非 dict 项 / 解析失败
2. _demo_results: 含去重+冲突项
3. _cmd_aggregate_run: 文件错误 / 空结果 / 正常 / JSON
4. _cmd_aggregate_demo: 正常 / JSON
5. cmd_aggregate: 默认 demo / run 分发

通过 tmp_path 写真实 JSON 文件 + monkeypatch console。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_aggregate as P


def _args(**kw) -> SimpleNamespace:
    base = dict(aggregate_cmd=None, json=False, results=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _result(task_id="T1", agent_id="a", role="implementer",
            content="实现功能", quality=0.8, elapsed=10.0, tools=3):
    return {
        "task_id": task_id, "agent_id": agent_id, "role": role,
        "content": content, "quality_score": quality,
        "elapsed": elapsed, "tool_calls": tools,
    }


def _write_results(tmp_path: Path, items: list) -> Path:
    p = tmp_path / "results.json"
    p.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return p


# ============================================================ _load_results


class TestLoadResults:
    def test_from_file(self, tmp_path) -> None:
        p = _write_results(tmp_path, [_result()])
        out = P._load_results(str(p))
        assert len(out) == 1
        assert out[0]["task_id"] == "T1"

    def test_at_prefix(self, tmp_path) -> None:
        p = _write_results(tmp_path, [_result(), _result(agent_id="b")])
        # @ 前缀剥离
        out = P._load_results(f"@{p}")
        assert len(out) == 2

    def test_inline_json(self) -> None:
        out = P._load_results(json.dumps([_result()], ensure_ascii=False))
        assert len(out) == 1

    def test_not_a_list(self, tmp_path) -> None:
        p = tmp_path / "x.json"
        p.write_text('{"not": "list"}', encoding="utf-8")
        with pytest.raises(ValueError, match="JSON 数组"):
            P._load_results(str(p))

    def test_non_dict_item(self, tmp_path) -> None:
        p = tmp_path / "x.json"
        p.write_text('[1, 2, 3]', encoding="utf-8")
        with pytest.raises(ValueError, match="对象"):
            P._load_results(str(p))

    def test_unparseable(self) -> None:
        with pytest.raises(ValueError, match="无法解析"):
            P._load_results("not-valid-json-and-not-a-file")

    def test_empty_list_ok(self, tmp_path) -> None:
        p = _write_results(tmp_path, [])
        out = P._load_results(str(p))
        assert out == []


# ============================================================ _demo_results


class TestDemoResults:
    def test_structure(self) -> None:
        items = P._demo_results()
        assert len(items) == 3
        assert items[0]["task_id"] == "T1"
        assert items[2]["task_id"] == "T2"
        assert items[2]["role"] == "security_auditor"


# ============================================================ _cmd_aggregate_run


class TestCmdAggregateRun:
    def test_file_error(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_aggregate_run(_args(results="not-valid-or-existing"), json_mode=False)
        assert rc == 1

    def test_empty_results(self, monkeypatch, tmp_path) -> None:
        p = _write_results(tmp_path, [])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_aggregate_run(_args(results=str(p)), json_mode=False)
        assert rc == 0

    def test_normal_render(self, monkeypatch, tmp_path) -> None:
        p = _write_results(tmp_path, [
            _result(content="实现登录 API, 用 JWT", agent_id="a"),
            _result(content="实现登录接口, JWT 认证", agent_id="b"),
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_aggregate_run(_args(results=str(p)), json_mode=False)
        assert rc == 0

    def test_json_output(self, monkeypatch, tmp_path, capsys) -> None:
        p = _write_results(tmp_path, [
            _result(agent_id="a", content="实现登录"),
            _result(agent_id="b", content="实现登录"),
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_aggregate_run(_args(results=str(p)), json_mode=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert "input_count" in data
        assert "result" in data
        assert "decisions" in data
        assert "merged_content" in data
        assert data["input_count"] == 2

    def test_with_conflicts(self, monkeypatch, tmp_path) -> None:
        # 构造两个矛盾结果 (同任务不同结论)
        p = _write_results(tmp_path, [
            _result(agent_id="a", content="使用 SQLite 数据库"),
            _result(agent_id="b", content="使用 PostgreSQL 数据库"),
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_aggregate_run(_args(results=str(p)), json_mode=False)
        assert rc == 0


# ============================================================ _cmd_aggregate_demo


class TestCmdAggregateDemo:
    def test_normal_render(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_aggregate_demo(_args(), json_mode=False)
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_aggregate_demo(_args(), json_mode=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["input_count"] == 3  # demo 有 3 个结果
        assert "decisions" in data


# ============================================================ 分发入口


class TestDispatcher:
    def test_default_demo(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_aggregate(_args(aggregate_cmd=None))
        assert rc == 0

    def test_demo_subcommand(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_aggregate(_args(aggregate_cmd="demo"))
        assert rc == 0

    def test_run_subcommand(self, monkeypatch, tmp_path) -> None:
        p = _write_results(tmp_path, [_result()])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_aggregate(_args(aggregate_cmd="run", results=str(p)))
        assert rc == 0

    def test_run_json(self, monkeypatch, tmp_path, capsys) -> None:
        p = _write_results(tmp_path, [_result()])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_aggregate(_args(aggregate_cmd="run", results=str(p), json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["input_count"] == 1
