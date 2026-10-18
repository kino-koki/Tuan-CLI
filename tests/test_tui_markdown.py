# -*- coding: utf-8 -*-
"""TUI Markdown / 代码语法高亮渲染回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.tui.tui import QxtTUI, STATUS_BULLET  # noqa: E402


def _tui() -> QxtTUI:
    return QxtTUI(on_submit=lambda x: None)


def _flat(lines):
    return [(cls, txt) for ln in lines for (cls, txt) in ln]


class TestHighlightCode:
    def test_python_token_colored(self):
        tui = _tui()
        lines = tui._highlight_code("def f():\n    return 1\n", "python")
        flat = _flat(lines)
        assert any(c.startswith("#") for c, _ in flat), "至少应有一个十六进制着色段"
        text = "".join(t for _, t in flat)
        assert "def f()" in text and "return 1" in text

    def test_unknown_lang_falls_back(self):
        tui = _tui()
        lines = tui._highlight_code("hello world", "not_a_real_lang_xyz")
        assert "".join(t for _, t in _flat(lines)) == "hello world"

    def test_code_lines_one_per_source_line(self):
        tui = _tui()
        lines = tui._highlight_code("a\nb\nc\n", "python")
        # 3 行源码 -> 3 个逻辑行 (供软换行高度估算)
        assert len(lines) == 3


class TestRenderMarkdown:
    def test_prose_keeps_text_and_bullet(self):
        tui = _tui()
        lines = tui._render_markdown_message("你好，这是一段普通文本")
        flat = _flat(lines)
        text = "".join(t for _, t in flat)
        assert "你好，这是一段普通文本" in text
        assert STATUS_BULLET in flat[0][1]

    def test_code_block_label_and_highlight(self):
        tui = _tui()
        md = "看这段代码：\n```python\nprint('hi')\n```\n结束"
        flat = _flat(tui._render_markdown_message(md))
        text = "".join(t for _, t in flat)
        assert "› python" in text
        assert "print('hi')" in text
        assert "看这段代码：" in text
        assert "结束" in text
        assert any(c.startswith("#") for c, _ in flat)

    def test_leading_bullet_not_duplicated(self):
        tui = _tui()
        md = STATUS_BULLET + "```python\nx = 1\n```"
        flat = _flat(tui._render_markdown_message(md))
        assert "".join(t for _, t in flat).count(STATUS_BULLET) == 1

    def test_multiline_code_preserved(self):
        tui = _tui()
        md = "```js\nconst a = 1;\nconst b = 2;\n```"
        flat = _flat(tui._render_markdown_message(md))
        text = "".join(t for _, t in flat)
        assert "const a = 1;" in text and "const b = 2;" in text

    def test_empty_message(self):
        tui = _tui()
        lines = tui._render_markdown_message("")
        assert len(lines) >= 1


class TestArgCompletion:
    def test_provider_completions(self):
        tui = _tui()
        cands = tui._arg_completions("provider", "")
        assert isinstance(cands, list) and len(cands) > 10
        assert "openai" in cands and "deepseek" in cands

    def test_provider_completions_prefix(self):
        tui = _tui()
        cands = tui._arg_completions("provider", "deep")
        assert all(c.lower().startswith("deep") for c in cands)
        assert "deepseek" in cands

    def test_model_completions(self):
        tui = _tui()
        cands = tui._arg_completions("model", "gpt")
        assert all(c.lower().startswith("gpt") for c in cands)
        assert "gpt-4o" in cands

    def test_model_completions_empty_prefix_lists_all(self):
        tui = _tui()
        cands = tui._arg_completions("model", "")
        assert len(cands) > 50  # 全量模型 ID (各供应商 MODEL_LISTS 并集)
        assert "deepseek-chat" in cands


class TestSlashArgMode:
    def _ready_tui(self):
        tui = _tui()
        tui._commands = ["/model", "/provider", "/help", "/web"]
        tui._booting = False
        tui._boot_error = None
        return tui

    def test_model_arg_opens_menu_and_accepts(self):
        tui = self._ready_tui()
        tui._input.buffer.text = "/model gpt"
        tui._on_input_changed()
        assert tui._slash_open is True
        assert tui._slash_arg_mode is True
        assert all(c.lower().startswith("gpt") for c in tui._slash_items)
        tui._slash_index = 0
        tui._accept_slash()
        assert tui._input.buffer.text.startswith("/model ")

    def test_provider_arg_filters(self):
        tui = self._ready_tui()
        tui._input.buffer.text = "/provider deep"
        tui._on_input_changed()
        assert tui._slash_open is True
        assert all(c.lower().startswith("deep") for c in tui._slash_items)
        assert "deepseek" in tui._slash_items
