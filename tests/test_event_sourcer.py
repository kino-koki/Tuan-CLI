"""EventSourcer 专项测试 —— 事件溯源核心 (单一真相源 + 分叉/恢复/回放/导出)。

覆盖 tuan_cli.core.event_sourcer:
- emit: 序号递增 / 时间戳 / session_id 回填 / 写 store (append-only)
- emit_parallel / emit_waterfall / emit_bail: 语义标记
- query: kind/since/until/since_seq/until_seq/tags/fork_id/limit 各过滤
- get_event / count
- fork / get_fork / list_forks (含未知 fork)
- replay (正常 / 未知 fork 抛 ValueError / from_seq/to_seq 边界)
- resume_from (user/assistant/tool_call/tool_call_update 重建 messages)
- to_trajectory / export_markdown / export_dict
- SourcedEvent.to_dict/from_dict 往返
"""

from __future__ import annotations

import json
import time

import pytest

from tuan_cli.core.event_sourcer import (
    EventSourcer,
    EventSemantics,
    ForkPoint,
    SourcedEvent,
)


class _FakeStore:
    """最小 SessionStore 替身 —— 采用 EventSourcer 实际契约: append(dict)。

    注意: 真实 memory.sessions.SessionStore.append 是双参数 (event_type, payload),
    但 EventSourcer 的唯一实际使用点 (arch.context.ContextEventLog) 的 append 是
    单参数 dict 契约。此处模拟后者 (EventSourcer 实际依赖的接口)。
    """

    def __init__(self, session_id: str = "sess-1") -> None:
        self.session_id = session_id
        self.records: list = []

    def append(self, d: dict) -> None:
        self.records.append(dict(d))

    def read_all(self):
        return list(self.records)


# ---------------------------------------------------------------- emit

def test_emit_increments_seq_and_returns_event():
    s = EventSourcer()
    ev1 = s.emit("tool_call", {"name": "x"})
    ev2 = s.emit("assistant", {"content": "hi"})
    assert ev1.seq == 1
    assert ev2.seq == 2
    assert ev1.kind == "tool_call"
    assert ev1.payload == {"name": "x"}
    assert ev1.semantics == "emit"
    assert ev1.tags == []
    assert ev1.fork_id == ""


def test_emit_backfills_session_id_from_store():
    store = _FakeStore("sess-abc")
    s = EventSourcer(store)
    ev = s.emit("user", {"content": "hi"})
    assert ev.session_id == "sess-abc"


def test_emit_explicit_session_id_wins():
    s = EventSourcer(_FakeStore("sess-abc"))
    ev = s.emit("user", {"content": "hi"}, session_id="override")
    assert ev.session_id == "override"


def test_emit_writes_to_store_append_only():
    store = _FakeStore("sess-1")
    s = EventSourcer(store)
    s.emit("user", {"content": "a"})
    s.emit("user", {"content": "b"})
    assert len(store.records) == 2
    # 记录含 type 字段 (to_dict 映射 kind -> type)
    assert store.records[0]["type"] == "user"
    assert store.records[0]["content"] == "a"
    assert store.records[1]["content"] == "b"


def test_emit_sets_timestamp():
    before = time.time()
    s = EventSourcer()
    ev = s.emit("x", {})
    after = time.time()
    assert before - 1 <= ev.ts <= after + 1


def test_emit_semantics_enum_values():
    assert EventSemantics.EMIT.value == "emit"
    assert EventSemantics.PARALLEL.value == "parallel"
    assert EventSemantics.SERIAL.value == "serial"
    assert EventSemantics.BAIL.value == "bail"
    assert EventSemantics.WATERFALL.value == "waterfall"


# ---------------------------------------------------------------- emit_parallel / waterfall / bail

def test_emit_parallel_marks_semantics():
    s = EventSourcer()
    evs = s.emit_parallel([("agent.a", {"id": 1}), ("agent.b", {"id": 2})])
    assert len(evs) == 2
    assert evs[0].kind == "agent.a"
    assert evs[0].semantics == "parallel"
    assert evs[1].semantics == "parallel"
    assert evs[1].seq == evs[0].seq + 1


def test_emit_waterfall_marks_semantics_and_order():
    s = EventSourcer()
    evs = s.emit_waterfall([
        ("pre", {"step": 1}),
        ("execute", {"step": 2}),
        ("post", {"step": 3}),
    ])
    assert [e.semantics for e in evs] == ["waterfall"] * 3
    assert [e.payload["step"] for e in evs] == [1, 2, 3]


def test_emit_bail_marks_semantics():
    s = EventSourcer()
    ev = s.emit_bail("loop.abort", {"reason": "limit"})
    assert ev.semantics == "bail"
    assert ev.kind == "loop.abort"


def test_emit_parallel_passes_kwargs():
    s = EventSourcer(_FakeStore("s-1"))
    evs = s.emit_parallel([("a", {})], tags=["grp"])
    assert evs[0].tags == ["grp"]
    assert evs[0].session_id == "s-1"


# ---------------------------------------------------------------- query

def _seed() -> EventSourcer:
    s = EventSourcer()
    s.emit("user", {"content": "one"}, tags=["chat"])
    s.emit("tool_call", {"name": "bash"}, tags=["tool"])
    s.emit("assistant", {"content": "hi"}, tags=["chat"])
    s.emit("tool_result", {"ok": True}, tags=["tool"])
    return s


def test_query_no_filter_returns_all_in_order():
    s = _seed()
    evs = s.query()
    assert [e.seq for e in evs] == [1, 2, 3, 4]


def test_query_filter_by_kind():
    s = _seed()
    evs = s.query(kind="tool_call")
    assert len(evs) == 1
    assert evs[0].kind == "tool_call"


def test_query_filter_by_tags_any_match():
    s = _seed()
    evs = s.query(tags=["tool"])
    assert len(evs) == 2
    assert all("tool" in e.tags for e in evs)


def test_query_filter_by_fork_id():
    s = _seed()
    # 默认 fork_id="" 的所有事件
    evs = s.query(fork_id="")
    assert len(evs) == 4
    # 非空 fork 无命中
    assert s.query(fork_id="fork-xyz") == []


def test_query_filter_by_since_seq_and_until_seq():
    s = _seed()
    # since_seq: seq > since_seq
    evs = s.query(since_seq=2)
    assert [e.seq for e in evs] == [3, 4]
    # until_seq: seq < until_seq
    evs = s.query(until_seq=3)
    assert [e.seq for e in evs] == [1, 2]


def test_query_filter_by_time():
    s = EventSourcer()
    s.emit("a", {})
    mid = time.time()
    s.emit("b", {})
    evs = s.query(since=mid)
    assert [e.kind for e in evs] == ["b"]
    evs = s.query(until=mid)
    assert [e.kind for e in evs] == ["a"]


def test_query_respects_limit():
    s = _seed()
    evs = s.query(limit=2)
    assert len(evs) == 2
    assert [e.seq for e in evs] == [1, 2]


# ---------------------------------------------------------------- get_event / count

def test_get_event_found_and_missing():
    s = _seed()
    ev = s.get_event(2)
    assert ev is not None
    assert ev.kind == "tool_call"
    assert s.get_event(999) is None


def test_count_all_and_by_kind():
    s = _seed()
    assert s.count() == 4
    assert s.count("user") == 1
    assert s.count("assistant") == 1
    assert s.count("nonexistent") == 0


# ---------------------------------------------------------------- fork

def test_fork_creates_point_and_records_event():
    store = _FakeStore("sess-1")
    s = EventSourcer(store)
    s.emit("user", {"content": "hi"})
    fork_id = s.fork(at_seq=1, reason="try alt")
    assert fork_id.startswith("fork-")
    fp = s.get_fork(fork_id)
    assert fp is not None
    assert fp.source_session == "sess-1"
    assert fp.at_seq == 1
    assert fp.reason == "try alt"
    # 分叉事件也被记录
    ev = s.get_event(2)
    assert ev is not None
    assert ev.kind == "session.fork"
    assert ev.parent_seq == 1
    assert ev.fork_id == fork_id
    assert ev.payload["fork_id"] == fork_id


def test_fork_without_store_empty_source():
    s = EventSourcer()
    fork_id = s.fork(at_seq=0)
    fp = s.get_fork(fork_id)
    assert fp is not None
    assert fp.source_session == ""


def test_get_fork_unknown_returns_none():
    s = EventSourcer()
    assert s.get_fork("nope") is None


def test_list_forks_returns_all():
    s = EventSourcer()
    f1 = s.fork(at_seq=0, reason="a")
    f2 = s.fork(at_seq=0, reason="b")
    forks = s.list_forks()
    assert {f.fork_id for f in forks} == {f1, f2}
    assert {f.reason for f in forks} == {"a", "b"}


# ---------------------------------------------------------------- replay

def test_replay_copies_events_after_fork():
    store = _FakeStore("src")
    target = _FakeStore("dst")
    s = EventSourcer(store)
    s.emit("user", {"content": "q"})          # seq 1
    s.emit("tool_call", {"name": "bash"})     # seq 2
    fork_id = s.fork(at_seq=2, reason="x")    # seq 3 (fork 事件)
    s.emit("assistant", {"content": "ans"})   # seq 4

    replayed = s.replay(fork_id, target)
    # 只重放 at_seq 之后、且非本 fork 的事件: seq 4
    assert [e.seq for e in replayed] == [4]
    assert len(target.records) == 1
    rec = target.records[0]
    assert rec["type"] == "assistant"
    assert rec["fork_id"] == fork_id
    assert "replayed" in rec["tags"]


def test_replay_unknown_fork_raises():
    s = EventSourcer()
    with pytest.raises(ValueError, match="未知分叉点"):
        s.replay("nope", _FakeStore())


def test_replay_with_from_to_seq_bounds():
    store = _FakeStore("src")
    s = EventSourcer(store)
    for i in range(5):
        s.emit("step", {"i": i})
    fork_id = s.fork(at_seq=0, reason="x")  # seq 6
    target = _FakeStore("dst")
    replayed = s.replay(fork_id, target, from_seq=1, to_seq=4)
    # seq 满足 1 < seq <= 4 => 2,3,4
    assert [e.seq for e in replayed] == [2, 3, 4]
    assert len(target.records) == 3


def test_replay_without_target_returns_events_only():
    store = _FakeStore("src")
    s = EventSourcer(store)
    s.emit("user", {"content": "q"})
    fork_id = s.fork(at_seq=1, reason="x")
    s.emit("assistant", {"content": "a"})
    replayed = s.replay(fork_id, None)
    assert [e.seq for e in replayed] == [3]


# ---------------------------------------------------------------- resume_from

def test_resume_from_rebuilds_messages():
    s = EventSourcer()
    s.emit("user", {"content": "hello"})
    s.emit("assistant", {"content": "world"})
    s.emit("tool_call", {"toolCallId": "tc1", "name": "bash",
                         "arguments": '{"cmd":"ls"}'})
    s.emit("tool_call_update", {"toolCallId": "tc1", "result": "ok"})
    fork_id = s.fork(at_seq=4, reason="resume")

    msgs = s.resume_from(fork_id)
    assert msgs[0] == {"role": "user", "content": "hello"}
    assert msgs[1] == {"role": "assistant", "content": "world"}
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["tool_calls"][0]["id"] == "tc1"
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "bash"
    assert msgs[2]["tool_calls"][0]["function"]["arguments"] == '{"cmd":"ls"}'
    assert msgs[3] == {"role": "tool", "content": "ok"}


def test_resume_from_respects_fork_position():
    s = EventSourcer()
    s.emit("user", {"content": "first"})
    s.emit("assistant", {"content": "second"})
    fork_id = s.fork(at_seq=1, reason="x")
    s.emit("assistant", {"content": "third"})
    msgs = s.resume_from(fork_id)
    # 只包含 seq <= at_seq(1) 的事件: 只有 user
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_resume_from_unknown_fork_raises():
    s = EventSourcer()
    with pytest.raises(ValueError, match="未知分叉点"):
        s.resume_from("nope")


# ---------------------------------------------------------------- 导出

def test_to_trajectory_returns_trajectory():
    s = EventSourcer(_FakeStore("s-1"))
    s.emit("user", {"content": "q"})
    s.emit("assistant", {"content": "a"})
    traj = s.to_trajectory()
    assert traj.session_id == "s-1"
    m = traj.metrics()
    assert m["user_turns"] == 1
    assert m["assistant_messages"] == 1


def test_export_markdown_returns_string():
    s = EventSourcer(_FakeStore("s-1"))
    s.emit("user", {"content": "q"})
    s.emit("assistant", {"content": "a"})
    md = s.export_markdown()
    assert isinstance(md, str)
    assert "# Trajectory" in md
    assert "s-1" in md


def test_export_dict_structure():
    s = EventSourcer(_FakeStore("s-1"))
    s.emit("user", {"content": "q"})
    f = s.fork(at_seq=1, reason="x")
    d = s.export_dict()
    assert d["session_id"] == "s-1"
    assert d["total_events"] == 2
    assert f in d["forks"]
    assert len(d["events"]) == 2
    assert "metrics" in d
    assert d["events"][0]["type"] == "user"


# ---------------------------------------------------------------- SourcedEvent 序列化

def test_sourced_event_to_dict_roundtrip():
    ev = SourcedEvent(
        seq=7, ts=123.45, kind="tool_call",
        payload={"name": "bash", "cmd": "ls"},
        session_id="s-1", fork_id="fork-abc", parent_seq=3,
        semantics="parallel", tags=["tool", "grp"],
    )
    d = ev.to_dict()
    # payload 字段平铺进顶层
    assert d["type"] == "tool_call"
    assert d["name"] == "bash"
    assert d["cmd"] == "ls"
    assert d["tags"] == ["tool", "grp"]
    assert d["seq"] == 7
    assert d["session_id"] == "s-1"
    assert d["fork_id"] == "fork-abc"

    ev2 = SourcedEvent.from_dict(d)
    assert ev2.seq == 7
    assert ev2.ts == 123.45
    assert ev2.kind == "tool_call"
    assert ev2.payload == {"name": "bash", "cmd": "ls"}
    assert ev2.session_id == "s-1"
    assert ev2.fork_id == "fork-abc"
    assert ev2.parent_seq == 3
    assert ev2.semantics == "parallel"
    assert ev2.tags == ["tool", "grp"]


def test_sourced_event_to_dict_no_tags_when_empty():
    ev = SourcedEvent(seq=1, ts=0.0, kind="a", payload={"x": 1})
    d = ev.to_dict()
    assert "tags" not in d


def test_sourced_event_from_dict_missing_fields_defaults():
    ev = SourcedEvent.from_dict({"type": "user", "content": "hi"})
    assert ev.seq == 0
    assert ev.kind == "user"
    assert ev.payload == {"content": "hi"}
    assert ev.session_id == ""
    assert ev.tags == []


def test_fork_point_to_dict():
    fp = ForkPoint(fork_id="fork-1", source_session="s-1",
                   at_seq=5, reason="why", created_at=9.9)
    d = fp.to_dict()
    assert d == {
        "fork_id": "fork-1", "source_session": "s-1",
        "at_seq": 5, "reason": "why", "created_at": 9.9,
    }


# ---------------------------------------------------------------- 从 store 加载

def test_load_from_store_initializes_seq_and_events():
    store = _FakeStore("s-1")
    # 预置两条记录 (模拟已有 JSONL)
    store.records = [
        {"seq": 1, "ts": 1.0, "type": "user", "content": "a", "session_id": "s-1"},
        {"seq": 2, "ts": 2.0, "type": "assistant", "content": "b", "session_id": "s-1"},
    ]
    s = EventSourcer(store)
    assert s.count() == 2
    # 下一个事件序号接续
    ev = s.emit("user", {"content": "c"})
    assert ev.seq == 3


def test_load_from_store_ignores_bad_records():
    store = _FakeStore("s-1")
    store.records = [
        {"seq": 1, "ts": 1.0, "type": "user", "content": "a"},
        "not-a-dict",  # 会触发异常, 被 except 吞掉
    ]
    s = EventSourcer(store)
    # from_dict 遇非 dict 抛错, _load_from_store 吞掉; 但第一条已加载
    assert s.count() >= 1


def test_load_from_store_read_all_raises_is_safe():
    class _BadStore:
        session_id = "s-1"

        def read_all(self):
            raise RuntimeError("boom")

    s = EventSourcer(_BadStore())
    assert s.count() == 0
