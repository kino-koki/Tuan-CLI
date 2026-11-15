"""``tuan auditstore`` CLI 的单元测试 (cmd_auditstore.py)。

内核全量审计事件归档只读查询。覆盖:
1. _get_home: 显式 / 默认
2. _open_store: 未初始化 / 有 log / 有轮转
3. _fmt_ts: 正常 / 0
4. _ev_row: 完整字段
5. _cmd_stats: 未初始化 / JSON / 正常
6. _cmd_recent: 未初始化 / 正常 / JSON
7. _cmd_query: 未初始化 / 正常 / JSON
8. cmd_auditstore: 默认 stats / 各子命令 / 未知子命令

通过 monkeypatch 打桩 _open_store 返回 fake AuditStore。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_auditstore as P


def _args(**kw) -> SimpleNamespace:
    base = dict(auditstore_cmd=None, home=None, json=False, limit=20,
                type=None, keyword="", since=None, until=None)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeEv:
    def __init__(self, seq=1, ts=1000.0, type="tool_call", payload=None):
        self.seq = seq
        self.ts = ts
        self.type = type
        self.payload = payload or {"command": "ls"}


class _FakeStore:
    def __init__(self, stats=None, events=None, **kw):
        self._stats = stats or {
            "total": 100, "by_type": {"tool_call": 50, "model_request": 50},
            "buffered": 5, "enabled": True,
            "oldest_iso": "2026-01-01T00:00:00Z",
            "newest_iso": "2026-01-15T00:00:00Z",
        }
        self._events = events or [_FakeEv()]

    def stats(self):
        return self._stats

    def recent(self, n=20, types=()):
        return self._events[:n]

    def query(self, q):
        return self._events[:q.limit]


# ============================================================ _get_home


class TestGetHome:
    def test_explicit(self) -> None:
        rc = P._get_home("/tmp/ws/x")
        assert rc == Path("/tmp/ws/x").resolve()

    def test_default(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "home_dir", lambda: str(tmp_path))
        rc = P._get_home(None)
        assert rc == tmp_path.resolve()


# ============================================================ _open_store


class TestOpenStore:
    def test_uninitialized(self, tmp_path) -> None:
        rc = P._open_store(tmp_path)
        assert rc is None

    def test_with_log(self, monkeypatch, tmp_path) -> None:
        (tmp_path / "audit").mkdir()
        (tmp_path / "audit" / "audit.log").write_text("{}", encoding="utf-8")
        monkeypatch.setattr("tuan_cli.audit.store.AuditStore", _FakeStore)
        rc = P._open_store(tmp_path)
        assert rc is not None

    def test_with_rotated_only(self, monkeypatch, tmp_path) -> None:
        (tmp_path / "audit").mkdir()
        (tmp_path / "audit" / "audit.log.1").write_text("{}", encoding="utf-8")
        monkeypatch.setattr("tuan_cli.audit.store.AuditStore", _FakeStore)
        rc = P._open_store(tmp_path)
        assert rc is not None


# ============================================================ _fmt_ts


class TestFmtTs:
    def test_zero(self) -> None:
        assert P._fmt_ts(0) == "-"

    def test_valid(self) -> None:
        s = P._fmt_ts(1000.0)
        assert s != "-"
        assert "1970" in s or "2001" in s or "01" in s


# ============================================================ _ev_row


class TestEvRow:
    def test_complete_fields(self) -> None:
        ev = _FakeEv(seq=5, ts=1700000000.0, type="test", payload={"k": "v"})
        r = P._ev_row(ev)
        assert r["seq"] == 5
        assert r["type"] == "test"
        assert r["iso"] is not None
        assert r["payload"] == {"k": "v"}

    def test_zero_ts(self) -> None:
        ev = _FakeEv(ts=0)
        r = P._ev_row(ev)
        assert r["iso"] is None


# ============================================================ _cmd_stats


class TestCmdStats:
    def test_uninitialized(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_stats(_args(), store=None)
        assert rc == 0

    def test_uninitialized_json(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_stats(_args(json=True), store=None)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is False

    def test_normal(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_stats(_args(home="/tmp/h"), store=_FakeStore())
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_stats(_args(json=True), store=_FakeStore())
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is True
        assert data["stats"]["total"] == 100


# ============================================================ _cmd_recent


class TestCmdRecent:
    def test_uninitialized(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_recent(_args(), store=None)
        assert rc == 0

    def test_uninitialized_json(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_recent(_args(json=True), store=None)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["events"] == []

    def test_normal(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_recent(_args(), store=_FakeStore())
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_recent(_args(json=True), store=_FakeStore())
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data["events"]) == 1
        assert data["events"][0]["type"] == "tool_call"


# ============================================================ _cmd_query


class TestCmdQuery:
    def test_uninitialized(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_query(_args(), store=None)
        assert rc == 0

    def test_uninitialized_json(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_query(_args(json=True), store=None)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["events"] == []

    def test_normal(self, monkeypatch) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_query(_args(keyword="test"), store=_FakeStore())
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_query(_args(json=True, keyword="cmd"), store=_FakeStore())
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data["events"]) == 1


# ============================================================ cmd_auditstore 入口


class TestCmdAuditstore:
    def test_default_stats(self, monkeypatch) -> None:
        monkeypatch.setattr(P, "_open_store", lambda home: None)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_auditstore(_args())
        assert rc == 0

    def test_stats_subcommand(self, monkeypatch) -> None:
        monkeypatch.setattr(P, "_open_store", lambda home: _FakeStore())
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_auditstore(_args(auditstore_cmd="stats"))
        assert rc == 0

    def test_recent_subcommand(self, monkeypatch) -> None:
        monkeypatch.setattr(P, "_open_store", lambda home: _FakeStore())
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_auditstore(_args(auditstore_cmd="recent"))
        assert rc == 0

    def test_query_subcommand(self, monkeypatch) -> None:
        monkeypatch.setattr(P, "_open_store", lambda home: _FakeStore())
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_auditstore(_args(auditstore_cmd="query", keyword="x"))
        assert rc == 0

    def test_unknown_subcommand(self, monkeypatch) -> None:
        monkeypatch.setattr(P, "_open_store", lambda home: _FakeStore())
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_auditstore(_args(auditstore_cmd="bogus"))
        assert rc == 1
        text = "\n".join(printed)
        assert "未知子命令" in text

    def test_open_store_failure(self, monkeypatch) -> None:
        def _raise(home):
            raise RuntimeError("boom")
        monkeypatch.setattr(P, "_open_store", _raise)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_auditstore(_args())
        assert rc == 1
