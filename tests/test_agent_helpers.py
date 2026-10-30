"""Agent 辅助功能单元测试 (core/agent_helpers.py)。

覆盖:
- summarize_messages: 上下文压缩时的结构化摘要提取;
- should_nudge / SKILL_NUDGE: 技能蒸馏 (Hermes 闭环) 触发判断;
- ChunkFlusher: 流式 token 分片合并落盘;
- estimate_total_cost / cache_hit_rate: 用量/成本估算;
- detect_verify_write_tools: 验证闭环写工具检测。
"""
from __future__ import annotations

from tuan_cli.core.agent_helpers import (
    ChunkFlusher, SKILL_NUDGE, cache_hit_rate, detect_verify_write_tools,
    estimate_total_cost, should_nudge, summarize_messages,
)


# ---------------------------------------------------------------- summarize_messages

def _msg(role, content="", tool_calls=None):
    m = {"role": role}
    if content:
        m["content"] = content
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def _tc(name, args_json):
    return {"function": {"name": name, "arguments": args_json}}


def test_summarize_extracts_goal_file_tool_conclusion():
    messages = [
        _msg("user", "修复登录页面的 bug"),
        _msg("assistant", content="开始排查", tool_calls=[
            _tc("read_file", '{"path":"src/login.py"}'),
            _tc("run_terminal_command", '{"command":"pytest tests/test_login.py"}'),
        ]),
        _msg("assistant", "问题定位到 token 校验逻辑, 已修复"),
    ]
    out = summarize_messages(messages)
    assert "修复登录页面的 bug" in out      # 用户目标
    assert "src/login.py" in out            # 涉及文件
    assert "read_file(src/login.py)" in out  # 工具操作
    assert "问题定位到 token 校验逻辑" in out  # 结论
    assert len(out) <= 500


def test_summarize_content_list_joined():
    messages = [_msg("user", ["第一段", "第二段"])]
    out = summarize_messages(messages)
    assert "第一段" in out and "第二段" in out


def test_summarize_empty_messages():
    out = summarize_messages([])
    assert out == "(无可提取的结构化信息)"


def test_summarize_invalid_json_args_ignored():
    messages = [
        _msg("assistant", content="x", tool_calls=[
            _tc("read_file", "{not json"),
            _tc("run_terminal_command", '{"command":"ls"}'),
        ]),
    ]
    out = summarize_messages(messages)
    assert "$ ls" in out           # 合法 JSON 的仍然提取
    assert "read_file" not in out  # 非法 JSON 被忽略


def test_summarize_no_structured_info_falls_back_to_flat():
    messages = [_msg("user", "hello"), _msg("assistant", "hi")]
    out = summarize_messages(messages)
    # 无目标/文件/工具/结论时回退到扁平摘要
    assert "user: hello" in out or "hello" in out


# ---------------------------------------------------------------- should_nudge

def test_should_nudge_true_at_interval():
    assert should_nudge(5, 5) is True


def test_should_nudge_false_when_not_at_interval():
    assert should_nudge(4, 5) is False


def test_should_nudge_false_when_interval_zero():
    assert should_nudge(5, 0) is False


def test_should_nudge_false_when_turn_zero():
    assert should_nudge(0, 5) is False


def test_skill_nudge_mentions_save():
    assert "skill_save" in SKILL_NUDGE


# ---------------------------------------------------------------- ChunkFlusher

def test_chunk_flusher_flushes_at_char_threshold():
    out = []
    f = ChunkFlusher(out.append, max_chars=4, max_interval=10.0)
    f.add("ab")
    assert out == []          # 未达阈值, 不落盘
    f.add("cd")
    assert out == ["abcd"]    # 达到阈值, 一次性落盘


def test_chunk_flusher_flushes_on_interval():
    out = []
    f = ChunkFlusher(out.append, max_chars=1000, max_interval=0.05)
    f.add("a")
    # 等待超过 interval 后, 下一次 add 触发落盘
    import time
    time.sleep(0.06)
    f.add("b")
    assert out == ["ab"]


def test_chunk_flusher_empty_delta_ignored():
    out = []
    f = ChunkFlusher(out.append, max_chars=2, max_interval=0.01)
    f.add("")
    assert out == []


def test_chunk_flusher_manual_flush():
    out = []
    f = ChunkFlusher(out.append, max_chars=1000, max_interval=10.0)
    f.add("hello")
    f.flush()
    assert out == ["hello"]
    f.flush()  # 再次 flush 空缓冲, 不报错
    assert out == ["hello"]


def test_chunk_flusher_sink_exception_isolated():
    def _boom(text):
        raise RuntimeError("disk full")

    f = ChunkFlusher(_boom, max_chars=1, max_interval=10.0)
    f.add("x")  # sink 抛异常 → 被隔离, 不向外抛
    assert True


def test_chunk_flusher_concatenation_preserves_order():
    out = []
    f = ChunkFlusher(out.append, max_chars=3, max_interval=10.0)
    f.add("ab")
    f.add("cd")   # 触发落盘 ["abcd"]
    f.add("ef")
    f.add("gh")   # 触发落盘 ["efgh"]
    assert out == ["abcd", "efgh"]
    assert "".join(out) == "abcdefgh"  # 回放拼接与逐 delta 一致


# ---------------------------------------------------------------- 用量/成本

def test_cache_hit_rate_computes():
    assert cache_hit_rate({"prompt_cache_hit_tokens": 3, "prompt_cache_miss_tokens": 1}) == 0.75


def test_cache_hit_rate_none_when_no_data():
    assert cache_hit_rate({}) is None
    assert cache_hit_rate({"prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}) is None


def test_estimate_total_cost_config_error_returns_zero():
    # 配置读取异常(如缺 provider/model 导致路由抛) → 函数应兜底 0.0
    class _Cfg:
        def get(self, key, default=None):
            raise RuntimeError("config missing provider/model")

    assert estimate_total_cost(_Cfg(), {"prompt_tokens": 100, "completion_tokens": 50}) == 0.0


# ---------------------------------------------------------------- 验证写工具检测

def test_detect_write_tools_true():
    calls = [{"function": {"name": "write_file"}}, {"function": {"name": "read_file"}}]
    assert detect_verify_write_tools(calls) is True


def test_detect_write_tools_false():
    calls = [{"function": {"name": "read_file"}}, {"function": {"name": "code_search"}}]
    assert detect_verify_write_tools(calls) is False


def test_detect_write_tools_edit_and_delete():
    assert detect_verify_write_tools([{"function": {"name": "edit_file"}}]) is True
    assert detect_verify_write_tools([{"function": {"name": "delete_file"}}]) is True
    assert detect_verify_write_tools([{"function": {"name": "move_file"}}]) is True


def test_detect_write_tools_empty():
    assert detect_verify_write_tools([]) is False


def test_detect_write_tools_non_dict_items_ignored():
    assert detect_verify_write_tools(["not-a-dict"]) is False
