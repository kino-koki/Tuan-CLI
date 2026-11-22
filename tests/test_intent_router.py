"""意图路由 (Intent Router) 测试 —— 每轮用户输入分类 + 路由到提示档/工具暴露。

覆盖:
- 四类意图的正例 / 反例 (code_task / question / command / chat)。
- 边界: 空输入、超长输入、混合信号 (命令词开头 + 编辑动词 + 文件路径)、疑问词但含编辑动词。
- 路由决策字段 (prompt_tier / expose_tools / max_tool_rounds) 的语义。
- 记忆化: 同一输入多次调用直接命中缓存 (lru_cache), 跨文本/窗口参数才重新分类。
- 性能: 单次分类 < 5ms (启发式硬约束)。
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.core.intent_router import (
    Intent,
    RouteDecision,
    classify_intent,
    clear_cache,
    route,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前后清缓存, 避免跨用例串扰 (lru_cache 是进程级共享状态)。"""
    clear_cache()
    yield
    clear_cache()


# ============================================================ 1. code_task

class TestCodeTask:
    def test_explicit_edit_with_file_path(self):
        assert classify_intent("把 utils.py 里的 parse_date 函数改成支持时区") is Intent.CODE_TASK
        assert classify_intent("edit src/main.py to add error handling") is Intent.CODE_TASK

    def test_english_edit_verbs(self):
        for verb in ("refactor", "implement", "fix", "add", "remove", "rewrite"):
            text = f"{verb} the parse function in module.py"
            assert classify_intent(text) is Intent.CODE_TASK, text

    def test_chinese_edit_verbs(self):
        for verb in ("重构", "实现", "修复", "添加", "删除", "优化"):
            text = f"{verb} core/agent.py 中的 _build_system 函数"
            assert classify_intent(text) is Intent.CODE_TASK, text

    def test_edit_verb_with_code_marker_no_path(self):
        """没显式给路径但提到了 function/class/def 等代码标识 → 视为编码任务。"""
        assert classify_intent("please fix the parse_function that returns wrong dates") \
            is Intent.CODE_TASK
        assert classify_intent("帮我修一下这个 function, 它总是返回 None") is Intent.CODE_TASK

    def test_long_edit_without_path_is_still_code_task(self):
        """长输入 + 编辑动词即使没路径, 也按完整任务处理 (后续轮次会指明)。"""
        text = (
            "please refactor the whole authentication flow to use OAuth2 "
            "instead of basic auth, also add proper error handling and logging"
        )
        assert classify_intent(text) is Intent.CODE_TASK

    def test_route_code_task_exposes_tools(self):
        d = route("修复 utils.py 里的日期解析 bug")
        assert d.intent is Intent.CODE_TASK
        assert d.expose_tools is True          # 安全底线
        assert d.max_tool_rounds >= 5
        assert d.prompt_tier in ("COMPACT", "FULL")

    def test_route_code_task_compact_vs_full(self):
        """短小任务 COMPACT, 超长任务 / 大上下文模型 FULL。"""
        d_short = route("fix bug in main.py")
        assert d_short.prompt_tier == "COMPACT"
        d_long = route("refactor " + "the whole module " * 30)
        assert d_long.prompt_tier == "FULL"
        d_big_window = route("fix bug in main.py", context_window=200_000)
        assert d_big_window.prompt_tier == "FULL"

    def test_route_never_degrades_tools_for_code_task(self):
        """安全约束: CODE_TASK 无论输入多短/多简单都必须暴露工具。"""
        for text in ("fix bug", "edit a.py", "改一下"):
            d = route(text)
            if d.intent is Intent.CODE_TASK:
                assert d.expose_tools is True


# ============================================================ 2. question

class TestQuestion:
    def test_wh_questions(self):
        for q in ("How do I parse a date in Python?",
                  "Why is the sky blue?",
                  "What is a context manager?",
                  "When should I use asyncio?"):
            assert classify_intent(q) is Intent.QUESTION, q

    def test_chinese_questions(self):
        for q in ("什么是指针?",
                  "为什么需要虚拟环境?",
                  "怎么在 Python 里读 YAML?",
                  "如何写出高效的递归?",
                  "请问 list 和 tuple 的区别是什么?"):
            assert classify_intent(q) is Intent.QUESTION, q

    def test_question_tail_punctuation(self):
        assert classify_intent("list 和 tuple 有什么区别?") is Intent.QUESTION
        assert classify_intent("Is Python 3.12 stable?") is Intent.QUESTION

    def test_route_question_skips_tools(self):
        """答疑默认不暴露文件编辑工具 (省 token + 降低误操作面)。"""
        d = route("什么是闭包?")
        assert d.intent is Intent.QUESTION
        assert d.expose_tools is False
        assert d.max_tool_rounds == 0
        assert d.prompt_tier == "MINI"


# ============================================================ 3. command

class TestCommand:
    def test_short_shell_commands(self):
        for c in ("git status",
                  "ls -la",
                  "pwd",
                  "docker ps",
                  "pip install requests",
                  "npm run test",
                  "cat README.md",
                  "cd src"):
            assert classify_intent(c) is Intent.COMMAND, c

    def test_chinese_simple_action(self):
        """show/open/run/list 这类简单动词 + 短输入 → COMMAND。"""
        for c in ("show README.md", "open src/main.py", "run tests",
                  "list files in current directory", "cat main.py"):
            assert classify_intent(c) is Intent.COMMAND, c

    def test_long_command_head_is_not_command(self):
        """超过 50 字符, 即使以命令词开头也升级为 question/code_task。"""
        long_q = "git: how do I revert a merge commit on branch foo without losing my changes"
        assert len(long_q) > 50
        assert classify_intent(long_q) is not Intent.COMMAND

    def test_route_command_minimal_rounds(self):
        d = route("git status")
        assert d.intent is Intent.COMMAND
        assert d.expose_tools is True   # 需要跑 shell 命令
        assert d.max_tool_rounds <= 5   # 简单动作, 不应长时间循环
        assert d.prompt_tier == "MINI"


# ============================================================ 4. chat

class TestChat:
    def test_short_conversational(self):
        for c in ("谢谢!",
                  "辛苦了",
                  "你好",
                  "嗯, 明白了",
                  "Good job!",
                  "thanks",
                  "ok",
                  "继续"):
            assert classify_intent(c) is Intent.CHAT, c

    def test_empty_input_defaults_to_chat(self):
        assert classify_intent("") is Intent.CHAT
        assert classify_intent("   ") is Intent.CHAT

    def test_route_chat_no_tools(self):
        d = route("谢谢你, 辛苦了!")
        assert d.intent is Intent.CHAT
        assert d.expose_tools is False
        assert d.max_tool_rounds == 0
        assert d.prompt_tier == "MINI"


# ============================================================ 5. 边界 / 混合信号

class TestEdgeCases:
    def test_command_head_with_edit_verb_and_path_upgrades_to_code_task(self):
        """短输入但明显是「跑命令改文件」: 命令词开头 + 编辑动词 + 路径 → CODE_TASK。"""
        text = "git mv utils.py core/utils.py"
        assert classify_intent(text) is Intent.CODE_TASK

    def test_question_with_edit_verb_stays_code_task(self):
        """疑问句式但含明确编辑动词 + 路径 → 优先 CODE_TASK (用户其实是想动手)。"""
        text = "how do I fix the bug in main.py?"
        assert classify_intent(text) is Intent.CODE_TASK

    def test_very_long_input_is_never_chat(self):
        """超长输入不论关键词都不要降级到 CHAT (避免吞掉真实任务)。"""
        long_text = "hello " * 200
        assert classify_intent(long_text) is not Intent.CHAT

    def test_very_long_input_with_edit_verb(self):
        long_task = ("please refactor the auth module and extract a "
                     "TokenProvider interface, also write unit tests "
                     "covering expiry and refresh flows " + "with detailed logs " * 20)
        d = route(long_task)
        assert d.intent is Intent.CODE_TASK
        assert d.prompt_tier == "FULL"      # 长任务倾向 FULL

    def test_mixed_signals_prefer_code_task(self):
        """命令词 + 疑问词 + 编辑动词 + 路径 同时出现 → CODE_TASK 兜底 (安全侧)。"""
        text = "fix the broken import in src/app.py, what's the fastest way?"
        assert classify_intent(text) is Intent.CODE_TASK

    def test_unicode_only_input(self):
        assert classify_intent("你好") is Intent.CHAT
        assert classify_intent("修一下 main.py 里的 bug") is Intent.CODE_TASK

    def test_file_extension_regex_coverage(self):
        """常见扩展名都能识别为文件路径信号。"""
        for path in ("main.py", "app.js", "config.yaml", "script.sh",
                     "server.rs", "lib.go", "index.html", "style.css"):
            text = f"please edit {path} to add logging"
            assert classify_intent(text) is Intent.CODE_TASK, path


# ============================================================ 6. 路由决策 & 记忆化

class TestRouteDecision:
    def test_frozen_dataclass_is_immutable(self):
        d = route("git status")
        with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError 不直接 import
            d.intent = Intent.CHAT  # type: ignore[misc]

    def test_task_hash_is_stable_for_same_input(self):
        a = route("fix bug in main.py")
        b = route("fix bug in main.py")
        assert a.task_hash == b.task_hash
        assert len(a.task_hash) == 12

    def test_task_hash_differs_for_different_input(self):
        a = route("fix bug in main.py")
        b = route("fix bug in utils.py")
        assert a.task_hash != b.task_hash

    def test_memoization_returns_cached_decision(self):
        first = route("fix bug in main.py")
        second = route("fix bug in main.py")
        assert first is second  # lru_cache 命中同一对象

    def test_memoization_keyed_by_both_text_and_window(self):
        a = route("fix bug in main.py", context_window=0)
        b = route("fix bug in main.py", context_window=200_000)
        # 不同窗口 → 不同缓存键 → prompt_tier 可能不同 (CODE_TASK 在大窗口下升级 FULL)
        assert a is not b
        assert b.prompt_tier == "FULL"

    def test_classify_intent_is_memoized(self):
        a = classify_intent("fix bug in main.py")
        b = classify_intent("fix bug in main.py")
        assert a is b  # 同一 Intent 枚举单例


# ============================================================ 7. 性能

class TestPerformance:
    def test_classify_is_under_5ms(self):
        """单次分类必须 < 5ms (硬约束, 纯启发式无 ML 调用)。"""
        samples = [
            "fix the bug in main.py",
            "什么是闭包?",
            "git status",
            "谢谢!",
            "refactor the auth module and extract a TokenProvider interface",
        ]
        for text in samples:
            clear_cache()
            start = time.perf_counter()
            classify_intent(text)
            elapsed_ms = (time.perf_counter() - start) * 1000
            assert elapsed_ms < 5.0, f"{text!r} 花了 {elapsed_ms:.3f}ms"

    def test_1000_distinct_inputs_under_budget(self):
        """1000 条不同输入分类总耗时应在合理量级 (避免意外走了慢路径)。"""
        clear_cache()
        start = time.perf_counter()
        for i in range(1000):
            classify_intent(f"fix bug number {i} in main.py")
        elapsed_ms = (time.perf_counter() - start) * 1000
        # 启发式应远低于 1ms/条; 这里给 3ms/条作为宽裕上限
        assert elapsed_ms < 3000


# ============================================================ 8. 集成 (agent_prompt)

class TestAgentPromptIntegration:
    """_build_system 在用户输入存在时应用意图路由覆盖。"""

    @staticmethod
    def _make_agent(tmp_path, tuan_home, **model):
        from tuan_cli.app import build_kernel
        from tuan_cli.core.agent import Agent
        from tuan_cli.models.base import ModelAdapter, ModelResponse

        kernel = build_kernel()
        config = kernel.require("config")
        for key, value in model.items():
            config.set_user(f"model.{key}", value)

        class M(ModelAdapter):
            name = "m"
            def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
                return ModelResponse(content="ok")

        kernel.unprovide("model_adapter")
        kernel.provide("model_adapter", M(), owner="test")
        return Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                     confirm=lambda _p: True)

    def test_no_user_input_keeps_default_tier(self, tmp_path, tuan_home):
        """首帧/后台补建系统提示时无用户输入, 意图路由不介入 (保持既有 _soul_tier)。"""
        agent = self._make_agent(tmp_path, tuan_home, provider="anthropic",
                                 model="claude-fable-5", context_window=1_000_000)
        agent.config.set_user("prompt.tier", "full")
        agent._soul_tier = "full"
        agent._last_user_input = ""
        prompt = agent._build_system()
        assert prompt.splitlines()[0].startswith("# SOUL_FULL.md")
        assert agent._intent_route is None

    def test_question_overrides_to_compact(self, tmp_path, tuan_home):
        """QUESTION 意图把 SOUL 档位压到 compact (省 token)。"""
        agent = self._make_agent(tmp_path, tuan_home, provider="anthropic",
                                 model="claude-fable-5", context_window=1_000_000)
        agent.config.set_user("prompt.tier", "full")
        agent._soul_tier = "full"
        agent._last_user_input = "什么是闭包?"
        prompt = agent._build_system()
        assert prompt.splitlines()[0].startswith("# SOUL_COMPACT.md")
        assert agent._intent_route is not None
        assert agent._intent_route.intent is Intent.QUESTION

    def test_code_task_preserves_full_for_big_model(self, tmp_path, tuan_home):
        """CODE_TASK + 大上下文模型 → FULL 档 + 暴露工具。"""
        agent = self._make_agent(tmp_path, tuan_home, provider="anthropic",
                                 model="claude-fable-5", context_window=1_000_000)
        agent.config.set_user("prompt.tier", "full")
        agent._soul_tier = "full"
        agent._last_user_input = "fix the bug in main.py"
        agent._build_system()
        assert agent._intent_route is not None
        assert agent._intent_route.intent is Intent.CODE_TASK
        assert agent._intent_route.expose_tools is True

    def test_router_failure_falls_back_to_existing_tier(self, tmp_path, tuan_home):
        """路由异常时不打断会话, 回退到既有 _soul_tier (fail-safe)。"""
        agent = self._make_agent(tmp_path, tuan_home, provider="anthropic",
                                 model="claude-fable-5", context_window=1_000_000)
        agent._soul_tier = "full"
        agent._last_user_input = "什么是闭包?"
        # 人为把 route 打坏: monkeypatch 成抛异常
        import tuan_cli.core.agent_prompt as ap
        original = ap.route
        try:
            def boom(*_a, **_k):
                raise RuntimeError("injected")
            ap.route = boom  # type: ignore[assignment]
            prompt = agent._build_system()
            # 回退 full 档 (既有 _soul_tier)
            assert prompt.splitlines()[0].startswith("# SOUL_FULL.md")
            assert agent._intent_route is None
        finally:
            ap.route = original  # type: ignore[assignment]