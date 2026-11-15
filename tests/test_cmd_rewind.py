"""cmd_rewind tests -- session rewind CLI (list + truncate)."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import pytest

from tuan_cli.cli import cmd_rewind as P
from tuan_cli.core.rewind import RewindManager, rewind_session_file, RewindError


@pytest.fixture(autouse=True)
def _patch_paths(monkeypatch, tmp_path):
    # home_dir -> tmp_path so _resolve_session_file looks at tmp_path/sessions
    monkeypatch.setattr("tuan_cli.cli.cmd_rewind.home_dir", lambda: tmp_path)
    monkeypatch.setattr("tuan_cli.cli.cmd_rewind.default_workspace",
                        lambda: str(tmp_path))
    return tmp_path


def _make_session(home, sid, n_events=5, meta=True):
    """Write a session jsonl with n_events business events + optional meta."""
    sessions_dir = home / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{sid}.jsonl"
    records = []
    if meta:
        records.append({"ts": time.time(), "type": "session.meta", "sid": sid})
    for i in range(n_events):
        records.append({"ts": time.time(), "type": "user", "content": f"msg{i}"})
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                    encoding="utf-8")
    return path


def _args(**kw):
    base = dict(session_id="", list=False, to=None, workspace=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- helpers

class TestHelpers:
    def test_resolve_session_no_dir(self, tmp_path):
        # home_dir returns tmp_path; sessions dir doesn't exist
        assert P._resolve_session_file("anything") is None

    def test_resolve_session_empty(self, tmp_path):
        (tmp_path / "sessions").mkdir()
        assert P._resolve_session_file("") is None

    def test_resolve_session_prefix(self, tmp_path):
        _make_session(tmp_path, "abc123")
        p = P._resolve_session_file("abc")
        assert p is not None and p.name.startswith("abc")

    def test_resolve_session_latest_no_sid(self, tmp_path):
        p1 = _make_session(tmp_path, "sess_a")
        time.sleep(0.01)
        p2 = _make_session(tmp_path, "sess_b")
        # touch to ensure different mtime
        import os
        os.utime(p2, None)
        p = P._resolve_session_file("")
        assert p is not None
        assert p.name.endswith(".jsonl")


# ---------------------------------------------------------------- list

class TestList:
    def test_list_empty(self, capsys, tmp_path):
        rc = P.cmd_rewind(_args(list=True, session_id="nonexistent"))
        assert rc == 0
        assert "没有可回退的快照" in capsys.readouterr().out

    def test_list_with_snapshots(self, capsys, tmp_path):
        # create session + snapshot
        sess = _make_session(tmp_path, "sess1", n_events=3)
        mgr = RewindManager(str(tmp_path))
        mgr.snapshot([{"role": "user", "content": "hi"}],
                     reason="user_input", session_id="sess1", event_count=3)
        rc = P.cmd_rewind(_args(list=True, session_id="sess1"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "快照" in out
        assert "回退" in out

    def test_list_alias_flag(self, capsys, tmp_path):
        rc = P.cmd_rewind(_args(list=True))
        assert rc == 0


# ---------------------------------------------------------------- rewind

class TestRewind:
    def test_rewind_missing_session(self, capsys, tmp_path):
        rc = P.cmd_rewind(_args(session_id="nope"))
        assert rc == 1
        assert "未找到会话文件" in capsys.readouterr().out

    def test_rewind_no_snapshots(self, capsys, tmp_path):
        _make_session(tmp_path, "sess_x", n_events=5)
        rc = P.cmd_rewind(_args(session_id="sess_x"))
        assert rc == 1
        out = capsys.readouterr().out
        # Should be RewindError path
        assert "rewind" in out.lower()

    def test_rewind_success(self, capsys, tmp_path):
        sess = _make_session(tmp_path, "sess_ok", n_events=5)
        mgr = RewindManager(str(tmp_path))
        mgr.snapshot([{"role": "user", "content": "hi"}],
                     reason="manual", session_id="sess_ok", event_count=2)
        rc = P.cmd_rewind(_args(session_id="sess_ok"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "已 Rewind" in out
        # After rewind, jsonl has a rewind.applied marker
        data = sess.read_text(encoding="utf-8")
        lines = [json.loads(l) for l in data.splitlines() if l.strip()]
        types = [r.get("type") for r in lines]
        assert "rewind.applied" in types


# ---------------------------------------------------------------- core rewind

class TestRewindCore:
    def test_rewind_session_file_missing(self, tmp_path):
        with pytest.raises(RewindError, match="不存在"):
            rewind_session_file(tmp_path / "nope.jsonl", str(tmp_path))

    def test_rewind_session_file_no_snap(self, tmp_path):
        sess = _make_session(tmp_path, "sess_nosnap", n_events=3)
        with pytest.raises(RewindError, match="没有可回退"):
            rewind_session_file(sess, str(tmp_path))

    def test_rewind_session_file_keeps_events(self, tmp_path):
        sess = _make_session(tmp_path, "sess_keep", n_events=10, meta=False)
        mgr = RewindManager(str(tmp_path))
        mgr.snapshot([{"role": "user", "content": "x"}],
                     reason="manual", session_id="sess_keep", event_count=3)
        result = rewind_session_file(sess, str(tmp_path))
        assert result["ok"] is True
        assert result["kept_events"] == 3
        assert result["removed_events"] == 7
