"""测试 event_protocol —— Agent 事件协议 (统一 CLI/TUI/ACP 事件词汇)。

覆盖:
  - AgentEvent 常量 (str 子类, 字符串比较)
  - canonicalize (别名映射 / 未知原样)
  - normalize_record (type 规整 / tool_result 折叠 toolCallId)
  - 各工具构造器: session_update / task_update / tool_call / tool_call_update / agent_message_chunk
"""

from __future__ import annotations

import pytest

from tuan_cli.core.event_protocol import (
    AgentEvent,
    canonicalize,
    normalize_record,
    session_update,
    task_update,
    tool_call,
    tool_call_update,
    agent_message_chunk,
)


class TestAgentEvent:
    def test_str_subclass(self):
        # AgentEvent 是 str 子类, 可直接当字符串用
        assert AgentEvent.SESSION_UPDATE == "session.update"
        assert isinstance(AgentEvent.SESSION_UPDATE, str)
        assert AgentEvent.SESSION_UPDATE == str(AgentEvent.SESSION_UPDATE)

    def test_constants(self):
        assert AgentEvent.USER == "user"
        assert AgentEvent.ASSISTANT == "assistant"
        assert AgentEvent.TOOL_CALL == "tool_call"
        assert AgentEvent.TOOL_CALL_UPDATE == "tool_call_update"
        assert AgentEvent.TOOL_RESULT == "tool_result"
        assert AgentEvent.USAGE == "usage"
        assert AgentEvent.BACKGROUND_JOB_START == "job.start"
        assert AgentEvent.GOAL_ACHIEVED == "goal.achieved"
        assert AgentEvent.BUDGET_EXCEEDED == "budget.exceeded"

    def test_agent_event_equality_with_plain_str(self):
        assert AgentEvent.TOOL_CALL_UPDATE == "tool_call_update"
        assert "tool_call_update" == AgentEvent.TOOL_CALL_UPDATE


class TestCanonicalize:
    def test_legacy_alias_tool_result(self):
        assert canonicalize("tool_result") == AgentEvent.TOOL_CALL_UPDATE

    def test_legacy_alias_usage(self):
        assert canonicalize("usage") == AgentEvent.USAGE

    def test_already_canonical(self):
        assert canonicalize("tool_call_update") == "tool_call_update"
        assert canonicalize("session.update") == "session.update"

    def test_unknown_passthrough(self):
        # 未知类型原样返回, 向前兼容
        assert canonicalize("custom.event") == "custom.event"
        assert canonicalize("") == ""


class TestNormalizeRecord:
    def test_type_canonicalized(self):
        r = normalize_record({"type": "tool_result", "name": "read", "result": "x"})
        assert r["type"] == AgentEvent.TOOL_CALL_UPDATE
        assert r["name"] == "read"
        assert r["result"] == "x"

    def test_tool_result_folds_tool_call_id(self):
        # 历史 tool_result 有 tool_call_id, 规整为 toolCallId
        r = normalize_record({"type": "tool_result", "name": "read",
                              "tool_call_id": "call-1", "result": "x"})
        assert r["type"] == AgentEvent.TOOL_CALL_UPDATE
        assert r["toolCallId"] == "call-1"

    def test_canonical_not_duplicated(self):
        r = normalize_record({"type": "tool_call_update", "toolCallId": "c1"})
        assert r["type"] == "tool_call_update"
        assert r["toolCallId"] == "c1"

    def test_original_not_mutated(self):
        src = {"type": "tool_result", "name": "read", "result": "x"}
        normalize_record(src)
        assert src["type"] == "tool_result"  # 原 dict 不变

    def test_custom_passthrough(self):
        r = normalize_record({"type": "custom.event", "k": 1})
        assert r["type"] == "custom.event"
        assert r["k"] == 1


class TestConstructors:
    def test_session_update(self):
        r = session_update("initialized")
        assert r == {"type": "session.update", "status": "initialized"}

    def test_session_update_extra(self):
        r = session_update("compact", session_id="s1")
        assert r["status"] == "compact"
        assert r["session_id"] == "s1"

    def test_task_update(self):
        r = task_update("running", task_id="t1")
        assert r == {"type": "task.update", "status": "running", "task_id": "t1"}

    def test_tool_call(self):
        r = tool_call("read", "{\"a\":1}", "call-9")
        assert r == {"type": "tool_call", "name": "read",
                     "arguments": "{\"a\":1}", "toolCallId": "call-9"}

    def test_tool_call_defaults(self):
        r = tool_call("ls")
        assert r == {"type": "tool_call", "name": "ls",
                     "arguments": "", "toolCallId": ""}

    def test_tool_call_update(self):
        r = tool_call_update("call-1", "completed", "output", "read")
        assert r == {"type": "tool_call_update", "toolCallId": "call-1",
                     "status": "completed", "result": "output", "name": "read"}

    def test_tool_call_update_defaults(self):
        r = tool_call_update("call-1")
        assert r == {"type": "tool_call_update", "toolCallId": "call-1",
                     "status": "completed", "result": "", "name": ""}

    def test_agent_message_chunk(self):
        r = agent_message_chunk("hello")
        assert r == {"type": "agent_message_chunk", "text": "hello"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
