"""cmd_web_audit tests -- Web workspace persistent state read-only audit."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tuan_cli.cli import cmd_web_audit as P


@pytest.fixture(autouse=True)
def _workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("TUAN_WORKSPACE", str(tmp_path))
    return tmp_path


def _args(**kw):
    base = dict(web_audit_cmd=None, json=False, workspace=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _write_sessions(ws: Path, sessions: dict):
    d = ws / ".tuan"
    d.mkdir(parents=True, exist_ok=True)
    (d / "web_sessions.json").write_text(
        json.dumps(sessions, ensure_ascii=False), encoding="utf-8")


def _write_settings(ws: Path, settings: dict):
    d = ws / ".tuan"
    d.mkdir(parents=True, exist_ok=True)
    (d / "web_settings.json").write_text(
        json.dumps(settings, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- helpers

class TestHelpers:
    def test_resolve_explicit(self, tmp_path):
        p = P._resolve_workspace(str(tmp_path))
        assert p == tmp_path.resolve()

    def test_resolve_env(self, tmp_path):
        p = P._resolve_workspace(None)
        assert p == tmp_path.resolve()

    def test_read_json_missing(self, tmp_path):
        assert P._read_json(tmp_path / "nope.json") is None

    def test_read_json_bad(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        assert P._read_json(p) is None

    def test_read_json_not_dict(self, tmp_path):
        p = tmp_path / "arr.json"
        p.write_text("[1,2]", encoding="utf-8")
        assert P._read_json(p) is None

    def test_msg_count_list(self):
        assert P._msg_count({"messages": [1, 2, 3]}) == 3

    def test_msg_count_dict(self):
        assert P._msg_count({"messages": {"a": 1, "b": 2}}) == 2

    def test_msg_count_missing(self):
        assert P._msg_count({}) == 0

    def test_session_row(self):
        row = P._session_row("s1", {"title": "My Chat", "created": "2024-01-01",
                                     "messages": [1, 2]})
        assert row["id"] == "s1"
        assert row["title"] == "My Chat"
        assert row["messages"] == 2

    def test_session_row_long_title(self):
        long_title = "x" * 100
        row = P._session_row("s1", {"title": long_title})
        assert len(row["title"]) == 60


# ---------------------------------------------------------------- all (default)

class TestAll:
    def test_all_empty(self, capsys):
        rc = P.cmd_web_audit(_args())
        assert rc == 0
        assert "尚未落盘" in capsys.readouterr().out

    def test_all_with_sessions(self, capsys, _workspace):
        _write_sessions(_workspace, {
            "s1": {"title": "Session 1", "created": "2024-01-02",
                   "messages": [1, 2, 3]},
        })
        rc = P.cmd_web_audit(_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "Session 1" in out
        assert "1 个会话" in out

    def test_all_json(self, capsys, _workspace):
        _write_sessions(_workspace, {"s1": {"title": "S1", "messages": [1]}})
        rc = P.cmd_web_audit(_args(json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["session_count"] == 1
        assert d["total_messages"] == 1


# ---------------------------------------------------------------- sessions

class TestSessions:
    def test_sessions_json(self, capsys, _workspace):
        _write_sessions(_workspace, {
            "s1": {"title": "A", "messages": [1, 2]},
            "s2": {"title": "B", "messages": [1]},
        })
        rc = P.cmd_web_audit(_args(web_audit_cmd="sessions", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["session_count"] == 2
        assert d["settings"] is None


# ---------------------------------------------------------------- settings

class TestSettings:
    def test_settings_json_empty(self, capsys, _workspace):
        rc = P.cmd_web_audit(_args(web_audit_cmd="settings", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["initialized"] is False
        assert d["settings"] == {}

    def test_settings_text(self, capsys, _workspace):
        _write_settings(_workspace, {"theme": "dark", "font_size": 14})
        rc = P.cmd_web_audit(_args(web_audit_cmd="settings"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "theme" in out
        assert "dark" in out
