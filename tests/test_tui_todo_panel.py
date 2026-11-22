# -*- coding: utf-8 -*-
"""TUI 任务清单执行面板测试 (F3)。

Agent 用 todo_write 记录多步骤任务并落盘到 <workspace>/.tuan/todo.json;
面板只读展示进度 (进行中 > 待办 > 已完成), 与 diff 面板共用右侧栏位、
互斥展开。验证不依赖真实终端 —— 直接实例化 QxtTUI 并驱动面板方法。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.tui.tui import QxtTUI  # noqa: E402


def _make_tui(cols: int = 140) -> QxtTUI:
    """造一个只初始化面板相关字段的 TUI 实例 (绕过重量级 __init__)。"""
    tui = QxtTUI.__new__(QxtTUI)
    tui.workspace = "."
    tui._diff_visible = False
    tui._diff_width = 0
    tui._todo_visible = False
    tui._todo_cache = []
    tui._todo_error = ""
    tui._todo_fetched_at = 0.0
    tui._app = None
    tui._terminal_cols = lambda: cols  # type: ignore[method-assign]
    return tui


def _write_todos(ws: Path, todos: list) -> None:
    d = ws / ".tuan"
    d.mkdir(parents=True, exist_ok=True)
    (d / "todo.json").write_text(json.dumps(todos, ensure_ascii=False), encoding="utf-8")


class TestToggle:
    def test_toggle_flips(self):
        tui = _make_tui()
        tui.toggle_todo()
        assert tui._todo_visible is True
        tui.toggle_todo()
        assert tui._todo_visible is False

    def test_toggle_resets_throttle_so_opening_refreshes(self):
        tui = _make_tui()
        tui._todo_fetched_at = 9e9
        tui.toggle_todo()
        assert tui._todo_fetched_at == 0.0

    def test_mutually_exclusive_with_diff(self):
        """同一右侧栏位: 开 todo 关 diff, 开 diff 关 todo。"""
        tui = _make_tui()
        tui.toggle_diff()
        tui.toggle_todo()
        assert tui._todo_visible is True
        assert tui._diff_visible is False
        tui.toggle_diff()
        assert tui._diff_visible is True
        assert tui._todo_visible is False


class TestFetch:
    def test_reads_workspace_todo_json(self, tmp_path):
        _write_todos(tmp_path, [
            {"content": "步骤一", "status": "completed"},
            {"content": "步骤二", "status": "in_progress"},
            {"content": "步骤三", "status": "pending"},
        ])
        tui = _make_tui()
        tui.workspace = str(tmp_path)
        tui._fetch_todos()
        assert tui._todo_error == ""
        assert len(tui._todo_cache) == 3
        assert tui._todo_cache[0]["content"] == "步骤一"

    def test_missing_file_is_empty_not_error(self, tmp_path):
        tui = _make_tui()
        tui.workspace = str(tmp_path)
        tui._fetch_todos()
        assert tui._todo_cache == []
        assert tui._todo_error == ""


class TestRender:
    def test_render_empty_when_hidden(self):
        tui = _make_tui()
        assert tui._render_todo_panel() == []

    def test_render_shows_progress_and_items(self, tmp_path):
        _write_todos(tmp_path, [
            {"content": "已完成步骤", "status": "completed"},
            {"content": "进行中步骤", "status": "in_progress"},
            {"content": "待办步骤", "status": "pending"},
        ])
        tui = _make_tui()
        tui._todo_visible = True
        tui.workspace = str(tmp_path)
        rows = tui._render_todo_panel()
        text = "".join(seg for _, seg in rows)
        assert "1/3 已完成" in text
        assert "进行中步骤" in text and "待办步骤" in text and "已完成步骤" in text

    def test_render_orders_in_progress_first(self, tmp_path):
        _write_todos(tmp_path, [
            {"content": "甲-待办", "status": "pending"},
            {"content": "乙-进行中", "status": "in_progress"},
        ])
        tui = _make_tui()
        tui._todo_visible = True
        tui.workspace = str(tmp_path)
        text = "".join(seg for _, seg in tui._render_todo_panel())
        assert text.index("乙-进行中") < text.index("甲-待办")

    def test_render_marks_in_progress_with_accent(self, tmp_path):
        _write_todos(tmp_path, [{"content": "进行中", "status": "in_progress"}])
        tui = _make_tui()
        tui._todo_visible = True
        tui.workspace = str(tmp_path)
        styles = {cls for cls, _ in tui._render_todo_panel()}
        assert "class:accent" in styles

    def test_render_empty_list_shows_hint(self, tmp_path):
        tui = _make_tui()
        tui._todo_visible = True
        tui.workspace = str(tmp_path)
        text = "".join(seg for _, seg in tui._render_todo_panel())
        assert "暂无任务" in text

    def test_render_error_does_not_raise(self):
        tui = _make_tui()
        tui._todo_visible = True
        tui._todo_error = "boom"
        tui._render_todo_panel()  # 不抛异常即通过


class TestBinding:
    def test_f3_bound(self):
        from pathlib import Path as _P
        import tuan_cli.tui as _pkg
        pkg_dir = _P(_pkg.__file__).parent
        src = "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(pkg_dir.glob("*.py"))
        )
        assert '@kb.add("f3")' in src, "应绑定 F3"
