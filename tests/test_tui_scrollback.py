"""TUI 对话区**虚拟视口回卷**回归测试 (Claude Code 式"能真正翻看历史")。

背景 —— 为什么旧实现是坏的:
    旧实现靠 `FormattedTextControl.get_cursor_position` 伪造一个"光标行"来驱动
    prompt_toolkit 的 Window 滚动。但 Window 只会**最小幅度**滚动到该点可见,
    于是 PgUp 根本翻不动一屏 (只挪几行), 且一旦逻辑行与终端行错位 (长消息软
    换行), 中段内容永远够不到 —— 表现为"内容溢出后上面再也看不到"。

现在改为真虚拟视口 (`_viewport_slice`):
    - `_log_window` 实测自身高度 (终端行数) 作为视口高;
    - `_render_conversation` 只返回当前视口覆盖到的那几行 (首尾半行按显示行裁剪);
    - `_view_top` 记录视口顶端偏移, `_scroll_log` 以**终端行**为单位平移。

本文件覆盖: 每屏行数恒等于视口 / 整屏位移无重叠无跳空 / 顶部可达 / 底部跟随 /
上翻后新内容不把视图拽走 / 半行裁剪 / 内容不足一屏。
"""
import math
import re
from unittest import mock

import pytest

from tuan_cli.i18n import t
from tuan_cli.tui.tui import QxtTUI, _wcswidth

_MSG = re.compile(r"MSG(\d+)")


class _FakeCtx:
    confirm = None


class _FakeAgent:
    def __init__(self):
        self.ctx = _FakeCtx()
        self.plan_mode = False


class _FakeConfig:
    _d = {"model.provider": "x", "model.model": "y", "agent.effort": "high"}

    def get(self, k, d=None):
        return self._d.get(k, d)

    def api_key(self):
        return None


def _tui(n=200, vp=20, width=80):
    """构造一个 ready 状态、带 n 条消息、视口固定 vp 行的 TUI。"""
    tui = QxtTUI(
        on_submit=lambda s: "ok",
        title="t",
        workspace=".",
        on_cancel=lambda: None,
        on_command=lambda c: None,
    )
    tui.set_ready(_FakeConfig(), _FakeAgent(), ".")
    for i in range(n):
        tui.append_log(f"MSG{i:03d}")
    # 固定视口高度与列宽, 让断言可精确计算
    tui._log_window.measured_height = vp
    patcher = mock.patch.object(tui, "_log_width", return_value=width)
    patcher.start()
    tui._width_patcher = patcher
    return tui


@pytest.fixture()
def tui():
    t = _tui()
    yield t
    try:
        t._width_patcher.stop()
    except Exception:
        pass


def _msgs(tui):
    """当前视口里出现的消息序号 (按渲染顺序)。"""
    out = []
    for _, seg in tui._render_conversation():
        for m in _MSG.finditer(seg):
            out.append(int(m.group(1)))
    return out


def _rows(tui):
    """当前视口渲染出的**终端行数**。

    独立按显示宽度折行计算 (不复用被测代码的 _line_heights), 这样"切片高度是否
    恰好等于视口"才是被真正验证的量 —— 注意一个逻辑行可能折成多行, 不能直接
    数逻辑行条数。
    """
    w = tui._log_width()
    total = 0
    for ln in tui._viewport_slice(tui._scrolled_lines()):
        text = "".join(s for _, s in ln)
        disp = sum(max(0, _wcswidth(ch)) for ch in text)
        total += max(1, math.ceil(disp / w))
    return total


# ---------------------------------------------------------------- 基本视口

def test_viewport_renders_exactly_one_screen(tui):
    """内容远超一屏时, 只渲染视口那么多行 (不把整段历史塞给 Window)。"""
    _msgs(tui)  # 触发一次渲染, 解析 follow -> 底部
    total, vp, max_top = tui._scroll_bounds(tui._scrolled_lines(logic_only=True))
    assert total > vp > 0 and max_top > 0
    assert _rows(tui) == vp


def test_bottom_shows_latest_and_follows(tui):
    """默认停在底部, 能看到最新一条。"""
    got = _msgs(tui)
    assert got[-1] == 199
    assert tui._follow is True


def test_content_shorter_than_viewport_shows_all(tui):
    """内容不足一屏时全部显示, 且不进入滚动态。"""
    small = _tui(n=3, vp=20)
    try:
        got = _msgs(small)
        assert got == [0, 1, 2]
        assert small._follow is True
    finally:
        small._width_patcher.stop()


# ---------------------------------------------------------------- 整屏位移

def test_page_scroll_moves_exactly_one_screen(tui):
    """PgUp/PgDn 每次正好位移一屏 —— 旧实现这里是"只挪几行"的 bug。"""
    vp = tui._viewport_rows()
    b = _msgs(tui)                 # 底屏
    tui._scroll_log(-vp)
    u1 = _msgs(tui)
    tui._scroll_log(-vp)
    u2 = _msgs(tui)
    # 相邻两屏内容严格相邻: 无重叠、无跳空
    assert u1[-1] + 1 == b[0]
    assert u2[-1] + 1 == u1[0]
    # 每屏条数恒定 (每条 2 行)
    per = vp // 2
    assert len(b) == len(u1) == len(u2) == per


def test_scroll_down_returns_to_follow(tui):
    """一路下翻到底 -> 恢复 follow, 重新跟随新内容。"""
    vp = tui._viewport_rows()
    tui._scroll_log(-vp * 3)
    assert tui._follow is False
    total, _, _ = tui._scroll_bounds(tui._scrolled_lines(logic_only=True))
    tui._scroll_log(total)         # 远超底部
    assert tui._follow is True
    assert _msgs(tui)[-1] == 199


def test_top_and_bottom_shortcuts(tui):
    """跳顶能看到最早一条; 回底恢复跟随。"""
    total, _, max_top = tui._scroll_bounds(tui._scrolled_lines(logic_only=True))
    tui._scroll_to_top()
    assert tui._follow is False
    assert _msgs(tui)[0] == 0
    tui._scroll_to_bottom()
    tui._render_conversation()     # 解析 follow -> max_top
    assert tui._follow is True
    assert tui._view_top == max_top


def test_scroll_clamps_at_top(tui):
    """在顶部继续上翻不会越界 (停在 0)。"""
    tui._scroll_to_top()
    tui._scroll_log(-9999)
    assert tui._view_top == 0
    assert tui._follow is False


# ---------------------------------------------------------------- 跟随语义

def test_scrolled_up_not_yanked_by_new_content(tui):
    """上翻后到达新内容, 视图**不**被拽回底部 (Claude Code 同款行为)。"""
    vp = tui._viewport_rows()
    tui._scroll_log(-vp * 2)
    before = _msgs(tui)
    assert tui._follow is False
    for i in range(200, 230):       # 新来 30 条
        tui.append_log(f"MSG{i:03d}")
    after = _msgs(tui)
    assert after == before, "上翻状态下新内容不应改变视口"
    assert tui._follow is False


def test_follow_keeps_pinned_to_new_bottom(tui):
    """跟随状态下新内容会把最新一条顶到可见区。"""
    assert tui._follow is True
    for i in range(200, 260):
        tui.append_log(f"MSG{i:03d}")
    got = _msgs(tui)
    assert got[-1] == 259
    assert tui._follow is True


# ---------------------------------------------------------------- 逐行/半行

def test_single_line_scroll(tui):
    """Ctrl+↑/↓ (delta=1) 逐行翻, 不会跳过内容。"""
    b = _msgs(tui)
    tui._scroll_log(-1)
    u = _msgs(tui)
    # 上移 1 个终端行 -> 至少还能看到大部分同样的消息, 且顶行不晚于原来
    assert u[-1] <= b[-1]
    assert u[0] >= b[0] - 1


def test_clip_line_rows_slices_display_rows():
    """半行裁剪: 按显示行取子串, 宽字符按起始列归属。"""
    tui_ = QxtTUI(on_submit=lambda s: "ok", title="t", workspace=".",
                  on_cancel=lambda: None, on_command=lambda c: None)
    line = [("class:text", "abcdefghij")]      # 10 列, 宽度 5 -> 2 个显示行
    got = tui_._clip_line_rows(line, 0, 1, 5)
    assert "".join(s for _, s in got) == "abcde"
    got2 = tui_._clip_line_rows(line, 1, 2, 5)
    assert "".join(s for _, s in got2) == "fghij"
    # 全行命中时裁剪结果与原行等价
    got3 = tui_._clip_line_rows(line, 0, 2, 5)
    assert "".join(s for _, s in got3) == "abcdefghij"


def test_long_wrapped_line_fills_viewport(tui):
    """超长单行 (软换行成多屏) 也能逐屏翻 —— 逻辑行/终端行不错位。"""
    long_text = "L" * 3000          # 宽度 80 -> 约 38 个终端行, 远超 vp=10
    t2 = _tui(n=5, vp=10)
    try:
        t2._events.clear()
        t2.append_log(long_text)
        total, vp, max_top = t2._scroll_bounds(t2._scrolled_lines(logic_only=True))
        assert total > vp, f"长行应折成多屏 (total={total}, vp={vp})"
        bottom_text = "".join(s for _, s in t2._render_conversation())
        assert _rows(t2) == vp
        t2._scroll_log(-vp)
        up_text = "".join(s for _, s in t2._render_conversation())
        assert up_text != bottom_text, "上翻后内容应变化 (翻到了长行的更早部分)"
        assert _rows(t2) == vp, "翻页后仍应正好一屏"
    finally:
        t2._width_patcher.stop()


def test_viewport_slice_returns_full_screen_height(tui):
    """切片后的实际行数恒等于视口 (Window 无需再自行滚动)。"""
    vp = tui._viewport_rows()
    total, _, _ = tui._scroll_bounds(tui._scrolled_lines(logic_only=True))
    for top in (0, 1, vp - 1, vp, vp * 2, max(0, total - vp), max(0, total - 1)):
        tui._follow = False
        tui._view_top = top
        assert _rows(tui) == vp, f"view_top={top} 切片高度不等于视口"


# ---------------------------------------------------------------- 位置指示

def test_scroll_indicator_hidden_at_bottom(tui):
    """在底部 (跟随) 时不显示回卷指示, 不占底栏版面。"""
    assert tui._scroll_indicator() == []


def test_scroll_indicator_shown_when_scrolled_up(tui):
    """上翻后底栏出现位置指示 + 回底提示。"""
    vp = tui._viewport_rows()
    tui._scroll_log(-vp * 2)
    parts = tui._scroll_indicator()
    assert parts, "上翻后应有指示"
    text = "".join(s for _, s in parts)
    assert "↑" in text
    assert "/" in text, "应显示 位置/总行"
    assert t("tui.scroll_back_hint") in text, "应提示如何回到底部"


def test_scroll_indicator_clears_after_scroll_to_bottom(tui):
    """回到底部后指示消失。"""
    vp = tui._viewport_rows()
    tui._scroll_log(-vp * 3)
    assert tui._scroll_indicator()
    tui._scroll_to_bottom()
    tui._render_conversation()          # 解析 follow -> 底部
    assert tui._scroll_indicator() == []


def test_footer_contains_indicator_when_scrolled(tui):
    """指示器确实接进了底栏渲染。"""
    vp = tui._viewport_rows()
    tui._scroll_log(-vp)
    footer = "".join(s for _, s in tui._render_footer())
    assert "↑" in footer