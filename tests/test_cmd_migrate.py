"""cmd_migrate tests -- legacy config/session migration CLI (status/detect/run)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tuan_cli.cli import cmd_migrate as P


# ---------------------------------------------------------------- fakes

class FakePlan:
    def __init__(self, has_config=True, has_mcp=True, has_user_history=False,
                 total_sessions=3, detected_plugins=None):
        self.has_config = has_config
        self.has_mcp = has_mcp
        self.has_user_history = has_user_history
        self.total_sessions = total_sessions
        self.detected_plugins = detected_plugins or []


class FakeResult:
    def __init__(self, applied=True, config_written=True, tui_written=True,
                 mcp_written=True, total_sessions=3, errors=None):
        self.applied = applied
        self.config_written = config_written
        self.tui_written = tui_written
        self.mcp_written = mcp_written
        self.total_sessions = total_sessions
        self.errors = errors or []


class FakeMarker:
    def __init__(self, first="2024-01-01", last="2024-06-01", runs=None, version="1.0"):
        self.first_migrated_at = first
        self.last_migrated_at = last
        self.runs = runs or [{}]
        self.migrator_version = version


@pytest.fixture(autouse=True)
def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr("tuan_cli.cli.cmd_migrate.home_dir", lambda: tmp_path)
    monkeypatch.setattr(P, "_default_source", lambda: str(tmp_path / "legacy"))
    monkeypatch.setattr(P, "detect_migration", lambda opts: FakePlan())
    monkeypatch.setattr(P, "run_migration", lambda src, tgt: FakeResult())
    monkeypatch.setattr(P, "read_marker", lambda src: None)
    monkeypatch.setattr(P, "skip_marker",
                        lambda src: tmp_path / "skip_marker_does_not_exist")
    monkeypatch.setattr(P, "source_sessions_dir",
                        lambda src: str(tmp_path / "legacy_sessions"))
    monkeypatch.setattr(P, "migration_report_file",
                        lambda tgt: str(tmp_path / "report.json"))
    monkeypatch.setattr(P, "migration_errors_log_file",
                        lambda tgt: str(tmp_path / "errors.log"))
    return tmp_path


def _args(**kw):
    base = dict(migrate_cmd=None, source=None, target=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- helpers

class TestHelpers:
    def test_default_source_is_string(self):
        s = P._default_source()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_plan_description_empty(self):
        plan = FakePlan(has_config=False, has_mcp=False, total_sessions=0)
        assert P._plan_description(plan) == "无 (空源)"

    def test_plan_description_full(self):
        plan = FakePlan(has_config=True, has_mcp=True, has_user_history=True,
                        total_sessions=5, detected_plugins=["a", "b"])
        desc = P._plan_description(plan)
        assert "config.toml" in desc
        assert "mcp.json" in desc
        assert "user-history" in desc
        assert "5 个会话" in desc
        assert "2 个插件" in desc

    def test_status_line_unmigrated(self, tmp_path):
        lines = P._status_line(str(tmp_path / "nonexistent"))
        assert any("未迁移" in l for l in lines)

    def test_status_line_migrated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(P, "read_marker", lambda src: FakeMarker())
        lines = P._status_line(str(tmp_path))
        assert any("已迁移" in l for l in lines)


# ---------------------------------------------------------------- status

class TestStatus:
    def test_status_text(self, capsys):
        rc = P.cmd_migrate(_args(migrate_cmd="status"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "迁移状态" in out
        assert "源会话目录" in out


# ---------------------------------------------------------------- detect

class TestDetect:
    def test_detect_source_not_exist(self, capsys, tmp_path):
        rc = P.cmd_migrate(_args(migrate_cmd="detect", source=str(tmp_path / "nope")))
        assert rc == 1
        assert "不存在" in capsys.readouterr().out

    def test_detect_ok(self, capsys, tmp_path):
        src = tmp_path / "legacy"
        src.mkdir()
        rc = P.cmd_migrate(_args(migrate_cmd="detect", source=str(src)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "检测结果" in out
        assert "config.toml" in out


# ---------------------------------------------------------------- run

class TestRun:
    def test_run_source_not_exist_noop(self, capsys, tmp_path):
        rc = P.cmd_migrate(_args(migrate_cmd="run",
                                  source=str(tmp_path / "nope")))
        assert rc == 0
        assert "无需迁移" in capsys.readouterr().out

    def test_run_success(self, capsys, tmp_path):
        src = tmp_path / "legacy"
        src.mkdir()
        rc = P.cmd_migrate(_args(migrate_cmd="run", source=str(src)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "迁移完成" in out

    def test_run_noop(self, capsys, tmp_path, monkeypatch):
        src = tmp_path / "legacy"
        src.mkdir()
        monkeypatch.setattr(P, "run_migration", lambda s, t: FakeResult(applied=False))
        rc = P.cmd_migrate(_args(migrate_cmd="run", source=str(src)))
        assert rc == 0
        assert "no-op" in capsys.readouterr().out

    def test_run_with_errors(self, capsys, tmp_path, monkeypatch):
        src = tmp_path / "legacy"
        src.mkdir()
        monkeypatch.setattr(P, "run_migration",
                            lambda s, t: FakeResult(errors=["some error"]))
        rc = P.cmd_migrate(_args(migrate_cmd="run", source=str(src)))
        assert rc == 1
        assert "some error" in capsys.readouterr().out

    def test_run_exception(self, capsys, tmp_path, monkeypatch):
        src = tmp_path / "legacy"
        src.mkdir()
        def _boom(s, t):
            raise RuntimeError("boom")
        monkeypatch.setattr(P, "run_migration", _boom)
        rc = P.cmd_migrate(_args(migrate_cmd="run", source=str(src)))
        assert rc == 1
        assert "迁移失败" in capsys.readouterr().out


# ---------------------------------------------------------------- usage

class TestUsage:
    def test_no_sub_shows_usage(self, capsys):
        rc = P.cmd_migrate(_args())
        assert rc == 2
        out = capsys.readouterr().out
        assert "用法" in out
