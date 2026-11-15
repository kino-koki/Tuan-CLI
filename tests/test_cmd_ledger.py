"""``tuan ledger`` CLI 的单元测试 (cmd_ledger.py)。

操作账本可观测性 (纯只读)。覆盖:
1. _resolve_ws: 显式 / cwd
2. _fmt_time: 正常 / 异常
3. _rec_dict: 完整字段
4. cmd_ledger list: 空账本 / 有凭证 / JSON
5. cmd_ledger stats: 正常 / JSON
6. cmd_ledger mark: 正常 / JSON

通过 monkeypatch 打桩 _get_ledger 返回 fake MutationLedger。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_ledger as P


def _args(**kw) -> SimpleNamespace:
    base = dict(ledger_cmd=None, workspace=None, json=False)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeLedger:
    def __init__(self, history=None, enabled=True, max_records=500,
                 journal_name="ledger.jsonl", mark=3):
        self._history = history or []
        self.enabled = enabled
        self.max_records = max_records
        self.journal_path = Path(f"/tmp/ws/{journal_name}")
        self._mark = mark

    def history(self):
        return self._history

    def stats(self):
        files = set()
        for r in self._history:
            for t in r.get("targets", []):
                files.add(t)
        return {
            "records": len(self._history),
            "files_touched": len(files),
            "files": sorted(files),
        }

    def mark(self):
        return self._mark


def _patch_ledger(monkeypatch, **kw) -> None:
    monkeypatch.setattr(P, "_get_ledger", lambda raw: _FakeLedger(**kw))


# ============================================================ _resolve_ws


class TestResolveWs:
    def test_explicit(self) -> None:
        rc = P._resolve_ws("/tmp/ws/x")
        assert rc == Path("/tmp/ws/x").resolve()

    def test_cwd(self) -> None:
        rc = P._resolve_ws(None)
        assert rc == Path.cwd().resolve()


# ============================================================ _fmt_time


class TestFmtTime:
    def test_valid(self) -> None:
        s = P._fmt_time(1000.0)
        assert s != "-"

    def test_invalid(self) -> None:
        assert P._fmt_time("not-a-number") == "-"


# ============================================================ _rec_dict


class TestRecDict:
    def test_complete(self) -> None:
        r = {"id": "a1", "ts": 1700000000.0, "tool": "Write",
             "kind": "mutation", "summary": "写文件", "targets": ["src/x.py"]}
        d = P._rec_dict(r)
        assert d["id"] == "a1"
        assert d["tool"] == "Write"
        assert d["kind"] == "mutation"
        assert d["targets"] == ["src/x.py"]
        assert d["time"] != "-"

    def test_defaults(self) -> None:
        d = P._rec_dict({})
        assert d["id"] == ""
        assert d["kind"] == "mutation"
        assert d["targets"] == []


# ============================================================ list 子命令


class TestList:
    def test_empty(self, monkeypatch) -> None:
        _patch_ledger(monkeypatch, history=[])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_ledger(_args())
        assert rc == 0
        text = "\n".join(printed)
        assert "无变更凭证" in text

    def test_with_records(self, monkeypatch) -> None:
        _patch_ledger(monkeypatch, history=[
            {"id": "a1", "ts": 1700000000.0, "tool": "Write",
             "kind": "mutation", "summary": "写 src/x.py", "targets": ["src/x.py"]},
            {"id": "a2", "ts": 1700000100.0, "tool": "Bash",
             "kind": "mutation", "summary": "运行测试", "targets": []},
        ])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_ledger(_args())
        assert rc == 0
        text = "\n".join(printed)
        assert "2 条凭证" in text
        assert "a1" in text
        assert "Write" in text

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_ledger(monkeypatch, history=[
            {"id": "a1", "ts": 1700000000.0, "tool": "Write",
             "kind": "mutation", "summary": "写文件", "targets": ["src/x.py"]},
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ledger(_args(json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["count"] == 1
        assert data["records"][0]["id"] == "a1"
        assert "workspace" in data


# ============================================================ stats 子命令


class TestStats:
    def test_normal(self, monkeypatch) -> None:
        _patch_ledger(monkeypatch, history=[
            {"id": "a1", "targets": ["a.py"]},
            {"id": "a2", "targets": ["b.py"]},
        ])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_ledger(_args(ledger_cmd="stats"))
        assert rc == 0
        text = "\n".join(printed)
        assert "变更凭证" in text
        assert "触及文件" in text
        assert "a.py" in text

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_ledger(monkeypatch, history=[
            {"id": "a1", "targets": ["a.py"]},
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ledger(_args(ledger_cmd="stats", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["records"] == 1
        assert data["files_touched"] == 1
        assert "workspace" in data


# ============================================================ mark 子命令


class TestMark:
    def test_normal(self, monkeypatch) -> None:
        _patch_ledger(monkeypatch, mark=7)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_ledger(_args(ledger_cmd="mark"))
        assert rc == 0
        text = "\n".join(printed)
        assert "检查点标记" in text
        assert "7" in text

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_ledger(monkeypatch, mark=5)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ledger(_args(ledger_cmd="mark", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["mark"] == 5
        assert "workspace" in data
