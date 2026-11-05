# -*- coding: utf-8 -*-
"""TUI 对话区虚拟视口 (回卷) 回归测试。

用户反馈「上翻/下翻还是会被顶掉」。实测根因不是切片逻辑本身 (它是对的), 而是
**视口高度取自上一帧的实测值**: 布局刚变化的那一帧 (Ctrl+O 审计面板 / "/" 命令
面板 / 输入框变多行 / 终端改大小), 实测高度还是旧的"大值", 于是切出的行数超过
窗口真正能显示的行数 → prompt_toolkit 的 Window 触发它自己的内部滚动, 与我们的
视口两套机制打架, 表现就是内容被顶掉、翻不动。

因此本文件锁定:
1. `_visible_log_rows` 按当前布局算出视口**上界**;
2. `_viewport_rows` 用实测值但必须被该上界**钳制**;
3. 切片行数恒 <= 视口行数 (Window 永不内部滚动);
4. 上翻后新内容不改变视图 (滚动位置不被顶掉);
5. 实测值未就绪时回退到理论值, 不会返回 0/None 之类把视口算崩的值。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.tui.tui import QxtTUI  # noqa: E402


class _Size:
    def __init__(self, rows, columns=120):
        self.rows = rows
        self.columns = columns


class _Out:
    def __init__(self, rows):
        self._rows = rows

    def get_size(self):
        return _Size(self._rows)


class _App:
    def __init__(self, rows=40):
        self.output = _Out(rows)
        self.is_running = False


def _tui(rows: int = 40, lines: int = 80) -> QxtTUI:
    tui = QxtTUI(on_submit=lambda _t: "ok")
    tui._booting = False
    tui._boot_error = None
    tui._trust_pending = None
    tui._log_width = lambda: 100
    tui._app = _App(rows)
    for i in range(1, lines + 1):
        tui.append_log(f"行{i:03d}")
    return tui


class TestVisibleRowsCeiling:
    def test_no_panels(self):
        tui = _tui(rows=40)
        # 终端 40 - 输入框 3 - 底栏 1
        assert tui._visible_log_rows() == 36

    def test_audit_panel_shrinks_viewport(self):
        """Ctrl+O 展开审计面板后, 视口必须显著变小, 否则切片会溢出窗口。"""
        tui = _tui(rows=40)
        before = tui._visible_log_rows()
        tui._audit_visible = True
        assert tui._visible_log_rows() < before

    def test_slash_menu_shrinks_viewport(self):
        tui = _tui(rows=40)
        before = tui._visible_log_rows()
        tui._slash_open = True
        tui._slash_items = [("a", "b")] * 5
        tui._slash_menu_rows = lambda: 9
        assert tui._visible_log_rows() < before

    def test_confirm_card_shrinks_viewport(self):
        tui = _tui(rows=40)
        before = tui._visible_log_rows()
        tui._confirm_pending = {"prompt": "确认?"}
        assert tui._visible_log_rows() < before

    def test_never_degenerate(self):
        """极小终端也不能返回 <=0 的视口高度, 否则切片/滚动全崩。"""
        tui = _tui(rows=6)
        tui._audit_visible = True
        assert tui._visible_log_rows() >= 3


class TestViewportClamp:
    def test_clamps_stale_measured_height(self):
        """核心回归: 上一帧的旧实测高度必须被当前布局上界钳制。"""
        tui = _tui(rows=40)
        tui._log_window.measured_height = 36      # 面板打开前的老值
        tui._audit_visible = True                 # 面板现在打开了
        ceiling = tui._visible_log_rows()
        assert tui._viewport_rows() <= ceiling, "过期实测高度未被钳制"
        assert tui._viewport_rows() < 36

    def test_falls_back_when_unmeasured(self):
        """实测值未就绪 (首帧) 时回退到理论值, 而不是 0。"""
        tui = _tui(rows=40)
        tui._log_window.measured_height = 0
        assert tui._viewport_rows() == tui._visible_log_rows()
        assert tui._viewport_rows() >= 3

    def test_keeps_accurate_measurement(self):
        """实测值未超上界时应原样采用 (不能把精确测量也压掉)。"""
        tui = _tui(rows=40)
        exact = tui._visible_log_rows()
        tui._log_window.measured_height = exact
        assert tui._viewport_rows() == exact

    @pytest.mark.parametrize("audit", [False, True])
    @pytest.mark.parametrize("stale", [0, 36, 40])
    def test_slice_never_exceeds_viewport(self, audit, stale):
        """切片行数必须 <= 视口行数 —— 否则 Window 会自己滚动, 把视口顶掉。"""
        tui = _tui(rows=40)
        tui._log_window.measured_height = stale
        tui._audit_visible = audit
        tui._viewport_rows()          # 先 resolve 一次
        screen = tui._viewport_slice(tui._scrolled_lines())
        assert len(screen) <= tui._viewport_rows(), (
            f"切片 {len(screen)} 行 > 视口 {tui._viewport_rows()} 行 (audit={audit}, stale={stale})"
        )


class TestScrollStability:
    def test_scroll_up_leaves_follow(self):
        tui = _tui()
        assert tui._follow is True
        tui._scroll_log(-tui._viewport_rows())
        assert tui._follow is False
        assert tui._view_top >= 0

    def test_new_content_does_not_push_view(self):
        """核心回归: 上翻后到达的新内容不得改变视图位置。"""
        tui = _tui()
        for _ in range(3):
            tui._scroll_log(-tui._viewport_rows())
        assert tui._follow is False
        before = "".join(s for _, s in tui._render_conversation())

        for i in range(200, 210):          # 模拟流式输出
            tui.append_log(f"新内容{i}")
        after = "".join(s for _, s in tui._render_conversation())
        assert tui._follow is False, "新内容把视图拽回了底部"
        assert before == after, "视图内容被顶掉了"

    def test_new_stream_does_not_push_view(self):
        tui = _tui()
        tui._scroll_log(-tui._viewport_rows())
        tui._streaming = True
        for chunk in ("正在", "生成", "回答"):
            tui._stream_buf = chunk
            tui._render_conversation()
            assert tui._follow is False, f"流式输出把视图拽走: {chunk}"

    def test_scroll_back_to_bottom_resumes_follow(self):
        tui = _tui()
        tui._scroll_log(-tui._viewport_rows())
        assert tui._follow is False
        tui._scroll_log(10_000)             # 往下滚到底
        assert tui._follow is True, "滚到底应恢复自动跟随"

    def test_scroll_to_top_and_back(self):
        tui = _tui()
        tui._scroll_to_top()
        assert tui._follow is False and tui._view_top == 0
        tui._scroll_to_bottom()
        assert tui._follow is True


class TestScrollHint:
    def test_hint_mentions_keys(self):
        """回卷提示必须告诉用户**怎么翻**, 而不是只说怎么回到底部。"""
        from tuan_cli.i18n import t

        hint = t("tui.scroll_back_hint")
        assert "pgup" in hint and "pgdn" in hint, f"提示未说明翻页键位: {hint}"
