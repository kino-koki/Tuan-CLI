"""MessageBus 单元测试 —— 跨会话消息总线。

覆盖 `core/message_bus.py` 的:
- register / heartbeat / unregister
- send / receive (读取 / 标记已读 / 过期丢弃 / 已读跳过 / 坏行容错)
- list_agents (存活 / 过期清理 / include_self)
- cleanup (死会话清理)
- BusMessage 默认字段
- 全局单例 get_message_bus
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tuan_cli.core.message_bus import (
    BusMessage,
    MessageBus,
    _DEFAULT_TTL,
    _SESSION_STALE,
    get_message_bus,
)


def _mk_bus(tmp_path: Path, ttl: float = 300) -> MessageBus:
    home = tmp_path / "home"
    return MessageBus(home=home, ttl=ttl)


# ============================================================ BusMessage

def test_bus_message_defaults():
    m = BusMessage()
    assert m.id and len(m.id) == 12
    assert m.from_session == ""
    assert m.to_session == ""
    assert m.content == ""
    assert m.ttl == _DEFAULT_TTL
    assert m.read is False
    assert m.ts > 0


def test_bus_message_explicit():
    m = BusMessage(id="abc", from_session="s1", to_session="s2",
                   content="hi", ttl=10, read=True)
    assert m.id == "abc"
    assert m.from_session == "s1"
    assert m.to_session == "s2"
    assert m.content == "hi"
    assert m.ttl == 10
    assert m.read is True


# ============================================================ register / heartbeat / unregister

def test_register_creates_registry_file(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-1", meta={"model": "claude"})
    reg = bus._registry_dir / "sess-1.json"
    assert reg.exists()
    info = json.loads(reg.read_text(encoding="utf-8"))
    assert info["session_id"] == "sess-1"
    assert info["meta"]["model"] == "claude"
    assert info["pid"] > 0
    assert info["last_heartbeat"] > 0


def test_heartbeat_updates_timestamp(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-1")
    reg = bus._registry_dir / "sess-1.json"
    old = json.loads(reg.read_text(encoding="utf-8"))["last_heartbeat"]
    time.sleep(0.01)
    bus.heartbeat("sess-1")
    new = json.loads(reg.read_text(encoding="utf-8"))["last_heartbeat"]
    assert new >= old


def test_heartbeat_missing_session_noop(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.heartbeat("ghost")  # 不抛异常
    assert not (bus._registry_dir / "ghost.json").exists()


def test_unregister_removes_registry(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-1")
    bus.unregister("sess-1")
    assert not (bus._registry_dir / "sess-1.json").exists()
    bus.unregister("ghost")  # 不抛异常


# ============================================================ send / receive

def test_send_writes_jsonl(tmp_path):
    bus = _mk_bus(tmp_path)
    mid = bus.send("s1", "s2", "hello")
    assert mid
    inbox = bus._inbox_dir / "s2.jsonl"
    assert inbox.exists()
    line = inbox.read_text(encoding="utf-8").strip().splitlines()[0]
    entry = json.loads(line)
    assert entry["id"] == mid
    assert entry["from"] == "s1"
    assert entry["content"] == "hello"
    assert entry["read"] is False


def test_send_receive_roundtrip(tmp_path):
    bus = _mk_bus(tmp_path)
    mid = bus.send("s1", "s2", "ping")
    msgs = bus.receive("s2")
    assert len(msgs) == 1
    assert msgs[0].id == mid
    assert msgs[0].from_session == "s1"
    assert msgs[0].to_session == "s2"
    assert msgs[0].content == "ping"


def test_receive_marks_read_and_clears(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.send("s1", "s2", "first")
    msgs = bus.receive("s2")
    assert len(msgs) == 1
    # 再次接收: 已读消息不再返回
    msgs2 = bus.receive("s2")
    assert msgs2 == []


def test_receive_mark_read_false_keeps(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.send("s1", "s2", "keep")
    msgs = bus.receive("s2", mark_read=False)
    assert len(msgs) == 1
    # 不标记已读, 仍能再次读取
    msgs2 = bus.receive("s2", mark_read=False)
    assert len(msgs2) == 1


def test_receive_empty_inbox(tmp_path):
    bus = _mk_bus(tmp_path)
    assert bus.receive("no-such-session") == []


def test_receive_expired_message_dropped(tmp_path, monkeypatch):
    bus = _mk_bus(tmp_path, ttl=1)
    bus.send("s1", "s2", "stale")
    # 模拟时间前进
    inbox = bus._inbox_dir / "s2.jsonl"
    entry = json.loads(inbox.read_text(encoding="utf-8").strip())
    entry["ts"] = time.time() - 100
    inbox.write_text(json.dumps(entry), encoding="utf-8")
    msgs = bus.receive("s2")
    assert msgs == []


def test_receive_corrupt_line_skipped(tmp_path):
    bus = _mk_bus(tmp_path)
    inbox = bus._inbox_dir / "s2.jsonl"
    inbox.write_text("{bad json}\n", encoding="utf-8")
    bus.send("s1", "s2", "ok")
    msgs = bus.receive("s2")
    assert len(msgs) == 1
    assert msgs[0].content == "ok"


def test_receive_partitioned_by_session(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.send("s1", "s2", "to-s2")
    bus.send("s1", "s3", "to-s3")
    assert len(bus.receive("s2")) == 1
    assert len(bus.receive("s3")) == 1
    assert bus.receive("s2") == []


# ============================================================ list_agents

def test_list_agents_includes_live(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-a", meta={"model": "x"})
    agents = bus.list_agents()
    assert any(a["session_id"] == "sess-a" for a in agents)
    a = next(x for x in agents if x["session_id"] == "sess-a")
    assert a["pid"] > 0
    assert a["meta"]["model"] == "x"
    assert a["uptime"] >= 0


def test_list_agents_exclude_self(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-a")
    bus.register("sess-b")
    agents = bus.list_agents(include_self=False, session_id="sess-a")
    ids = [a["session_id"] for a in agents]
    assert "sess-a" not in ids
    assert "sess-b" in ids


def test_list_agents_cleans_stale(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-old")
    reg = bus._registry_dir / "sess-old.json"
    info = json.loads(reg.read_text(encoding="utf-8"))
    info["last_heartbeat"] = time.time() - _SESSION_STALE - 10
    reg.write_text(json.dumps(info), encoding="utf-8")
    agents = bus.list_agents()
    assert not any(a["session_id"] == "sess-old" for a in agents)
    assert not reg.exists()


def test_list_agents_corrupt_registry_skipped(tmp_path):
    bus = _mk_bus(tmp_path)
    (bus._registry_dir / "bad.json").write_text("{not json}", encoding="utf-8")
    bus.register("sess-good")
    agents = bus.list_agents()
    assert any(a["session_id"] == "sess-good" for a in agents)


# ============================================================ cleanup

def test_cleanup_removes_dead_sessions(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-dead")
    reg = bus._registry_dir / "sess-dead.json"
    info = json.loads(reg.read_text(encoding="utf-8"))
    info["last_heartbeat"] = time.time() - _SESSION_STALE * 2 - 10
    reg.write_text(json.dumps(info), encoding="utf-8")
    n = bus.cleanup()
    assert n >= 1
    assert not reg.exists()


def test_cleanup_keeps_live_sessions(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("sess-live")
    n = bus.cleanup()
    assert n == 0
    assert (bus._registry_dir / "sess-live.json").exists()


# ============================================================ 全局单例

def test_get_message_bus_singleton(tmp_path):
    bus = get_message_bus()
    assert bus is get_message_bus()
    # home 默认来自 home_dir(), 不应为 None
    assert bus._home is not None
