"""cmd_plan 单元测试 —— 实施计划存档只读体检 CLI。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_plan as P


def _args(**kw) -> SimpleNamespace:
    base = dict(plan_cmd=None, json=False, workspace=None, file=None, text="")
    base.update(kw)
    return SimpleNamespace(**base)


PLAN_MD = """# Implementation Plan

- 存档时间 (UTC): 2025-01-15T12:00:00Z
- 来源: Plan Mode (session abc123)

## Steps
1. Do something
2. Do another thing
"""


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _patch_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("TUAN_WORKSPACE", str(tmp_path))
    return tmp_path


# ============================================================ _resolve_workspace


class TestResolveWorkspace:
    def test_explicit(self):
        r = P._resolve_workspace("/tmp/ws")
        assert r == Path("/tmp/ws").resolve()

    def test_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TUAN_WORKSPACE", str(tmp_path))
        assert P._resolve_workspace(None) == tmp_path.resolve()

    def test_cwd_fallback(self, monkeypatch):
        monkeypatch.delenv("TUAN_WORKSPACE", raising=False)
        r = P._resolve_workspace(None)
        assert r == Path.cwd().resolve()


# ============================================================ _parse_header


class TestParseHeader:
    def test_with_header(self):
        meta = P._parse_header(PLAN_MD)
        assert meta["saved_at"] == "2025-01-15T12:00:00Z"
        assert "session" in meta["source"]

    def test_empty(self):
        meta = P._parse_header("# nothing")
        assert meta["saved_at"] is None
        assert meta["source"] is None


# ============================================================ _diff_stats


class TestDiffStats:
    def test_identical(self):
        s = P._diff_stats("a\nb\nc", "a\nb\nc")
        assert s["added"] == 0 and s["removed"] == 0

    def test_added(self):
        s = P._diff_stats("a", "a\nb")
        assert s["added"] == 1

    def test_removed(self):
        s = P._diff_stats("a\nb", "a")
        assert s["removed"] == 1

    def test_both(self):
        s = P._diff_stats("a\nb\nc", "a\nx\nd")
        assert s["added"] > 0 and s["removed"] > 0


# ============================================================ cmd_plan show


class TestPlanShow:
    def test_not_initialized_text(self):
        assert P.cmd_plan(_args(plan_cmd="show")) == 0

    def test_not_initialized_json(self, capsys):
        assert P.cmd_plan(_args(plan_cmd="show", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["initialized"] is False

    def test_initialized_text(self, tmp_path):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(PLAN_MD, encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="show")) == 0

    def test_initialized_json(self, tmp_path, capsys):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(PLAN_MD, encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="show", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["initialized"] is True
        assert data["saved_at"] == "2025-01-15T12:00:00Z"
        assert data["lines"] > 0

    def test_read_error(self, tmp_path):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text("x", encoding="utf-8")
        # monkeypatch read_text to raise
        import unittest.mock as mock
        with mock.patch.object(Path, "read_text", side_effect=OSError("perm")):
            assert P.cmd_plan(_args(plan_cmd="show")) == 1


# ============================================================ cmd_plan diff


class TestPlanDiff:
    def test_no_plan(self):
        assert P.cmd_plan(_args(plan_cmd="diff")) == 1

    def test_no_other(self, tmp_path):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(PLAN_MD, encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="diff")) == 1

    def test_diff_text(self, tmp_path):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(PLAN_MD, encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="diff", text="different")) == 0

    def test_diff_identical(self, tmp_path):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text("same", encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="diff", text="same")) == 0

    def test_diff_json(self, tmp_path, capsys):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text("a\nb", encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="diff", text="a\nb\nc", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["added"] == 1

    def test_diff_file(self, tmp_path):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(PLAN_MD, encoding="utf-8")
        other = tmp_path / "other.txt"
        other.write_text("other content", encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="diff", file=str(other))) == 0

    def test_diff_file_missing(self, tmp_path):
        ppath = tmp_path / ".tuan" / "plan.md"
        ppath.parent.mkdir(parents=True)
        ppath.write_text(PLAN_MD, encoding="utf-8")
        assert P.cmd_plan(_args(plan_cmd="diff", file="/nonexistent")) == 1


# ============================================================ unknown


class TestPlanUnknown:
    def test_unknown(self):
        assert P.cmd_plan(_args(plan_cmd="bogus")) == 1

    def test_default_is_show(self):
        assert P.cmd_plan(_args()) == 0
