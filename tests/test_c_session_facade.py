"""C-4 会话门面单测 (tuan_cli/session/store.py + cli/cmd_sessions.py)。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from tuan_cli.session import store as session_store


def _make_session(home: Path, sid: str, title: str) -> Path:
    d = home / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}.jsonl"
    p.write_text("\n".join([
        json.dumps({"ts": 1.0, "type": "session.meta", "task": title}, ensure_ascii=False),
        json.dumps({"ts": 2.0, "type": "user", "message": {"role": "user", "content": "你好"}},
                   ensure_ascii=False),
        json.dumps({"ts": 3.0, "type": "assistant",
                    "message": {"role": "assistant", "content": "嗨"}}, ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    return p


def test_list_recent_resolve_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("TUAN_HOME", str(tmp_path))
    _make_session(tmp_path, "20261025-100000-aaaaaa", "第一个会话")
    _make_session(tmp_path, "20261025-110000-bbbbbb", "第二个会话")

    recent = session_store.list_recent(20)
    assert len(recent) == 2
    # 按时间倒序: 11 点的在前
    assert recent[0].stem.startswith("20261025-110000")

    # resolve: latest
    assert session_store.resolve_session("latest").stem.startswith("20261025-110000")
    # resolve: 前缀
    assert session_store.resolve_session("20261025-100000").stem.startswith("20261025-100000")
    # resolve: 编号
    assert session_store.resolve_session("2").stem.startswith("20261025-100000")

    # remove
    assert session_store.remove_session("20261025-100000") == 1
    assert len(session_store.list_recent(20)) == 1

    # remove --all
    assert session_store.remove_session("", all_sessions=True) == 1
    assert session_store.list_recent(20) == []


def test_load_history(tmp_path, monkeypatch):
    monkeypatch.setenv("TUAN_HOME", str(tmp_path))
    p = _make_session(tmp_path, "20261025-120000-cccccc", "历史")
    msgs = session_store.load_history(p)
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_cmd_sessions_list(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("TUAN_HOME", str(tmp_path))
    from tuan_cli.cli import cmd_sessions
    _make_session(tmp_path, "20261025-120000-dddddd", "展示标题")
    args = type("A", (), {"sessions_cmd": "list"})()
    assert cmd_sessions.cmd_sessions(args) == 0
    out = capsys.readouterr().out
    assert "展示标题" in out


def test_cmd_sessions_rm(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("TUAN_HOME", str(tmp_path))
    from tuan_cli.cli import cmd_sessions
    _make_session(tmp_path, "20261025-130000-eeeeee", "待删")
    args = type("A", (), {"sessions_cmd": "rm", "target": "20261025-130000",
                          "all": False, "yes": True})()
    assert cmd_sessions.cmd_sessions(args) == 0
    assert session_store.list_recent(20) == []
