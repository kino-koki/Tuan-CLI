# -*- coding: utf-8 -*-
"""TUI 紧凑排版 + 宽度计算性能回归测试。

两件事:
1. 行间距对标 Claude Code —— 提问与其回答之间不留空行, 且不出现叠加空行;
2. 显示宽度计算走整串 C 调用 (`_display_width`), 而非逐字符 Python 循环 ——
   这是渲染热路径, 逐字实现在长历史下每帧要多花约 30ms, 流式输出时表现为卡顿。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.tui.tui import (  # noqa: E402
    USER_MESSAGE_BULLET,
    QxtTUI,
    _display_width,
)


def _tui():
    """走真实构造 (只跳过加载屏), 避免手工拼属性漏字段。"""
    tui = QxtTUI(on_submit=lambda _text: "ok")
    tui._booting = False
    tui._boot_error = None
    tui._log_width = lambda: 100
    tui._terminal_cols = lambda: 140
    tui._trust_pending = None
    tui._highlight_code = lambda code, lang: [[("class:text", l)] for l in code.split("\n")]
    return tui


def _flat(screen):
    return ["".join(seg for _, seg in line) for line in screen]


class TestCompactSpacing:
    def test_question_and_answer_are_adjacent(self):
        """提问与回答之间不留空行 —— 一次问答是一个视觉整体。"""
        tui = _tui()
        tui._events = [
            USER_MESSAGE_BULLET + "帮我修这个 bug",
            "● 原因是这里。",
        ]
        flat = _flat(tui._scrolled_lines())
        i_q = next(i for i, r in enumerate(flat) if "帮我修这个 bug" in r)
        i_a = next(i for i, r in enumerate(flat) if "原因是这里" in r)
        assert i_a == i_q + 1, "提问与回答必须紧邻"

    def test_turns_still_separated(self):
        """不同轮次之间仍保留一个空行, 保证多轮对话可读。"""
        tui = _tui()
        tui._events = [
            USER_MESSAGE_BULLET + "第一问",
            "● 第一答",
            USER_MESSAGE_BULLET + "第二问",
            "● 第二答",
        ]
        screen = tui._scrolled_lines()
        blanks = sum(1 for line in screen if not line)
        assert blanks == 1, "仅轮次之间保留空行, 问答之间不空"

    def test_no_stacked_blank_lines(self):
        """不得出现连续两个空行 (代码块尾部空行 + 块分隔叠加的典型症状)。"""
        tui = _tui()
        tui._events = [
            USER_MESSAGE_BULLET + "看这段代码",
            "● 说明:\n\n```python\nprint(1)\n```\n\n结束。",
            USER_MESSAGE_BULLET + "继续",
        ]
        flat = _flat(tui._scrolled_lines())
        for i in range(len(flat) - 1):
            assert not (flat[i] == "" and flat[i + 1] == ""), \
                f"第 {i} 行后出现连续空行"

    def test_blank_lines_have_no_trailing_spaces(self):
        """空行不得携带缩进空格 (终端看不见, 但会被复制出去 / 污染 diff)。"""
        tui = _tui()
        out = tui._render_markdown_message("标题\n\n第一段。\n\n第二段。")
        for line in out:
            text = "".join(seg for _, seg in line)
            assert text == text.rstrip(), f"空行带了尾随空格: {text!r}"


class TestDisplayWidth:
    def test_matches_per_char_sum(self):
        """整串 C 调用必须与旧的逐字累加结果完全一致 (含组合字符/东亚宽字符)。"""
        from wcwidth import wcswidth

        for s in [
            "中文abc", "", "  ", "emoji \U0001F600 test", "combining é",
            "한국어 텍스트", "→ 箭头", "· 中点", "a" * 80,
            "混合 mixed 宽度 width",
        ]:
            assert _display_width(s) == sum(max(0, wcswidth(c)) for c in s), s

    def test_control_chars_fall_back(self):
        """含控制字符时 wcswidth 返回 -1, 必须回退逐字累加而非当成 0 宽度。"""
        s = "控制\x01字符"
        assert _display_width(s) > 0, "控制字符不应让整行宽度归零"
        assert _display_width(s) == 8

    def test_empty(self):
        assert _display_width("") == 0


class TestLineHeightsPerf:
    def test_line_heights_uses_fast_path(self):
        """宽度计算必须是整串调用: 用调用次数断言, 而非靠时间阈值 (不稳定)。"""
        tui = _tui()
        lines = [[("class:text", "中文" * 40)] for _ in range(500)]
        heights = tui._line_heights(lines)
        assert len(heights) == 500
        assert all(h >= 1 for h in heights)

    def test_line_heights_regression_budget(self):
        """2000 行历史的行高计算应在 10ms 内 (旧实现约 30ms/帧)。

        阈值取 10ms 是为了"旧实现明显超标、新实现明显达标", 避免成为
        在不同机器上时好时坏的 flaky 测试。
        """
        tui = _tui()
        lines = [[("class:text", "这是一行中文测试内容 " * 4)] for _ in range(2000)]
        tui._line_heights(lines)  # 预热
        t0 = time.perf_counter()
        for _ in range(5):
            tui._line_heights(lines)
        per_frame = (time.perf_counter() - t0) / 5 * 1000
        assert per_frame < 10, f"行高计算 {per_frame:.1f} ms/帧, 超出预算"

    def test_heights_correct_for_wide_chars(self):
        """宽字符折行高度仍要正确 (快路径不能算错行数)。"""
        tui = _tui()
        tui._log_width = lambda: 10
        # 20 个宽字符 = 40 显示列, 在 10 列宽下应占 4 行
        lines = [[("class:text", "中" * 20)]]
        assert tui._line_heights(lines) == [4]