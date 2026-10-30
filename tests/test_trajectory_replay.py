"""会话轨迹回放 (core/trajectory_replay.py) 的专项测试。

覆盖:
- TrajectoryEvent / TrajectoryStats / TrajectorySnapshot 数据类
- list_sessions: 列出会话 (含元数据/容错)
- replay: 多维筛选 (type/tool/source/status/时间窗/last_n) + on_event 回调
- analyze: 统计 (类型/工具/状态/来源/延迟/安全/拒绝/错误)
- fork / restore_snapshot / list_snapshots
- export_timeline: Markdown 时间线
- _load_events / _read_session_meta: 事件解析与容错

用 tmp_path 构造假会话 jsonl, 不依赖真实 ~/.tuan。
"""

from __future__ import annotations

import json
import time

import pytest

from tuan_cli.core.trajectory_replay import (
    TrajectoryEvent,
    TrajectoryReplay,
    TrajectorySnapshot,
    TrajectoryStats,
)


# ------------------------------------------------------------ 数据类

class TestDataclasses:
    def test_event_to_dict_roundtrip(self):
        """TrajectoryEvent.to_dict 序列化全部字段。"""
        ev = TrajectoryEvent(
            seq=3, ts=1700000000.0, event_type="tool_call",
            payload={"name": "read"}, source="shell",
            tool_name="read", duration_ms=12.5, status="ok",
        )
        d = ev.to_dict()
        assert d["seq"] == 3
        assert d["event_type"] == "tool_call"
        assert d["payload"] == {"name": "read"}
        assert d["tool_name"] == "read"
        assert d["duration_ms"] == 12.5

    def test_stats_to_dict_avg_latency(self):
        """to_dict 计算平均工具延迟 (空列表为 0)。"""
        s = TrajectoryStats()
        s.tool_latencies = {"read": [10.0, 20.0, 30.0], "write": []}
        d = s.to_dict()
        assert d["avg_tool_latency"]["read"] == 20.0
        assert d["avg_tool_latency"]["write"] == 0
        assert d["total_events"] == 0

    def test_snapshot_post_init_sets_created_at(self):
        """created_at 缺省时自动设为当前时间。"""
        snap = TrajectorySnapshot(session_id="s1", fork_point=5, events=[])
        assert snap.created_at > 0


# ------------------------------------------------------------ 夹具: 假会话

def _write_session(session_dir, session_id, events):
    """把 events (list[dict]) 写成会话 jsonl。"""
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"{session_id}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def _sample_events():
    """构造一段带多类型/多状态/多工具的会话事件。"""
    base = 1700000000.0
    return [
        {"ts": base, "type": "user",
         "message": {"content": "帮我看看这个文件"}, "source": "cli"},
        {"ts": base + 1, "type": "assistant",
         "message": {"content": "好的, 我来读取"}, "source": "cli"},
        {"ts": base + 2, "type": "tool_call", "name": "read",
         "source": "shell", "duration_ms": 50, "status": "ok"},
        {"ts": base + 3, "type": "tool", "name": "write",
         "source": "shell", "duration_ms": 120, "status": "error"},
        {"ts": base + 4, "type": "security", "source": "safety",
         "payload": {"reason": "疑似外泄"}, "status": "denied"},
        {"ts": base + 5, "type": "tool_call", "name": "grep",
         "source": "mcp", "duration_ms": 30, "status": "ok"},
    ]


class TestListSessions:
    def test_empty_dir(self, tmp_path):
        """无会话目录: 返回空列表。"""
        r = TrajectoryReplay(session_dir=tmp_path)
        assert r.list_sessions() == []

    def test_lists_with_meta(self, tmp_path):
        """列出会话含元数据 (event_count/last_ts/duration_s)。"""
        _write_session(tmp_path, "sess1", _sample_events())
        _write_session(tmp_path, "sess2", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        sessions = r.list_sessions()
        assert len(sessions) == 2
        ids = {s["session_id"] for s in sessions}
        assert ids == {"sess1", "sess2"}
        for s in sessions:
            assert s["event_count"] == 6
            assert s["last_ts"] > 0
            assert s["duration_s"] > 0

    def test_last_n_limit(self, tmp_path):
        """last_n 限制返回数量。"""
        for i in range(5):
            _write_session(tmp_path, f"s{i}", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        assert len(r.list_sessions(last_n=3)) == 3

    def test_corrupt_file_tolerated(self, tmp_path):
        """损坏的 jsonl 仍被列出 (异常时降级为最小元数据)。"""
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\n{{{\n", encoding="utf-8")
        r = TrajectoryReplay(session_dir=tmp_path)
        sessions = r.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "bad"
        # 损坏文件: 元数据容错降级 (event_count 统计所有行含损坏行, 不抛异常)
        assert sessions[0]["event_count"] == 2


class TestReplay:
    def test_missing_session_empty(self, tmp_path):
        """不存在的会话: 空列表。"""
        r = TrajectoryReplay(session_dir=tmp_path)
        assert r.replay("nope") == []

    def test_all_events_ordered(self, tmp_path):
        """回放全部事件, seq 从 1 递增。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        events = r.replay("sess")
        assert len(events) == 6
        assert [e.seq for e in events] == [1, 2, 3, 4, 5, 6]

    def test_filter_type(self, tmp_path):
        """filter_type 只留对应类型。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        events = r.replay("sess", filter_type="tool_call")
        assert len(events) == 2
        assert all(e.event_type == "tool_call" for e in events)

    def test_filter_tool(self, tmp_path):
        """filter_tool 按工具名筛选。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        events = r.replay("sess", filter_tool="write")
        assert len(events) == 1
        assert events[0].tool_name == "write"

    def test_filter_source(self, tmp_path):
        """filter_source 按来源模块筛选。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        events = r.replay("sess", filter_source="mcp")
        assert len(events) == 1
        assert events[0].tool_name == "grep"

    def test_filter_status(self, tmp_path):
        """filter_status 按状态筛选。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        denied = r.replay("sess", filter_status="denied")
        assert len(denied) == 1
        assert denied[0].event_type == "security"
        errors = r.replay("sess", filter_status="error")
        assert len(errors) == 1
        assert errors[0].tool_name == "write"

    def test_time_window(self, tmp_path):
        """since_ts/until_ts 时间窗筛选。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        base = 1700000000.0
        mid = r.replay("sess", since_ts=base + 2, until_ts=base + 4)
        assert len(mid) == 3  # ts = +2,+3,+4

    def test_last_n(self, tmp_path):
        """last_n 只返回最后 N 条。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        tail = r.replay("sess", last_n=2)
        assert len(tail) == 2
        assert tail[-1].event_type == "tool_call"

    def test_on_event_callback(self, tmp_path):
        """on_event 回调每条事件; 回调抛异常被吞掉。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        seen = []
        r.replay("sess", on_event=lambda e: seen.append(e.seq))
        assert seen == [1, 2, 3, 4, 5, 6]
        # 回调抛异常不中断
        r.replay("sess", on_event=lambda e: 1 / 0)
        r.replay("sess", on_event=lambda e: (_ for _ in ()).throw(RuntimeError()))

    def test_combined_filters(self, tmp_path):
        """多条件组合筛选。"""
        evs = _sample_events()
        _write_session(tmp_path, "sess", evs)
        r = TrajectoryReplay(session_dir=tmp_path)
        got = r.replay("sess", filter_type="tool", filter_tool="write",
                       filter_status="error")
        assert len(got) == 1
        assert got[0].tool_name == "write"


class TestAnalyze:
    def test_empty_session(self, tmp_path):
        """空会话: 全零统计。"""
        r = TrajectoryReplay(session_dir=tmp_path)
        s = r.analyze("missing")
        assert s.total_events == 0
        assert s.to_dict()["total_events"] == 0

    def test_stats_full(self, tmp_path):
        """完整统计各维度。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        s = r.analyze("sess")
        assert s.total_events == 6
        assert s.total_duration_ms == pytest.approx(5 * 1000, abs=0.001)
        assert s.by_type["user"] == 1
        assert s.by_type["tool_call"] == 2
        assert s.by_tool["read"] == 1
        assert s.by_tool["write"] == 1
        assert s.by_status["ok"] == 4
        assert s.by_status["error"] == 1
        assert s.by_status["denied"] == 1
        assert s.by_source["shell"] == 2
        assert s.security_events == 1
        assert s.denied_events == 1
        assert s.error_events == 1
        # 平均延迟
        d = s.to_dict()
        assert d["avg_tool_latency"]["read"] == 50.0
        assert d["avg_tool_latency"]["write"] == 120.0


class TestFork:
    def test_fork_and_snapshot(self, tmp_path):
        """fork 生成快照并落盘, 可 restore/list。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        snap = r.fork("sess", at_seq=3, label="alt")
        assert snap.fork_point == 3
        assert len(snap.events) == 3
        assert snap.label == "alt"

        # 快照已落盘
        snaps = r.list_snapshots()
        assert len(snaps) == 1
        assert snaps[0]["session_id"] == "sess"
        assert snaps[0]["fork_point"] == 3
        assert snaps[0]["event_count"] == 3

        # 恢复
        restored = r.restore_snapshot(snaps[0]["id"])
        assert restored is not None
        assert restored.fork_point == 3
        assert len(restored.events) == 3
        assert restored.events[0].event_type == "user"

    def test_fork_default_label(self, tmp_path):
        """label 缺省为 fork_at_{seq}。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        snap = r.fork("sess", at_seq=2)
        assert snap.label == "fork_at_2"

    def test_restore_missing_none(self, tmp_path):
        """恢复不存在的快照返回 None。"""
        r = TrajectoryReplay(session_dir=tmp_path)
        assert r.restore_snapshot("does-not-exist") is None

    def test_restore_corrupt_none(self, tmp_path):
        """损坏快照返回 None。"""
        d = tmp_path / ".trajectories"
        d.mkdir(parents=True)
        (d / "bad.json").write_text("not json", encoding="utf-8")
        r = TrajectoryReplay(session_dir=tmp_path)
        assert r.restore_snapshot("bad") is None

    def test_list_snapshots_empty(self, tmp_path):
        """无快照目录: 空列表。"""
        r = TrajectoryReplay(session_dir=tmp_path)
        assert r.list_snapshots() == []


class TestExportTimeline:
    def test_timeline_content(self, tmp_path):
        """导出 Markdown 时间线, 含事件行与内容摘要。"""
        _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        md = r.export_timeline("sess")
        assert md.startswith("# 会话轨迹: sess")
        assert "事件数: 6" in md
        assert "user" in md
        assert "assistant" in md
        assert "tool_call" in md
        assert "security" in md
        # 用户消息内容摘要
        assert "帮我看看这个文件" in md
        # 安全原因
        assert "疑似外泄" in md

    def test_timeline_empty(self, tmp_path):
        """空会话: 仅标题。"""
        r = TrajectoryReplay(session_dir=tmp_path)
        md = r.export_timeline("missing")
        assert "事件数: 0" in md


class TestLoadEvents:
    def test_parse_shapes(self, tmp_path):
        """解析不同键名形态 (type/event_type, message/payload, name/tool_name)。"""
        evs = [
            {"ts": 1.0, "event_type": "system", "payload": {"k": 1}},
            {"ts": 2.0, "type": "assistant", "message": {"content": "hi"}},
            {"ts": 3.0, "type": "tool", "name": "read", "tool_name": "unused"},
        ]
        _write_session(tmp_path, "sess", evs)
        r = TrajectoryReplay(session_dir=tmp_path)
        events = r.replay("sess")
        assert len(events) == 3
        assert events[0].event_type == "system"
        assert events[1].payload == {"content": "hi"}
        assert events[2].tool_name == "read"

    def test_skip_corrupt_lines(self, tmp_path):
        """损坏行跳过, 正常行保留。"""
        p = tmp_path / "sess.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"ts": 1, "type": "user"}\n')
            f.write("not json\n")
            f.write('{"ts": 3, "type": "assistant"}\n')
        r = TrajectoryReplay(session_dir=tmp_path)
        events = r.replay("sess")
        assert len(events) == 2
        assert events[0].event_type == "user"
        assert events[1].event_type == "assistant"

    def test_cache_used(self, tmp_path):
        """同一会话二次加载走缓存 (文件变更不影响)。"""
        path = _write_session(tmp_path, "sess", _sample_events())
        r = TrajectoryReplay(session_dir=tmp_path)
        r.replay("sess")
        # 文件追加, 但缓存生效, 事件数不变
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 9.0, "type": "system"}) + "\n")
        assert len(r.replay("sess")) == 6
