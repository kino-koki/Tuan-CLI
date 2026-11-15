"""cmd_sessions 单元测试 —— 会话列表/删除 CLI (复数)。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_sessions as P


def _args(**kw) -> SimpleNamespace:
    base = dict(sessions_cmd=None, target=None, all=False, yes=False)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)


# ============================================================ list


class TestSessionsList:
    def test_empty(self, monkeypatch):
        monkeypatch.setattr(P, "list_recent", lambda n: [])
        assert P.cmd_sessions(_args(sessions_cmd="list")) == 0

    def test_with_sessions(self, monkeypatch, tmp_path):
        files = [tmp_path / "sess1.jsonl", tmp_path / "sess2.jsonl"]
        for f in files:
            f.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(P, "list_recent", lambda n: files)
        monkeypatch.setattr(P, "session_title", lambda p: "test title")
        monkeypatch.setattr(P, "session_age_str", lambda p: "2h ago")
        assert P.cmd_sessions(_args(sessions_cmd="list")) == 0


# ============================================================ rm


class TestSessionsRm:
    def test_rm_all(self, monkeypatch):
        monkeypatch.setattr(P, "remove_session", lambda target, all_sessions=False: 5)
        assert P.cmd_sessions(_args(sessions_cmd="rm", all=True)) == 0

    def test_rm_no_target(self, monkeypatch):
        assert P.cmd_sessions(_args(sessions_cmd="rm")) == 1

    def test_rm_not_found(self, monkeypatch):
        monkeypatch.setattr(P, "resolve_session", lambda t: None)
        assert P.cmd_sessions(_args(sessions_cmd="rm", target="ghost")) == 1

    def test_rm_yes(self, monkeypatch, tmp_path):
        path = tmp_path / "sess.jsonl"
        path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(P, "resolve_session", lambda t: path)
        monkeypatch.setattr(P, "session_title", lambda p: "title")
        monkeypatch.setattr(P, "remove_session", lambda t: 1)
        assert P.cmd_sessions(_args(sessions_cmd="rm", target="sess",
                                    yes=True)) == 0

    def test_rm_confirm_no(self, monkeypatch, tmp_path):
        path = tmp_path / "sess.jsonl"
        path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(P, "resolve_session", lambda t: path)
        monkeypatch.setattr(P, "session_title", lambda p: "title")
        monkeypatch.setattr("builtins.input", lambda *a: "n")
        assert P.cmd_sessions(_args(sessions_cmd="rm", target="sess")) == 0

    def test_rm_remove_fails(self, monkeypatch, tmp_path):
        path = tmp_path / "sess.jsonl"
        path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(P, "resolve_session", lambda t: path)
        monkeypatch.setattr(P, "session_title", lambda p: "title")
        monkeypatch.setattr(P, "remove_session", lambda t: 0)
        assert P.cmd_sessions(_args(sessions_cmd="rm", target="sess",
                                    yes=True)) == 1


# ============================================================ dispatch


class TestSessionsDispatch:
    def test_default_is_list(self, monkeypatch):
        monkeypatch.setattr(P, "list_recent", lambda n: [])
        assert P.cmd_sessions(_args()) == 0

    def test_unknown(self):
        assert P.cmd_sessions(_args(sessions_cmd="bogus")) == 1
