"""tool_call 序列化合规回归测试 (OpenAI 兼容格式)。

背景: assistant 历史消息的 ``tool_calls`` 曾长期缺失 ``type="function"`` 字段,
严格 OpenAI 兼容端点 (SenseNova) 在回传多轮历史时以 400 拒绝
(``invalid tool_call type``)。属**核心序列化缺陷, 与供应商无关** —— 任何严格端点都会拒。

本文件把契约钉死:
  1. 每个 tool_call 必须含 id / type=="function" / function{name, arguments};
  2. 每条 role=tool 消息的 tool_call_id 必须能对应上某个 tool_call.id;
  3. 多轮 (5 轮 × 2~3 组) 累积历史整体合规;
  4. 适配器出口做纵深防御 (缺 type 自动补齐, 不改动已合规项, 不污染原始对象)。
"""
import json

from tuan_cli.core.agent import Agent
from tuan_cli.models.base import ModelResponse, ToolCall
from tuan_cli.models.openai_compat import OpenAICompatAdapter


def _validate(msgs):
    """按 OpenAI 兼容规范校验, 返回违规描述列表 (空 = 合规)。"""
    problems = []
    known_ids = set()
    for idx, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for j, tc in enumerate(m["tool_calls"]):
                known_ids.add(tc.get("id"))
                if not tc.get("id"):
                    problems.append(f"msg[{idx}].tool_calls[{j}] 缺 id")
                if tc.get("type") != "function":
                    problems.append(f"msg[{idx}].tool_calls[{j}] type={tc.get('type')!r} (应为 'function')")
                fn = tc.get("function")
                if not isinstance(fn, dict) or "name" not in fn or "arguments" not in fn:
                    problems.append(f"msg[{idx}].tool_calls[{j}].function 不合法: {fn!r}")
        if m.get("role") == "tool":
            if m.get("tool_call_id") not in known_ids:
                problems.append(f"msg[{idx}] role=tool 的 tool_call_id 对不上: {m.get('tool_call_id')!r}")
    return problems


def _build_history(turns=5):
    """构造 turns 轮、每轮 2~3 组 tool_call 的历史 (走真实生产函数)。"""
    msgs = [
        {"role": "system", "content": "you are a helpful agent"},
        {"role": "user", "content": "任务: 重构并测试"},
    ]
    for t in range(turns):
        n = 2 + (t % 2)  # 2 或 3
        calls = [
            ToolCall(id=f"call_{t}_{i}", name=f"tool_{i}",
                     arguments=json.dumps({"i": i}, ensure_ascii=False))
            for i in range(n)
        ]
        am = Agent._parse_assistant_message(ModelResponse(content="", tool_calls=calls))
        msgs.append(am)
        for tc in am["tool_calls"]:
            msgs.append({
                "role": "tool", "tool_call_id": tc["id"],
                "name": tc["function"]["name"], "content": "ok", "status": "ok",
            })
    return msgs


# ---------------------------------------------------------------- 1. 生产函数
def test_parse_assistant_message_includes_type_function():
    """核心修复点: tool_call 必须带 type='function'。"""
    resp = ModelResponse(content="", tool_calls=[ToolCall(id="c1", name="shell", arguments="{}")])
    msg = Agent._parse_assistant_message(resp)
    assert msg["tool_calls"][0]["type"] == "function"
    assert set(msg["tool_calls"][0]) >= {"id", "type", "function"}


# ---------------------------------------------------------------- 2. 多轮累积
def test_five_turn_history_is_openai_conformant():
    """5 轮 × 2~3 组 tool_call 的累积历史必须整体合规 (这就是线上炸的那份 payload)。"""
    msgs = _build_history(turns=5)
    assert _validate(msgs) == []
    groups = sum(len(m.get("tool_calls", [])) for m in msgs)
    assert groups == 2 + 3 + 2 + 3 + 2  # 12 组


def test_tool_message_ids_align_with_tool_calls():
    msgs = _build_history(turns=5)
    ids = {tc["id"] for m in msgs if m.get("tool_calls") for tc in m["tool_calls"]}
    tool_ids = {m["tool_call_id"] for m in msgs if m.get("role") == "tool"}
    assert tool_ids == ids
    assert len(tool_ids) == 12


# ---------------------------------------------------------------- 3. 纵深防御
def test_adapter_normalizes_missing_type():
    """适配器出口应自动补齐缺 type 的 tool_call (防未来新增构造点遗漏)。"""
    msgs = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    out = OpenAICompatAdapter._ensure_tool_call_types(msgs)
    assert out[0]["tool_calls"][0]["type"] == "function"
    assert _validate(out) == []
    # 不污染调用方持有的原始对象 (会话历史需保持原身份)
    assert "type" not in msgs[0]["tool_calls"][0]


def test_adapter_normalizer_is_idempotent_and_non_copying():
    msgs = _build_history(turns=2)
    out = OpenAICompatAdapter._ensure_tool_call_types(msgs)
    # 已合规 -> 原对象直接返回, 不做无谓复制
    assert out is msgs


def test_adapter_normalizer_handles_no_tool_calls():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert OpenAICompatAdapter._ensure_tool_call_types(msgs) is msgs


# ---------------------------------------------------------------- 4. 事件溯源路径
def test_event_sourcer_tool_call_has_type():
    """event_sourcer 重建历史时同样必须带 type (第二条构造路径)。"""
    import inspect

    from tuan_cli.core import event_sourcer

    src = inspect.getsource(event_sourcer)
    # 定位 tool_call 重建片段, 断言其中包含 type: "function"
    assert '"tool_calls": [{' in src
    seg = src.split('"tool_calls": [{', 1)[1][:200]
    assert '"type": "function"' in seg, "event_sourcer 重建的 tool_call 缺 type"
