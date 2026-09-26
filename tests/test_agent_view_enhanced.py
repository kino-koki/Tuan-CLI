"""A1: agent view 增强测试 —— rich 表格 / kill / watch 模式 (非交互)。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from qingxiaotuan.cli.cmd_agents_view import (
    collect_sessions,
    kill_session,
    render_table,
    watch_loop,
)


def _write_session(path: Path, kind: str, events: list, task: str = "测试任务") -> None:
    """造一个假会话 jsonl。"""
    now = time.time()
    lines = [json.dumps({
        "ts": now, "type": "session.meta", "task": task,
        "kind": kind, "started_at": now - 120,
    }, ensure_ascii=False)]
    for ev in events:
        lines.append(json.dumps({"ts": now, **ev}, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_collect_sessions_columns(tmp_path):
    sd = tmp_path / "sessions"
    sd.mkdir()
    _write_session(sd / "20260101-100000-aaaaaa.jsonl", "background", [
        {"type": "user", "message": {"content": "整理周报"}},
        {"type": "assistant", "message": {"content": "已整理完成"}},
        {"type": "job.done"},
    ])
    _write_session(sd / "20260101-110000-bbbbbb.jsonl", "interactive", [
        {"type": "user", "message": {"content": "帮我看下这个报错是什么意思"}},
    ], task="")
    rows = collect_sessions(sd)
    assert len(rows) == 2
    by_sid = {r["sid"]: r for r in rows}
    a = next(r for r in rows if r["sid"].startswith("20260101-100000"))
    assert a["kind"] == "background"
    assert a["status"] == "done"
    assert a["summary"]
    assert len(a["summary"]) <= 40
    b = next(r for r in rows if r["sid"].startswith("20260101-110000"))
    assert b["kind"] == "interactive"
    assert b["status"] == "waiting"
    assert b["elapsed"] >= 0


def test_render_table_runs(tmp_path):
    sd = tmp_path / "sessions"
    sd.mkdir()
    _write_session(sd / "s1.jsonl", "interactive", [
        {"type": "user", "message": {"content": "你好"}},
    ])
    rows = collect_sessions(sd)
    table = render_table(rows)
    cols = {c.header for c in table.columns}
    assert {"Session", "类型", "状态", "最后消息", "创建时间", "时长"} <= cols


def test_kill_session_appends_cancel(tmp_path):
    sd = tmp_path / "sessions"
    sd.mkdir()
    _write_session(sd / "20260101-120000-cccccc.jsonl", "background", [
        {"type": "user", "message": {"content": "跑个长任务"}},
    ])
    result = kill_session(sd, "20260101-120000")
    assert result["ok"] is True
    assert result["session_id"] == "20260101-120000-cccccc"
    lines = (sd / "20260101-120000-cccccc.jsonl").read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(lines[-1])
    assert last["type"] == "job.cancel"
    from qingxiaotuan.cli.cmd_agents_view import _get_session_status
    assert _get_session_status(sd / "20260101-120000-cccccc.jsonl") == "cancelled"


def test_kill_session_not_found(tmp_path):
    sd = tmp_path / "sessions"
    sd.mkdir()
    result = kill_session(sd, "nope")
    assert result["ok"] is False


def test_watch_loop_one_iteration(tmp_path):
    sd = tmp_path / "sessions"
    sd.mkdir()
    _write_session(sd / "w1.jsonl", "interactive", [
        {"type": "user", "message": {"content": "watch 测试"}},
    ])
    slept: list = []
    watch_loop(sd, interval=0.01, max_iterations=2, sleep=lambda s: slept.append(s))
    assert slept == [0.01]  # 渲染两帧, 中间 sleep 一次后退出
