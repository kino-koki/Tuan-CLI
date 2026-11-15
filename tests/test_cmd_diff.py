"""``tuan diff`` CLI 的单元测试 (cmd_diff.py)。

操作账本驱动的字节级 diff。覆盖:
1. _resolve_workspace: 默认 cwd 回落
2. _load_ledger_events: 缺目录 / 缺文件 / 有日志 / 坏 JSON 行跳过
3. _render_plain_diff: 生成统一 diff 文本
4. _summarize: 空事件 / 有 old/new 快照的事件
5. _scope_stats: 空 / targets 列表 / 单 path / 按 type 分组
6. cmd_diff: 空账本 / scope 模式 / stat 模式 / 有编辑凭证 / JSON / last N / file 过滤

通过 tmp_path 做真实文件系统测试 (写入 .tuan/ledger 事件)。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_diff as P


def _args(**kw) -> SimpleNamespace:
    base = dict(json=False, last=0, file="", stat=False, scope=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _write_events(ws: Path, events: list) -> None:
    ledger = ws / ".tuan" / "ledger"
    ledger.mkdir(parents=True)
    lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
    (ledger / "events.jsonl").write_text(lines + "\n", encoding="utf-8")


def _edit_event(path="src/a.py", old="old1\nold2\n", new="new1\nnew2\nnew3\n"):
    return {
        "type": "edit", "tool": "Write", "ts": "2026-01-01T00:00:00",
        "path": path, "old": old, "new": new,
    }


def _patch_ws(monkeypatch, ws: Path) -> None:
    monkeypatch.setattr(P, "_resolve_workspace", lambda: ws)


# ============================================================ _resolve_workspace


class TestResolveWorkspace:
    def test_returns_path(self) -> None:
        rc = P._resolve_workspace()
        assert isinstance(rc, Path)

    def test_default_workspace_exists(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.paths as P_paths
        monkeypatch.setattr(P_paths, "default_workspace", lambda: str(tmp_path))
        (tmp_path / ".tuan").mkdir()
        rc = P._resolve_workspace()
        assert rc == tmp_path


# ============================================================ _load_ledger_events


class TestLoadLedgerEvents:
    def test_no_dir(self, tmp_path) -> None:
        assert P._load_ledger_events(tmp_path) == []

    def test_no_file(self, tmp_path) -> None:
        (tmp_path / ".tuan" / "ledger").mkdir(parents=True)
        assert P._load_ledger_events(tmp_path) == []

    def test_with_events(self, tmp_path) -> None:
        _write_events(tmp_path, [{"type": "edit"}, {"type": "write"}])
        ev = P._load_ledger_events(tmp_path)
        assert len(ev) == 2

    def test_bad_json_skipped(self, tmp_path) -> None:
        ledger = tmp_path / ".tuan" / "ledger"
        ledger.mkdir(parents=True)
        (ledger / "events.jsonl").write_text(
            '{"type":"edit"}\nBAD LINE\n{"type":"write"}\n', encoding="utf-8")
        ev = P._load_ledger_events(tmp_path)
        assert len(ev) == 2


# ============================================================ _render_plain_diff


class TestRenderPlainDiff:
    def test_generates_diff(self) -> None:
        out = P._render_plain_diff("a\nb\n", "a\nc\n", "test.py")
        assert "--- a/test.py" in out
        assert "+++ b/test.py" in out
        assert "-b" in out
        assert "+c" in out


# ============================================================ _summarize


class TestSummarize:
    def test_empty(self) -> None:
        s = P._summarize([])
        assert s["events"] == 0
        assert s["added"] == 0
        assert s["files"] == 0

    def test_with_old_new(self) -> None:
        ev = _edit_event()
        s = P._summarize([ev])
        assert s["events"] == 1
        assert s["by_type"]["edit"] == 1
        assert "src/a.py" in s["by_file"]
        assert s["by_file"]["src/a.py"]["edits"] == 1


# ============================================================ _scope_stats


class TestScopeStats:
    def test_empty(self) -> None:
        s = P._scope_stats([])
        assert s["records"] == 0
        assert s["files_touched"] == 0

    def test_targets_list(self) -> None:
        s = P._scope_stats([
            {"type": "write", "targets": ["a.py", "b.py"]},
        ])
        assert s["files_touched"] == 2
        assert "a.py" in s["files"]

    def test_single_path(self) -> None:
        s = P._scope_stats([{"type": "edit", "path": "src/x.py"}])
        assert "src/x.py" in s["files"]

    def test_file_field(self) -> None:
        s = P._scope_stats([{"type": "write", "file": "y.py"}])
        assert "y.py" in s["files"]

    def test_by_type_grouping(self) -> None:
        s = P._scope_stats([
            {"type": "edit", "path": "a.py"},
            {"type": "edit", "path": "b.py"},
            {"type": "write", "path": "c.py"},
        ])
        assert s["by_type"]["edit"] == 2
        assert s["by_type"]["write"] == 1

    def test_path_stripping(self) -> None:
        s = P._scope_stats([{"type": "write", "path": "./a.py"}])
        assert "a.py" in s["files"]


# ============================================================ cmd_diff 入口


class TestCmdDiff:
    def test_empty_ledger(self, monkeypatch, tmp_path) -> None:
        _patch_ws(monkeypatch, tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_diff(_args())
        assert rc == 0
        text = "\n".join(printed)
        assert "无编辑记录" in text

    def test_empty_scope(self, monkeypatch, tmp_path) -> None:
        _patch_ws(monkeypatch, tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_diff(_args(scope=True))
        assert rc == 0
        text = "\n".join(printed)
        assert "无记录" in text

    def test_scope_mode(self, monkeypatch, tmp_path) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [
            {"type": "write", "targets": ["a.py", "b.py"]},
            {"type": "edit", "path": "c.py"},
        ])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_diff(_args(scope=True))
        assert rc == 0
        text = "\n".join(printed)
        assert "影响半径" in text
        assert "a.py" in text

    def test_scope_json(self, monkeypatch, tmp_path, capsys) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [
            {"type": "write", "targets": ["a.py"]},
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_diff(_args(scope=True, json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["records"] == 1
        assert data["files_touched"] == 1

    def test_stat_mode(self, monkeypatch, tmp_path) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [_edit_event(), _edit_event()])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_diff(_args(stat=True))
        assert rc == 0
        text = "\n".join(printed)
        assert "编辑摘要" in text

    def test_json_mode(self, monkeypatch, tmp_path, capsys) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [_edit_event()])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_diff(_args(json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["ledger_events"] == 1
        assert data["edits"][0]["type"] == "edit"

    def test_last_n_filter(self, monkeypatch, tmp_path, capsys) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [_edit_event() for _ in range(5)])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_diff(_args(json=True, last=3))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data["edits"]) == 3

    def test_file_filter(self, monkeypatch, tmp_path, capsys) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [
            _edit_event(path="src/a.py"),
            _edit_event(path="src/b.py"),
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_diff(_args(json=True, file="a.py"))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data["edits"]) == 1
        assert data["edits"][0]["path"] == "src/a.py"

    def test_full_diff_render(self, monkeypatch, tmp_path) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [_edit_event()])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_diff(_args())
        assert rc == 0
        text = "\n".join(printed)
        assert "最近编辑" in text or "src/a.py" in text

    def test_no_old_new_shows_list(self, monkeypatch, tmp_path) -> None:
        _patch_ws(monkeypatch, tmp_path)
        _write_events(tmp_path, [
            {"type": "edit", "tool": "Bash", "ts": "2026-01-01T00:00:00",
             "path": "run.log"},
        ])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_diff(_args())
        assert rc == 0
        text = "\n".join(printed)
        assert "无 old/new" in text or "编辑记录" in text
