"""CollaborationProtocol 协作消息协议测试 (能力10 Agent Teams 编排协议)。

审计发现缺口: collaboration_protocol.py 定义了结构化消息 (类型/优先级/CAS/冲突/
订阅) 并经 CollaborationPlugin 注册为内核服务, 但全仓库零直接测试 —— 这套
"编排协议"是否真的能在多 Agent 间流转消息、检测冲突、支持 CAS 从未被证明。

本测试证明协议真实生效:
- 写入带版本号递增, 消息历史按类型/发送者可追溯;
- 不同发送者对同一 key 写入不同值 → 自动记录冲突;
- compare_and_swap 版本号不匹配时拒绝写入 (并发安全);
- subscribe 在写入时收到通知;
- auto_resolve_conflicts 能消解未决冲突并回写最终值。
"""

from __future__ import annotations

from tuan_cli.core.collaboration_protocol import (
    CollabMessage,
    CollaborationProtocol,
    MessagePriority,
    MessageType,
)


# ------------------------------------------------------------------ 写入与版本

def test_write_assigns_monotonic_version():
    proto = CollaborationProtocol()
    m1 = proto.write("art:T1", "方案A", sender="architect")
    m2 = proto.write("art:T1", "方案B-修订", sender="architect")
    assert m1.version == 1
    assert m2.version == 2
    assert proto.read_version("art:T1") == 2


def test_messages_typed_and_queryable():
    proto = CollaborationProtocol()
    proto.write("res:T1", "审查通过", sender="reviewer", msg_type=MessageType.RESULT)
    proto.write("fb:T1", "建议改名", sender="reviewer", msg_type=MessageType.FEEDBACK)
    # 按类型过滤
    results = proto.get_messages(msg_type=MessageType.RESULT)
    types = {m.msg_type for m in results}
    assert MessageType.RESULT in types
    assert MessageType.FEEDBACK not in types
    # 按发送者过滤
    by_reviewer = proto.get_messages(sender="reviewer")
    assert all(m.sender == "reviewer" for m in by_reviewer)


def test_message_carries_priority_and_key():
    proto = CollaborationProtocol()
    m = proto.write("urgent:T9", "线上故障", sender="ops",
                    msg_type=MessageType.ERROR, priority=MessagePriority.URGENT)
    assert m.msg_type == MessageType.ERROR
    assert m.priority == MessagePriority.URGENT
    assert m.key == "urgent:T9"
    d = m.to_dict()
    assert d["priority"] == "urgent" and d["msg_type"] == "error"


# ------------------------------------------------------------------ 冲突检测

def test_conflict_detected_on_different_values():
    proto = CollaborationProtocol()
    proto.write("design:api", "REST 风格", sender="architect-a")
    # 另一 agent 对同一 key 写入不同值 → 应记录冲突
    proto.write("design:api", "gRPC 风格", sender="architect-b")
    conflicts = proto.get_unresolved_conflicts()
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.key == "design:api"
    assert c.sender_a == "architect-a"
    assert c.sender_b == "architect-b"


def test_no_conflict_on_same_value():
    proto = CollaborationProtocol()
    proto.write("doc:T1", "正文内容", sender="writer-a")
    proto.write("doc:T1", "正文内容", sender="writer-b")  # 值相同 → 不冲突
    assert proto.get_unresolved_conflicts() == []


# ------------------------------------------------------------------ CAS

def test_compare_and_swap_version_guard():
    proto = CollaborationProtocol()
    proto.write("shared:x", "v1", sender="a")  # version=1
    # 期望版本 1 → 成功
    assert proto.compare_and_swap("shared:x", 1, "v2", sender="a") is True
    assert proto.read("shared:x") == "v2"
    # 期望版本还是 1 (实际已是 2) → 失败, 不写入
    assert proto.compare_and_swap("shared:x", 1, "v3", sender="a") is False
    assert proto.read("shared:x") == "v2"


# ------------------------------------------------------------------ 订阅

def test_subscriber_notified_on_write():
    proto = CollaborationProtocol()
    received = []
    proto.subscribe("res:T1", lambda key, val: received.append((key, val)))
    proto.write("res:T1", "结果文本", sender="worker")
    assert received == [("res:T1", "结果文本")]


# ------------------------------------------------------------------ 冲突消解

def test_auto_resolve_conflicts_writes_final_value():
    proto = CollaborationProtocol()
    proto.write("calc:total", "100", sender="worker-1")
    proto.write("calc:total", "120", sender="worker-2")  # 冲突
    assert len(proto.get_unresolved_conflicts()) == 1
    n = proto.auto_resolve_conflicts("last_write")
    assert n == 1
    # 后写者的值被采纳
    assert proto.read("calc:total") == "120"
    assert proto.get_unresolved_conflicts() == []


# ------------------------------------------------------------------ 统计/上下文

def test_stats_and_context_block():
    proto = CollaborationProtocol()
    proto.write("a", "1", sender="x")
    proto.write("b", "2", sender="y")
    st = proto.stats()
    assert st["keys"] == 2
    assert st["messages"] >= 2
    block = proto.context_block()
    assert "a" in block and "b" in block
