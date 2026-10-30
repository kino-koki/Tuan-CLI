"""专项测试: core.loop_provider —— 可插拔 Loop 架构。

覆盖:
  - _render_model_error (业务模板 / 普通异常回退)
  - LoopProvider 基类 (should_nudge / on_task_start / on_task_end / _tool_messages_of_turn / _maybe_override_model)
  - ReActLoop.run_loop (正常 / 模型异常 / 预算超限 / 续跑兜底 / 最大迭代 / 取消 / 技能蒸馏)
  - PlannerExecuteLoop (run_loop / _plan / _parse_plan)
  - DevLoopProvider.run_loop (包装 DevLoop)
  - LoopRegistry (register / set_current / get_current / list_available / current_name)
"""

from __future__ import annotations

import threading
import warnings
from types import SimpleNamespace
from unittest import mock

import pytest

from tuan_cli.core.loop_provider import (
    LoopProvider,
    LoopRegistry,
    ReActLoop,
    PlannerExecuteLoop,
    DevLoopProvider,
    _render_model_error,
)


# ================================================================ 辅助替身

class _FakeAuto:
    """AutoRouter 替身。"""

    def __init__(self, enabled=True, plan_execute=False, escalate=False, override=0):
        self.enabled = enabled
        self.plan_execute = plan_execute
        self.escalate = escalate
        self.override = override
        self.observed = []

    def decide_override(self, session):
        return self.override

    def observe_turn(self, session, messages):
        self.observed.append((session, messages))


class _FakeContextManager:
    def __init__(self):
        self.compacts = 0

    def needs_compact(self, messages):
        return False

    def compact_if_needed(self, messages):
        self.compacts += 1
        return messages, None


class _FakeAgent:
    """Agent 替身: 提供 ReActLoop/PlannerExecuteLoop 所需的最小接口。"""

    def __init__(self, config=None):
        self.config = config or {}
        self.turn_count = 0
        self.messages = []
        self._cancel_event = threading.Event()
        self._continue_nudges = 0
        self._awaiting_done = False
        self._auto = _FakeAuto()
        self._route_session = "sess-1"
        self.context_manager = _FakeContextManager()
        self.model = SimpleNamespace(capabilities=SimpleNamespace(vision=False))
        self._chat_calls = []
        self._chat_queue = []
        self._executed_tools = []
        self._verify_calls = []
        self._nudged = 0
        self._session_events = []
        self._maybe_routed = []
        self._notified_hooks = []
        self._cost = 0.0

    # ---- 配置键访问 (dict 兼容) ----
    def get(self, key, default=None):
        return self.config.get(key, default)

    # ---- 循环回调桩 ----
    def _estimate_total_cost(self):
        return self._cost

    def _session_append(self, event_type, **payload):
        self._session_events.append((event_type, payload))

    def _chat_with_retry(self, messages, tools=None, stream=True,
                         on_token=None, on_reason=None):
        self._chat_calls.append((list(messages), tools, stream))
        if self._chat_queue:
            return self._chat_queue.pop(0)
        raise RuntimeError("no queued chat result")

    def _schemas(self):
        return []

    def _accumulate_usage(self, usage):
        pass

    @staticmethod
    def _parse_assistant_message(result):
        # 复用 Agent 的同名静态逻辑
        if hasattr(result, "content"):
            return {
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in (result.tool_calls or [])
                ],
            }
        if isinstance(result, dict):
            message = result.get("message", result)
            return message if isinstance(message, dict) else {"role": "assistant", "content": str(message)}
        return {"role": "assistant", "content": str(result)}

    _DONE_CUES = ("完成", "done", "completed", "任务完成", "all set")
    _CONTINUE_CUES = ("接下来", "然后", "还需要", "下一步", "next", "let me", "need to")

    @classmethod
    def _looks_unfinished(cls, text):
        t = (text or "").strip().lower()
        if not t:
            return False
        return any(c in t for c in cls._CONTINUE_CUES)

    def _execute_tools(self, tool_calls, on_tool=None, on_tool_result=None):
        self._executed_tools.append(tool_calls)
        if on_tool:
            for tc in tool_calls:
                name = tc.get("function", {}).get("name", "?")
                on_tool(tc.get("id", ""), name)
        if on_tool_result:
            for tc in tool_calls:
                on_tool_result(tc.get("id", ""), "ok")

    def _run_verify_loop(self, tool_calls, on_token=None):
        self._verify_calls.append(tool_calls)

    def _nudge_round(self, on_token=None, on_reason=None, on_error=None):
        self._nudged += 1

    def _notify_hook(self, hook, payload=None):
        self._notified_hooks.append((hook, payload))

    def _maybe_route_model(self, user_input, override=0, has_images=False):
        self._maybe_routed.append((user_input, override, has_images))


def _mk_agent(config=None):
    return _FakeAgent(config or {})


def _msg(content="", tool_calls=None):
    """构造模型响应 (SimpleNamespace, 与 Agent._parse_assistant_message 契约一致)。"""
    return SimpleNamespace(content=content, tool_calls=tool_calls or [], usage=None)


# ================================================================ _render_model_error

class TestRenderModelError:
    def test_business_error_returns_friendly_template(self):
        from tuan_cli.core.errors import ModelError
        text = _render_model_error(ModelError("gpt-4"))
        assert text.startswith("❌")

    def test_generic_exception_keeps_original(self):
        text = _render_model_error(RuntimeError("boom"))
        assert text == "boom"

    def test_friendly_for_returns_none_keeps_original(self):
        # 普通异常 friendly_for 返回 None → 保留原文
        text = _render_model_error(RuntimeError("raw"))
        assert text == "raw"

    def test_friendly_for_raises_keeps_original(self):
        # friendly_for 抛异常时回退 str(exc)
        with mock.patch("tuan_cli.core.errors.friendly_for", side_effect=ValueError("x")):
            text = _render_model_error(RuntimeError("raw"))
        assert text == "raw"


# ================================================================ LoopProvider 基类

class TestLoopProviderBase:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            LoopProvider()  # abstractmethod 未实现

    def test_should_nudge_interval_hit(self):
        agent = _mk_agent({"agent.skill_nudge_interval": 3})
        agent.turn_count = 3
        assert LoopProvider.should_nudge(LoopProvider, agent) is True

    def test_should_nudge_interval_miss(self):
        agent = _mk_agent({"agent.skill_nudge_interval": 3})
        agent.turn_count = 2
        assert LoopProvider.should_nudge(LoopProvider, agent) is False

    def test_should_nudge_zero_interval_disables(self):
        agent = _mk_agent({"agent.skill_nudge_interval": 0})
        agent.turn_count = 5
        assert LoopProvider.should_nudge(LoopProvider, agent) is False

    def test_hooks_are_noop(self):
        lp = ReActLoop()
        agent = _mk_agent()
        lp.on_task_start(agent, "hi")   # 不抛
        lp.on_task_end(agent, "ok", 1)  # 不抛

    def test_tool_messages_of_turn_in_range(self):
        msgs = [{"role": "user"}, {"role": "assistant"}, {"role": "user"}]
        assert LoopProvider._tool_messages_of_turn(msgs, 1) == msgs[1:]

    def test_tool_messages_of_turn_out_of_range(self):
        msgs = [{"role": "user"}]
        assert LoopProvider._tool_messages_of_turn(msgs, 5) == []


# ================================================================ _maybe_override_model

class TestMaybeOverrideModel:
    def test_auto_disabled_skips(self):
        agent = _mk_agent()
        agent._auto = _FakeAuto(enabled=False, plan_execute=True)
        LoopProvider._maybe_override_model(agent, "hi")
        assert agent._maybe_routed == []

    def test_no_plan_or_escalate_skips(self):
        agent = _mk_agent()
        agent._auto = _FakeAuto(enabled=True, plan_execute=False, escalate=False)
        LoopProvider._maybe_override_model(agent, "hi")
        assert agent._maybe_routed == []

    def test_override_zero_skips(self):
        agent = _mk_agent()
        agent._auto = _FakeAuto(enabled=True, plan_execute=True, override=0)
        LoopProvider._maybe_override_model(agent, "hi")
        assert agent._maybe_routed == []

    def test_override_routes(self):
        agent = _mk_agent()
        agent._auto = _FakeAuto(enabled=True, plan_execute=True, override=2)
        LoopProvider._maybe_override_model(agent, "task")
        assert agent._maybe_routed == [("task", 2, False)]

    def test_override_preserves_vision(self):
        agent = _mk_agent()
        agent.model = SimpleNamespace(capabilities=SimpleNamespace(vision=True))
        agent._auto = _FakeAuto(enabled=True, escalate=True, override=1)
        LoopProvider._maybe_override_model(agent, "task")
        assert agent._maybe_routed == [("task", 1, True)]


# ================================================================ ReActLoop.run_loop

class TestReActLoop:
    def test_plain_answer_breaks_immediately(self):
        agent = _mk_agent()
        agent._chat_queue = [_msg(content="你好，已完成任务。")]
        answer = ReActLoop().run_loop(agent, "你好", max_iterations=10)
        assert answer == "你好，已完成任务。"
        assert agent.turn_count == 1

    def test_model_error_invokes_callback(self):
        agent = _mk_agent()

        def _boom(*a, **k):
            raise RuntimeError("connection reset")

        agent._chat_with_retry = _boom
        errors = []
        answer = ReActLoop().run_loop(agent, "hi", on_error=errors.append, max_iterations=5)
        assert answer == "[模型错误] connection reset"
        assert errors == ["connection reset"]

    def test_budget_exceeded_stops(self):
        agent = _mk_agent({"router.budget_limit": 0.5})
        agent._cost = 0.9
        tokens = []
        agent._chat_queue = [_msg(content="x")]
        answer = ReActLoop().run_loop(agent, "hi", on_token=tokens.append, max_iterations=5)
        assert answer == ""  # budget 分支 break, 未设 answer
        assert any("[预算已用尽]" in t for t in tokens)
        assert ("budget.exceeded", {"cost": 0.9, "budget": 0.5}) in [
            (e, p) for e, p in agent._session_events
        ]

    def test_cancel_event_breaks(self):
        agent = _mk_agent()
        agent._cancel_event.set()
        agent._chat_queue = [_msg(content="x")]
        answer = ReActLoop().run_loop(agent, "hi", max_iterations=5)
        assert answer == ""

    def test_null_result_continues(self):
        agent = _mk_agent()
        agent._chat_queue = [None, _msg(content="done")]
        answer = ReActLoop().run_loop(agent, "hi", max_iterations=5)
        assert answer == "done"

    def test_continue_nudge_injects_question(self):
        # 第一次: 有 tool 活动 + unfinished 文本 → 注入询问
        agent = _mk_agent({"fusion.continue_nudge_max": 3})
        agent.messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
        ]
        # 第一次返回 unfinished, 第二次返回 DONE
        agent._chat_queue = [
            _msg(content="接下来我会继续处理……"),
            _msg(content="DONE 全部完成"),
        ]
        answer = ReActLoop().run_loop(agent, "hi", max_iterations=10)
        assert answer == "DONE 全部完成"
        # 注入了 user 询问
        assert any(m.get("role") == "user" and "DONE" in m.get("content", "")
                   for m in agent.messages)
        assert agent._continue_nudges == 1

    def test_no_tool_activity_no_nudge(self):
        # 无 tool 活动 + unfinished → 直接 break (不注入)
        agent = _mk_agent({"fusion.continue_nudge_max": 3})
        agent._chat_queue = [_msg(content="接下来还要做…")]
        answer = ReActLoop().run_loop(agent, "hi", max_iterations=10)
        assert answer == "接下来还要做…"
        assert agent._continue_nudges == 0

    def test_awaiting_done_and_done_cue_breaks(self):
        agent = _mk_agent()
        agent._awaiting_done = True
        agent._chat_queue = [_msg(content="已完成全部。")]
        answer = ReActLoop().run_loop(agent, "hi", max_iterations=10)
        assert answer == "已完成全部。"
        assert agent._awaiting_done is False

    def test_max_iterations_reached(self):
        agent = _mk_agent()
        # result None 一直 continue → 循环自然耗尽 max_iter, answer 保持空
        agent._chat_queue = [None]
        answer = ReActLoop().run_loop(agent, "hi", max_iterations=1)
        assert answer == "(达到最大迭代次数, 已停止。)"

    def test_tool_execution_path(self):
        agent = _mk_agent()
        tc = SimpleNamespace(id="call_1", name="bash", arguments='{"cmd": "ls"}')
        agent._chat_queue = [
            _msg(content="", tool_calls=[tc]),
            _msg(content="完成。"),
        ]
        answer = ReActLoop().run_loop(agent, "hi", max_iterations=10)
        assert answer == "完成。"
        assert agent._executed_tools and agent._executed_tools[0][0]["id"] == "call_1"
        assert agent._verify_calls and agent._verify_calls[0][0]["id"] == "call_1"
        assert agent._auto.observed  # observe_turn 被调用

    def test_skill_nudge_triggered(self):
        agent = _mk_agent({"agent.skill_nudge_interval": 1})
        agent._chat_queue = [_msg(content="完成。")]
        ReActLoop().run_loop(agent, "hi", max_iterations=5)
        assert agent._nudged == 1


# ================================================================ PlannerExecuteLoop

class TestPlannerExecute:
    def test_run_loop_happy(self):
        agent = _mk_agent({"agent.max_iterations": 10})
        agent._chat_queue = [
            SimpleNamespace(content="1. 第一步\n2. 第二步"),
            _msg(content="完成第一步。"),
            _msg(content="完成第二步。"),
        ]
        answer = PlannerExecuteLoop().run_loop(agent, "任务", max_iterations=10)
        assert answer == "完成第二步。"
        # 注入步骤消息
        assert any("[步骤 1/2]" in m.get("content", "") for m in agent.messages)
        assert any("[步骤 2/2]" in m.get("content", "") for m in agent.messages)

    def test_run_loop_empty_plan_single_step(self):
        agent = _mk_agent({"agent.max_iterations": 10})
        agent._chat_queue = [
            SimpleNamespace(content="无编号说明"),
            _msg(content="完成。"),
        ]
        answer = PlannerExecuteLoop().run_loop(agent, "任务", max_iterations=10)
        assert answer == "完成。"

    def test_run_loop_step_failure(self):
        agent = _mk_agent({"agent.max_iterations": 10})
        calls = {"n": 0}

        def _chat(messages, tools=None, stream=True, on_token=None, on_reason=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return SimpleNamespace(content="1. 第一步")
            raise RuntimeError("model down")

        agent._chat_with_retry = _chat
        errors = []
        answer = PlannerExecuteLoop().run_loop(agent, "任务", on_error=errors.append, max_iterations=10)
        assert "[步骤 1 失败]" in answer
        assert errors == ["model down"]

    def test_plan_success(self):
        agent = _mk_agent()
        agent._chat_queue = [SimpleNamespace(content="1. 甲\n2. 乙")]
        plan = PlannerExecuteLoop()._plan(agent, "任务")
        assert plan == "1. 甲\n2. 乙"

    def test_plan_failure_falls_back_to_task(self):
        agent = _mk_agent()

        def _boom(*a, **k):
            raise RuntimeError("x")

        agent._chat_with_retry = _boom
        plan = PlannerExecuteLoop()._plan(agent, "原始任务")
        assert plan == "原始任务"

    def test_plan_dict_result(self):
        agent = _mk_agent()
        agent._chat_queue = [{"content": "1. 甲"}]
        plan = PlannerExecuteLoop()._plan(agent, "任务")
        assert plan == "1. 甲"

    def test_parse_plan_numbered_dot(self):
        assert PlannerExecuteLoop._parse_plan("1. 甲\n2. 乙") == ["甲", "乙"]

    def test_parse_plan_numbered_paren(self):
        assert PlannerExecuteLoop._parse_plan("1) 甲\n2) 乙") == ["甲", "乙"]

    def test_parse_plan_chinese_step(self):
        assert PlannerExecuteLoop._parse_plan("步骤1：甲\n步骤2: 乙") == ["甲", "乙"]

    def test_parse_plan_appends_continuation(self):
        assert PlannerExecuteLoop._parse_plan("1. 第一步\n补充说明") == ["第一步 补充说明"]

    def test_parse_plan_empty_falls_back_to_whole(self):
        assert PlannerExecuteLoop._parse_plan("   ") == [""]


# ================================================================ DevLoopProvider

class TestDevLoopProvider:
    def test_run_loop_wraps_devloop(self):
        agent = _mk_agent({"agent.max_iterations": 5})
        tokens = []
        with mock.patch("tuan_cli.core.devloop.DevLoop") as m_loop:
            m_loop.return_value.run.return_value = "dev answer"
            answer = DevLoopProvider().run_loop(agent, "任务", on_token=tokens.append)
        assert answer == "dev answer"
        m_loop.assert_called_once()
        # DevLoop 构造时收到 on_checkpoint 回调 (mock 不触发, 仅验证接线)
        kwargs = m_loop.call_args.kwargs
        assert callable(kwargs["on_checkpoint"])
        # 手动调用该回调可产出检查点展示
        kwargs["on_checkpoint"]("报告内容")
        assert any("--- 检查点 ---" in t for t in tokens)

    def test_name_and_description(self):
        assert DevLoopProvider.name == "devloop"
        assert "自主开发循环" in DevLoopProvider.description


# ================================================================ LoopRegistry

class TestLoopRegistry:
    def test_register_sets_first_current(self):
        reg = LoopRegistry()
        reg.register(ReActLoop())
        assert reg.current_name == "react"
        assert isinstance(reg.get_current(), ReActLoop)

    def test_register_overwrites(self):
        reg = LoopRegistry()
        reg.register(ReActLoop())
        reg.register(PlannerExecuteLoop())
        assert reg.current_name == "react"  # 首注册仍为 current

    def test_set_current_unknown_raises(self):
        reg = LoopRegistry()
        reg.register(ReActLoop())
        with pytest.raises(ValueError):
            reg.set_current("nope")

    def test_set_current_switches(self):
        reg = LoopRegistry()
        reg.register(ReActLoop())
        reg.register(PlannerExecuteLoop())
        reg.set_current("plan_execute")
        assert reg.current_name == "plan_execute"
        assert isinstance(reg.get_current(), PlannerExecuteLoop)

    def test_get_current_empty_falls_back_react(self):
        reg = LoopRegistry()
        assert isinstance(reg.get_current(), ReActLoop)

    def test_list_available(self):
        reg = LoopRegistry()
        reg.register(ReActLoop())
        reg.register(PlannerExecuteLoop())
        names = [i["name"] for i in reg.list_available()]
        assert names == ["react", "plan_execute"]
        assert all("description" in i for i in reg.list_available())

    def test_current_name_default_react(self):
        assert LoopRegistry().current_name == "react"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
