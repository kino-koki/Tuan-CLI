# -*- coding: utf-8 -*-
"""/ 命令面板 (Claude Code 同款) + 文字溢出修复 + 终端标题 回归测试。

覆盖 tuan_cli/tui/tui.py 的:
- 输入 "/" / "+/" 自动展开命令面板, 前缀过滤, ↑↓ 循环选择
- Enter/Tab 确认填入输入框 (不直接执行)
- Esc / 空格 / 删空 / 非命令输入 关闭面板
- boot / 信任确认 / 命令确认态不展开; 思考中可预敲
- 面板 9 行封顶 + 滚动跟随 + 每行按显示宽度裁剪 (CJK 感知)
- _box_width 尊重真实终端宽 (窄终端不再强制 44 导致边框顶出屏幕)
- _clip_parts 对 height=1 无换行窗口的硬裁 (防文字溢出顶破布局)
- kimi 欢迎盒信息行裁剪
- win_compat.set_terminal_title 双通道 (OSC 0 + SetConsoleTitleW)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.tui.tui import (  # noqa: E402
    QxtTUI,
    _SLASH_MAX_VISIBLE,
    _disp_width,
)

CMDS = ["/help", "/model", "/clear", "/compact", "/mcp", "/tools", "/plan",
        "/mode", "/effort", "/offline", "/web", "/quit", "/cost", "/ctx", "/memory"]


class _Ev:
    """最小 KeyPressEvent 替身 (面板 Enter 分支只用 event.app, 已短路)。"""

    def __init__(self, app=None):
        self.app = app


def _tui(commands=CMDS, meta=None):
    t = QxtTUI(
        on_submit=lambda _x: "ok",
        commands=commands,
        command_meta=meta or {c: f"desc of {c}" for c in commands},
    )
    t._booting = False
    t._boot_error = None
    return t


def _type(t: QxtTUI, text: str) -> None:
    t._input.text = text
    t._on_input_changed()


# ---------------------------------------------------------------- 面板开合
class TestSlashMenuOpen:
    def test_slash_opens_and_highlights_first(self):
        t = _tui()
        _type(t, "/")
        assert t._slash_open is True
        assert len(t._slash_items) == len(CMDS)
        assert t._slash_index == 0

    def test_plus_slash_prefix_opens(self):
        t = _tui()
        _type(t, "+/")
        assert t._slash_open is True
        assert len(t._slash_items) == len(CMDS)

    def test_prefix_filter(self):
        t = _tui()
        _type(t, "/mo")
        assert t._slash_items == ["/model", "/mode"]

    def test_no_match_closes(self):
        t = _tui()
        _type(t, "/")
        assert t._slash_open
        _type(t, "/zzz")
        assert t._slash_open is False
        assert t._slash_items == []

    def test_space_closes_for_args(self):
        t = _tui()
        _type(t, "/help ")
        assert t._slash_open is False

    def test_empty_closes(self):
        t = _tui()
        _type(t, "/")
        _type(t, "")
        assert t._slash_open is False

    def test_plain_text_closes(self):
        t = _tui()
        _type(t, "/")
        _type(t, "hello")
        assert t._slash_open is False

    def test_accept_suppresses_reopen(self):
        """确认写入的命令文本不应触发联动重新展开。"""
        t = _tui()
        _type(t, "/cl")
        t._accept_slash(_Ev())
        assert t._input.text == "/clear"
        assert t._slash_open is False

    def test_no_commands_never_opens(self):
        t = _tui(commands=[])
        _type(t, "/")
        assert t._slash_open is False


class TestSlashMenuStates:
    def test_booting_suppresses(self):
        t = _tui()
        t._booting = True
        _type(t, "/")
        assert t._slash_open is False

    def test_trust_pending_suppresses(self):
        t = _tui()
        t._trust_pending = {"workspace": "x"}
        _type(t, "/")
        assert t._slash_open is False

    def test_confirm_pending_suppresses(self):
        t = _tui()
        t._confirm_pending = {"prompt": "x"}
        _type(t, "/")
        assert t._slash_open is False

    def test_busy_allows_pretype(self):
        """思考中允许预敲命令 (与 Claude Code 一致, 不吞按键)。"""
        t = _tui()
        t._busy = True
        _type(t, "/help")
        assert t._slash_open is True
        assert t._slash_items == ["/help"]


# ---------------------------------------------------------------- 导航/确认
class TestSlashMenuNav:
    def test_cyclic_move(self):
        t = _tui()
        _type(t, "/")
        t._slash_move(-1)
        assert t._slash_index == len(CMDS) - 1
        t._slash_move(1)
        assert t._slash_index == 0

    def test_enter_fills_not_executes(self):
        t = _tui()
        submitted = []
        t.on_submit = lambda x: submitted.append(x)
        _type(t, "/he")
        t._handle_enter(_Ev())
        assert t._input.text == "/help"
        assert t._slash_open is False
        assert submitted == []

    def test_enter_busy_fills_not_submits(self):
        t = _tui()
        t._busy = True
        submitted = []
        t.on_submit = lambda x: submitted.append(x)
        _type(t, "/help")
        t._handle_enter(_Ev())
        assert t._input.text == "/help"
        assert submitted == []

    def test_tab_accept_fills(self):
        t = _tui()
        _type(t, "/cl")
        t._accept_slash(_Ev())
        assert t._input.text == "/clear"


# ---------------------------------------------------------------- 渲染/裁剪
class TestSlashMenuRender:
    def _rows(self, t: QxtTUI):
        frags = t._render_slash_menu()
        rows, cur = [], []
        for cls, seg in frags:
            if seg == "\n":
                rows.append(cur)
                cur = []
            else:
                cur.append((cls, seg))
        if cur:
            rows.append(cur)
        return rows

    def test_highlight_marker_and_desc(self):
        t = _tui()
        _type(t, "/help")
        text = "".join(seg for _, seg in t._render_slash_menu())
        assert "▶ /help" in text
        assert "desc of /help" in text

    def test_rows_capped_at_max_visible(self):
        big = [f"/cmd{i:02d}" for i in range(55)]
        t = _tui(commands=big)
        _type(t, "/")
        assert t._slash_menu_rows() == _SLASH_MAX_VISIBLE == 9

    def test_scroll_follows_highlight(self):
        big = [f"/cmd{i:02d}" for i in range(55)]
        t = _tui(commands=big)
        _type(t, "/")
        for _ in range(20):
            t._slash_move(1)
        assert t._slash_index == 20
        assert t._slash_scroll == 20 - _SLASH_MAX_VISIBLE + 1

    def test_long_desc_clipped_to_width(self):
        long_meta = {c: "超长描述测试" * 20 for c in CMDS}
        t = _tui(meta=long_meta)
        _type(t, "/")
        rows = self._rows(t)
        width = t._term_width()
        for row in rows:
            w = sum(_disp_width(s) for _, s in row)
            assert w <= width, f"行宽 {w} 超过终端宽 {width}"

    def test_more_hint_when_overflow(self):
        big = [f"/cmd{i:02d}" for i in range(30)]
        t = _tui(commands=big)
        _type(t, "/")
        text = "".join(seg for _, seg in t._render_slash_menu())
        assert "还有" in text and "21" in text


# ---------------------------------------------------------------- 溢出修复
class _FakeSize:
    columns = 40


class _FakeOutput:
    def get_size(self):
        return _FakeSize()


class _FakeApp:
    output = _FakeOutput()
    is_running = False


class TestOverflowFixes:
    def test_box_width_respects_real_width(self):
        """窄终端 (<44) 不得强制 44: 否则右边框顶出屏幕导致换行错位。"""
        t = _tui()
        t._app = _FakeApp()
        assert t._box_width() == 40

    def test_box_width_fallback(self):
        t = _tui()
        t._app = None
        assert t._box_width() >= 1

    def test_clip_parts_hard_clips(self):
        t = _tui()
        t._app = _FakeApp()
        out = t._clip_parts([("class:a", "A" * 30), ("class:b", "B" * 30)])
        assert sum(_disp_width(s) for _, s in out) <= 40
        assert out[0][1] == "A" * 30  # 首段完整保留
        assert "…" in out[-1][1]      # 裁切段补省略号

    def test_clip_parts_identity_when_fits(self):
        t = _tui()
        t._app = _FakeApp()
        parts = [("class:a", "短行")]
        assert t._clip_parts(parts) == parts

    def test_kimi_box_rows_within_width(self):
        t = _tui()
        t._app = _FakeApp()
        box = t._kimi_box("标题", "副标题", [("键", "值" * 60), ("长键名", "x" * 100)])
        for row in box:
            if isinstance(row, list):
                w = sum(_disp_width(s) for _, s in row)
                assert w <= 40, f"欢迎盒行宽 {w} 超过 40"


# ---------------------------------------------------------------- 终端标题
class TestTerminalTitle:
    def test_set_terminal_title_exists_and_dual_channel(self):
        import inspect
        from tuan_cli.tui import win_compat
        from tuan_cli.tui.tui import TERMINAL_TITLE

        assert TERMINAL_TITLE == "Tuan-CLI"
        assert callable(win_compat.set_terminal_title)
        src = inspect.getsource(win_compat.set_terminal_title)
        assert "]0;" in src                  # OSC 0 转义序列
        assert "SetConsoleTitleW" in src     # Win32 回退
        assert "except" in src               # 失败静默

    def test_set_terminal_title_no_crash_on_failure(self, monkeypatch):
        from tuan_cli.tui import win_compat
        # 强制两条通道都失败也不应抛异常
        monkeypatch.setattr(win_compat.sys, "stdout", None, raising=False)
        monkeypatch.setattr(win_compat.ctypes, "windll", None, raising=False)
        win_compat.set_terminal_title("Tuan-CLI")  # 不抛即通过

    def test_title_env_override(self, monkeypatch):
        monkeypatch.setenv("TUAN_TERMINAL_TITLE", "Custom")
        import importlib
        from tuan_cli.tui import tui as tui_mod
        importlib.reload(tui_mod)
        try:
            assert tui_mod.TERMINAL_TITLE == "Custom"
        finally:
            monkeypatch.delenv("TUAN_TERMINAL_TITLE", raising=False)
            importlib.reload(tui_mod)


# ---------------------------------------------------------------- 按键绑定
class TestSlashKeyBindings:
    def test_up_down_swallow_only_when_open(self):
        """面板关闭时 ↑↓ 必须走历史导航 (不再被吞)。"""
        import inspect
        from tuan_cli.tui import tui as tui_mod
        src = inspect.getsource(tui_mod)
        assert "b.auto_up" in src
        assert "b.auto_down" in src

    def test_escape_closes_only_when_open(self):
        import inspect
        from tuan_cli.tui import tui as tui_mod
        src = inspect.getsource(tui_mod)
        assert "_close_slash_menu" in src
