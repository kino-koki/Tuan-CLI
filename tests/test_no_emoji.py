# -*- coding: utf-8 -*-
"""「零 emoji」硬规则回归测试。

两层防线:
1. 提示词层 (``core.prompts._no_emoji_rule``) —— 从源头要求不输出 emoji;
   且规则文本自身**不得含 emoji** (举例 emoji 反而会示范与激活模型)。
2. 兜底层 (``core.output_sanitize``) —— 确定性移除, 覆盖所有运行路径的公共收尾
   ``Agent._teardown_run``。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.core.output_sanitize import has_emoji, strip_emoji  # noqa: E402
from tuan_cli.core.prompts import _no_emoji_rule  # noqa: E402

# 用码位转义构造 emoji, 而不是写字面量: 字面 emoji 在编辑/传输链路上容易被
# 悄悄抹掉, 会让测试"看似通过"实则没测到东西。
ROCKET = "\U0001F680"          # emoji: rocket
CHECK = "\u2705"                 # emoji: white heavy check mark
CROSS = "\u274C"                 # emoji: cross mark
WARN = "\u26A0"                  # misc symbol: warning sign
VS16 = "\uFE0F"                  # variation selector-16


class TestRuleText:
    def test_rule_exists_and_is_first(self):
        r = _no_emoji_rule()
        assert r.startswith("0. 零 emoji")

    def test_rule_text_itself_has_no_emoji(self):
        """关键: 规则里若举例 emoji, 等于把它们塞进模型上下文示范。"""
        assert not has_emoji(_no_emoji_rule()), "规则文本自身不得包含 emoji"

    def test_rule_mentions_html_and_ppt(self):
        r = _no_emoji_rule()
        assert "HTML" in r and "PPT" in r

    def test_rule_states_exception(self):
        """必须给例外, 否则模型会把 → ✓ 等中文常规符号也戒掉。"""
        r = _no_emoji_rule()
        assert "例外" in r

    def test_rule_injected_into_stable_prompt(self):
        from pathlib import Path

        from tuan_cli.core.prompts import build_system_prompt_stable

        prompt = build_system_prompt_stable(home=Path.home(), workspace=".")
        assert "零 emoji" in prompt


class TestStripEmoji:
    def test_strips_emoji(self):
        out, n = strip_emoji("任务完成 " + ROCKET + " 50% " + WARN)
        assert n > 0
        assert not has_emoji(out)
        assert "任务完成" in out and "50%" in out

    def test_clean_text_untouched(self):
        src = "这是一段普通中文回答, 没有 emoji。"
        out, n = strip_emoji(src)
        assert out == src, "干净文本必须逐字节不变"
        assert n == 0

    def test_empty_string(self):
        out, n = strip_emoji("")
        assert out == "" and n == 0

    def test_none_safe(self):
        out, n = strip_emoji(None)  # type: ignore[arg-type]
        assert out is None and n == 0

    def test_preserves_code_indentation(self):
        src = "def f():\n    return 1  # ok\n"
        out, _ = strip_emoji(src)
        assert "    return 1" in out, "不得破坏代码缩进"

    def test_preserves_typographic_arrows(self):
        """→ ← 在中文技术写作里是常规用法, 不属于 emoji, 不应被抹掉。"""
        src = "A -> B, 也可写 A → B"
        out, _ = strip_emoji(src)
        assert "→" in out

    def test_preserves_sqrt_and_times(self):
        src = "√ 正确, × 错误"
        out, _ = strip_emoji(src)
        assert "√" in out and "×" in out

    def test_removes_variation_selector(self):
        # U+FE0F 变体选择符会让残留符号被渲染成彩色图标, 必须一并移除
        src = "完成" + VS16
        out, n = strip_emoji(src)
        assert VS16 not in out
        assert n >= 1

    def test_strips_multiple_lines(self):
        src = "第一行\n第二行\n第三行"
        out, n = strip_emoji(src)
        assert out == src and n == 0

    def test_has_emoji_detector(self):
        assert has_emoji(ROCKET)
        assert has_emoji(CHECK) and has_emoji(CROSS)
        assert not has_emoji("正常")


class TestTeardownIntegration:
    """兜底层必须挂在**所有**运行路径的公共收尾上, 否则某条路径会漏。"""

    def test_teardown_sanitizes_answer(self):
        import inspect

        from tuan_cli.core.agent import Agent

        src = inspect.getsource(Agent._teardown_run)
        assert "strip_emoji" in src, "_teardown_run 必须做 emoji 净化"

    def test_both_run_paths_use_teardown(self):
        """带 LoopProvider 与内联 ReAct 两条路径都必须经由 _teardown_run 返回。"""
        import inspect

        from tuan_cli.core.agent import Agent

        for name in ("_run_with_loop", "_run_react_inline"):
            src = inspect.getsource(getattr(Agent, name))
            assert "_teardown_run" in src, f"{name} 未经过 _teardown_run"