"""Cross-Session Messaging 专项测试 —— 弃用版 core.messaging。

注意: 此模块标注 [已弃用] 指向 core.message_bus, 但代码仍被 test_new_features_v2.py
的向后兼容测试引用, 故需要覆盖其关键路径。

覆盖 tuan_cli.core.messaging:
- PeerSession.to_dict/from_dict
- CrossMessage.to_dict/from_dict
- MessageBus: register/unregister/heartbeat/list_agents/send/receive/unread_count/discard_messages/cleanup
- registry 加载/保存 (原子写)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tuan_cli.core.messaging import (
    CrossMessage,
    MessageBus,
    PeerSession,
)


# ---------------------------------------------------------------- PeerSession

def test_peer_session_to_dict_from_dict_roundtrip():
    s = PeerSession(
        session_id="s-1", name="agent1", working_dir="/ws",
        started_at=1.0, last_active=2.0, status="active",
        pid=1234, model="gpt-4o", capabilities=["read", "write"],
    )
    d = s.to_dict()
    assert d["session_id"] == "s-1"
    assert d["pid"] == 1234
    s2 = PeerSession.from_dict(d)
    assert s2.session_id == "s-1"
    assert s2.name == "agent1"
    assert s2.status == "active"
    assert s2.capabilities == ["read", "write"]


def test_peer_session_from_dict_missing_defaults():
    s = PeerSession.from_dict({})
    assert s.session_id == ""
    assert s.status == "active"
    assert s.pid == 0
    assert s.capabilities == []


# ---------------------------------------------------------------- CrossMessage

def test_cross_message_roundtrip():
    m = CrossMessage(
        message_id="m1", from_session="a", from_name="A", to_session="b",
        content="hi", timestamp=5.0, message_type="task",
        read=True, metadata={"k": "v"},
    )
    d = m.to_dict()
    assert d["message_id"] == "m1"
    assert d["message_type"] == "task"
    m2 = CrossMessage.from_dict(d)
    assert m2.message_id == "m1"
    assert m2.content == "hi"
    assert m2.read is True
    assert m2.metadata == {"k": "v"}


def test_cross_message_from_dict_defaults():
    m = CrossMessage.from_dict({})
    assert m.message_id == ""
    assert m.message_type == "text"
    assert m.read is False
    assert m.metadata == {}


# ---------------------------------------------------------------- MessageBus

def _mk_bus(tmp_path: Path) -> MessageBus:
    return MessageBus(home=tmp_path)


def test_register_creates_registry(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-1", "agent1", "/ws", pid=10, model="deepseek")
    assert "s-1" in bus._registry
    assert bus._registry["s-1"].name == "agent1"
    assert bus._registry["s-1"].pid == 10
    # registry 已落盘
    assert bus._registry_path.exists()
    data = json.loads(bus._registry_path.read_text(encoding="utf-8"))
    assert "s-1" in data


def test_register_name_falls_back_to_id_prefix(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-abcdefgh", "", "/ws")
    assert bus._registry["s-abcdefgh"].name == "s-abcdef"


def test_unregister_removes_and_cleans_queue(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-1", "a", "/ws")
    bus.send("s-2", "s-1", "hello")  # s-1 有队列
    queue = bus._messaging_dir / "s-1.jsonl"
    assert queue.exists()
    bus.unregister("s-1")
    assert "s-1" not in bus._registry
    assert not queue.exists()


def test_heartbeat_updates_last_active(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-1", "a", "/ws")
    before = bus._registry["s-1"].last_active
    time.sleep(0.01)
    bus.heartbeat("s-1")
    assert bus._registry["s-1"].last_active > before


def test_heartbeat_unknown_session_noop(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.heartbeat("nope")  # 不抛


def test_list_agents_excludes_stale_and_self(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-self", "self", "/ws")
    bus.register("s-other", "other", "/ws")
    # 模拟 s-stale 已过期
    bus.register("s-stale", "stale", "/ws")
    bus._registry["s-stale"].last_active = time.time() - 400  # >300s

    agents = bus.list_agents(include_self=False, self_id="s-self")
    ids = [s.session_id for s in agents]
    assert "s-self" not in ids
    assert "s-stale" not in ids
    assert "s-other" in ids


def test_list_agents_include_self(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-self", "self", "/ws")
    agents = bus.list_agents(include_self=True, self_id="s-self")
    assert "s-self" in [s.session_id for s in agents]


def test_send_creates_message_in_queue(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-from", "from", "/ws")
    bus.register("s-to", "to", "/ws")
    msg = bus.send("s-from", "s-to", "hello", message_type="task")
    assert msg.message_type == "task"
    assert msg.from_name == "from"
    queue = bus._messaging_dir / "s-to.jsonl"
    assert queue.exists()
    lines = queue.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["content"] == "hello"


def test_send_from_unknown_session_uses_id_prefix(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-to", "to", "/ws")
    msg = bus.send("s-unknown", "s-to", "hi")
    assert msg.from_name == "s-unknow"


def test_receive_returns_unread_and_marks_read(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-from", "from", "/ws")
    bus.register("s-to", "to", "/ws")
    bus.send("s-from", "s-to", "msg1")
    bus.send("s-from", "s-to", "msg2")

    msgs = bus.receive("s-to")
    assert len(msgs) == 2
    assert all(m.read for m in msgs)
    # 再收, 已读的不返回
    assert bus.receive("s-to") == []


def test_receive_no_queue_returns_empty(tmp_path):
    bus = _mk_bus(tmp_path)
    assert bus.receive("s-none") == []


def test_receive_mark_read_false_keeps_unread(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-from", "from", "/ws")
    bus.register("s-to", "to", "/ws")
    bus.send("s-from", "s-to", "msg1")
    msgs = bus.receive("s-to", mark_read=False)
    assert len(msgs) == 1
    # 未标记已读, 再次接收仍返回
    assert len(bus.receive("s-to")) == 1


def test_unread_count(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-from", "from", "/ws")
    bus.register("s-to", "to", "/ws")
    bus.send("s-from", "s-to", "m1")
    bus.send("s-from", "s-to", "m2")
    assert bus.unread_count("s-to") == 2
    bus.receive("s-to")
    assert bus.unread_count("s-to") == 0


def test_unread_count_no_queue_zero(tmp_path):
    bus = _mk_bus(tmp_path)
    assert bus.unread_count("s-none") == 0


def test_discard_messages(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-from", "from", "/ws")
    bus.register("s-to", "to", "/ws")
    bus.send("s-from", "s-to", "m1")
    bus.send("s-from", "s-to", "m2")
    count = bus.discard_messages("s-to")
    assert count == 2
    assert bus.unread_count("s-to") == 0


def test_discard_no_queue_zero(tmp_path):
    bus = _mk_bus(tmp_path)
    assert bus.discard_messages("s-none") == 0


def test_cleanup_removes_stale_sessions(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-keep", "keep", "/ws")
    bus.register("s-stale", "stale", "/ws")
    bus._registry["s-stale"].last_active = time.time() - 700  # >600s
    removed = bus.cleanup()
    assert removed == 1
    assert "s-stale" not in bus._registry
    assert "s-keep" in bus._registry


def test_load_registry_from_disk(tmp_path):
    bus = _mk_bus(tmp_path)
    bus.register("s-1", "a", "/ws")
    # 新建一个 bus 实例, 从磁盘加载
    bus2 = _mk_bus(tmp_path)
    assert "s-1" in bus2._registry
    assert bus2._registry["s-1"].name == "a"


def test_load_registry_corrupt_is_safe(tmp_path):
    bus = _mk_bus(tmp_path)
    bus._registry_path.write_text("{not valid json", encoding="utf-8")
    bus2 = _mk_bus(tmp_path)
    assert bus2._registry == {}
