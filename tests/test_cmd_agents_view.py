"""``tuan agents view`` CLI 的单元测试 (cmd_agents_view.py)。

会话面板。覆盖:
1. collect_sessions 空目录 / 多条排序
2. _get_session_status: done/waiting/executing/running/job.cancel
3. _session_kind: interactive vs background (meta.kind / task 字段)
4. _fmt_duration: s/m/h/d 边界
5. _last_summary: 从 meta/流里取摘要, 截断 40 字
6. render_table 渲染不抛
7. watch_loop max_iterations 收敛
8. kill_session: 空 ID / 未找到 / 命中并写 job.cancel / job_store_updated

通过 monkeypatch 打桩 SessionStore.read_meta / peek_title / home_dir。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_agents_view as V


# ============================================================ 工厂


def _write_jsonl(path: Path, events: list) -> None:
    """写一个 jsonl 会话文件。"""
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _patch_session_store(monkeypatch, meta=None, title="") -> None:
    """打桩 SessionStore.read_meta / peek_title 类方法。"""
    monkeypatch.setattr(V.SessionStore, "read_meta",
                        classmethod(lambda cls, path: meta))
    monkeypatch.setattr(V.SessionStore, "peek_title",
                        classmethod(lambda cls, path: title))


# ============================================================ _get_session_status


class TestGetSessionStatus:
    def test_background_running(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta={"kind": "background"})
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [
            {"type": "user", "message": {"content": "hi"}},
        ])
        assert V._get_session_status(p) == "running"

    def test_background_done(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta={"kind": "background"})
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [
            {"type": "user", "message": {"content": "hi"}},
            {"type": "job.done", "status": "ok"},
        ])
        assert V._get_session_status(p) == "done"

    def test_background_failed(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta={"kind": "background"})
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "user", "message": {}},
                         {"type": "job.error", "message": "boom"}])
        assert V._get_session_status(p) == "failed"

    def test_background_cancelled(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta={"kind": "background"})
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "user", "message": {}},
                         {"type": "job.cancel"}])
        assert V._get_session_status(p) == "cancelled"

    def test_interactive_done(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None)
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "user", "message": {}},
                         {"type": "assistant", "message": {"content": "ok"}}])
        assert V._get_session_status(p) == "done"

    def test_interactive_waiting(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None)
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "user", "message": {"content": "?"}}])
        assert V._get_session_status(p) == "waiting"

    def test_interactive_executing(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None)
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "tool_call", "name": "run_shell"}])
        assert V._get_session_status(p) == "executing"

    def test_interactive_cancelled(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None)
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "job.cancel"}])
        assert V._get_session_status(p) == "cancelled"

    def test_empty_file(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None)
        p = tmp_path / "x.jsonl"
        p.write_text("", encoding="utf-8")
        assert V._get_session_status(p) == "empty"

    def test_unknown_on_garbage(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None)
        p = tmp_path / "x.jsonl"
        p.write_text("not json at all\n", encoding="utf-8")
        assert V._get_session_status(p) == "unknown"


# ============================================================ _session_kind


class TestSessionKind:
    def test_interactive_default(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None)
        assert V._session_kind(tmp_path / "x.jsonl") == "interactive"

    def test_background_by_meta(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta={"kind": "background"})
        assert V._session_kind(tmp_path / "x.jsonl") == "background"

    def test_background_by_task(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta={"task": "扫描文件"})
        assert V._session_kind(tmp_path / "x.jsonl") == "background"

    def test_arbitrary_kind(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta={"kind": "api"})
        assert V._session_kind(tmp_path / "x.jsonl") == "api"


# ============================================================ _fmt_duration


class TestFmtDuration:
    def test_seconds(self) -> None:
        assert V._fmt_duration(0) == "0s"
        assert V._fmt_duration(59) == "59s"

    def test_minutes(self) -> None:
        assert V._fmt_duration(60) == "1m"
        assert V._fmt_duration(3599) == "59m"

    def test_hours(self) -> None:
        assert V._fmt_duration(3600) == "1h"
        assert V._fmt_duration(86399) == "23h"

    def test_days(self) -> None:
        assert V._fmt_duration(86400) == "1d"
        assert V._fmt_duration(172800) == "2d"


# ============================================================ _last_summary


class TestLastSummary:
    def test_from_title_first(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None, title="标题摘要")
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "user", "message": {"content": "流里的内容"}}])
        assert V._last_summary(p) == "标题摘要"

    def test_truncate_to_40(self, tmp_path, monkeypatch) -> None:
        long = "x" * 100
        _patch_session_store(monkeypatch, meta=None, title=long)
        p = tmp_path / "x.jsonl"
        p.write_text("", encoding="utf-8")
        out = V._last_summary(p, 40)
        assert len(out) == 40
        assert out == "x" * 40

    def test_from_user_message(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None, title="")
        p = tmp_path / "x.jsonl"
        _write_jsonl(p, [{"type": "user", "message": {"content": "帮我查一下"}}])
        assert V._last_summary(p) == "帮我查一下"

    def test_no_summary_fallback(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None, title="")
        p = tmp_path / "x.jsonl"
        p.write_text("", encoding="utf-8")
        assert V._last_summary(p) == "(无摘要)"


# ============================================================ collect_sessions


class TestCollectSessions:
    def test_empty_dir(self, tmp_path) -> None:
        assert V.collect_sessions(tmp_path) == []

    def test_no_dir(self, tmp_path) -> None:
        assert V.collect_sessions(tmp_path / "missing") == []

    def test_collects_jsonl_sorted(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None, title="t")
        for name in ("a.jsonl", "b.jsonl"):
            p = tmp_path / name
            _write_jsonl(p, [{"type": "user", "message": {"content": "hi"}}])
            time.sleep(0.01)  # 让 mtime 不同
        rows = V.collect_sessions(tmp_path)
        assert len(rows) == 2
        # 最新在前
        assert rows[0]["mtime"] >= rows[1]["mtime"]
        for row in rows:
            assert "sid" in row and "status" in row and "elapsed" in row

    def test_respects_limit(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None, title="t")
        for i in range(5):
            _write_jsonl(tmp_path / f"s{i}.jsonl",
                         [{"type": "user", "message": {}}])
            time.sleep(0.005)
        rows = V.collect_sessions(tmp_path, limit=3)
        assert len(rows) == 3

    def test_short_id_is_12(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None, title="t")
        sid = "abcdefghijk0123456789"
        _write_jsonl(tmp_path / f"{sid}.jsonl", [{"type": "user", "message": {}}])
        rows = V.collect_sessions(tmp_path)
        assert rows[0]["short_id"] == sid[:12]


# ============================================================ render_table


class TestRenderTable:
    def test_renders_without_error(self, monkeypatch) -> None:
        rows = [{
            "sid": "s1", "short_id": "abc123", "kind": "interactive",
            "status": "done", "summary": "hello", "created_at": time.time(),
            "elapsed": 120.0, "mtime": time.time(), "path": Path("/tmp/x.jsonl"),
        }]
        table = V.render_table(rows)
        assert table is not None
        assert len(table.rows) == 1

    def test_empty_renders_empty_table(self) -> None:
        table = V.render_table([])
        assert len(table.rows) == 0


# ============================================================ watch_loop


class TestWatchLoop:
    def test_max_iterations_returns(self, tmp_path, monkeypatch) -> None:
        _patch_session_store(monkeypatch, meta=None, title="t")
        _write_jsonl(tmp_path / "s.jsonl", [{"type": "user", "message": {}}])
        monkeypatch.setattr(V.console, "clear", lambda: None)
        monkeypatch.setattr(V.console, "print", lambda *a, **k: None)
        sleeps = []

        def fake_sleep(_):
            sleeps.append(1)

        V.watch_loop(tmp_path, interval=0.1, max_iterations=3, sleep=fake_sleep)
        assert len(sleeps) == 2  # max=3 -> sleep 在 iteration 1, 2 后触发


# ============================================================ kill_session


class TestKillSession:
    def test_empty_prefix(self, tmp_path) -> None:
        r = V.kill_session(tmp_path, "")
        assert r["ok"] is False
        assert "会话 ID" in r["error"]

    def test_no_match(self, tmp_path) -> None:
        r = V.kill_session(tmp_path, "nonexistent")
        assert r["ok"] is False
        assert "未找到" in r["error"]

    def test_writes_cancel_event(self, tmp_path, monkeypatch) -> None:
        _write_jsonl(tmp_path / "abc123def456.jsonl",
                     [{"type": "user", "message": {}}])
        # BackgroundStore 是 best-effort, 找得到就同步, 找不到不影响 ok
        monkeypatch.setattr(V, "home_dir", lambda: tmp_path)
        r = V.kill_session(tmp_path, "abc123")
        assert r["ok"] is True
        assert r["session_id"] == "abc123def456"
        assert isinstance(r["job_store_updated"], bool)
        # 确认 job.cancel 已追加
        text = (tmp_path / "abc123def456.jsonl").read_text(encoding="utf-8")
        assert "job.cancel" in text


# ============================================================ cmd_agents 入口


class TestCmdAgents:
    def test_attach_without_sid(self, monkeypatch, capsys) -> None:
        _patch_session_store(monkeypatch, meta=None)
        monkeypatch.setattr(V, "home_dir", lambda: Path("/tmp/none"))
        args = SimpleNamespace(agents_cmd="attach", session_id="", watch=False)
        rc = V.cmd_agents(args)
        assert rc == 1

    def test_attach_with_sid(self, monkeypatch) -> None:
        # _UiProxy.__slots__=() 不能 monkeypatch 实例方法; 改 patch 底层 _get_ui
        import tuan_cli.cli._ui_singleton as _uimod
        monkeypatch.setattr(_uimod, "_get_ui",
                            lambda: SimpleNamespace(info=lambda *a, **k: None))
        args = SimpleNamespace(agents_cmd="attach", session_id="xyz", watch=False)
        rc = V.cmd_agents(args)
        assert rc == 0

    def test_unknown_subcommand(self, monkeypatch) -> None:
        monkeypatch.setattr(V.console, "print", lambda *a, **k: None)
        args = SimpleNamespace(agents_cmd="bogus", watch=False)
        rc = V.cmd_agents(args)
        assert rc == 1

    def test_view_empty_sessions(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(V, "home_dir", lambda: tmp_path)
        monkeypatch.setattr(V.console, "print", lambda *a, **k: None)
        args = SimpleNamespace(agents_cmd="view", watch=False)
        rc = V.cmd_agents(args)
        assert rc == 0
