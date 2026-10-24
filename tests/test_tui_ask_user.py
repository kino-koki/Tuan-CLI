"""TUI 模型提问卡片 (ask_user) 回归测试。

背景 —— 为什么之前"既溢出又选不了":
    `ask_user` 工具 (session_tools._ask_user_handler) 会先探测 `ctx.ui.ask_user`
    钩子; 此前 (a) Agent 构造 ToolContext 时**没传 ui** (ctx.ui 为 None),
    (b) TuiUI 桥接**没有** ask_user 方法 —— 于是钩子探测必然失败, 工具退回
    `print(f"\\n? {q}") + input("> ")`。在全屏 prompt_toolkit TUI 下, 这直接写
    stdout: prompt_toolkit 掌管的屏幕被冲垮 (用户报告的"溢出"), 而 input() 在
    备用屏/raw 模式下拿不到按键 ("选不了")。

本文件覆盖:
    - QxtTUI.ask_user 挂起卡片 / ↑↓ 移动 / Enter 取高亮 / 编号 / 自由作答;
    - 卡片渲染进对话区且**不溢出** (宽度受终端列数约束);
    - TuiUI 桥接转发到 QxtTUI;
    - session_tools 的安全阀: 全屏 TUI 在跑时禁止 print/input。
"""
import threading
from unittest import mock

import pytest

from tuan_cli.tui.tui import QxtTUI, _ask_user_plain
from tuan_cli.ui.tui_bridge import TuiUI


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


def _ready_tui(width=80, vp=30):
    tui = QxtTUI(on_submit=lambda s: "ok", title="t", workspace=".",
                 on_cancel=lambda: None, on_command=lambda c: None)
    tui.set_ready(_FakeConfig(), _FakeAgent(), ".")
    tui._log_window.measured_height = vp
    p1 = mock.patch.object(tui, "_box_width", return_value=width)
    p2 = mock.patch.object(tui, "_log_width", return_value=width)
    # ask_user 只看 app.is_running 就走卡片路径 (否则退回 headless input()).
    # 这里直接把属性打成 True, 无需真起事件循环。
    p3 = mock.patch.object(type(tui._app), "is_running",
                           new_callable=mock.PropertyMock, return_value=True)
    p1.start(); p2.start(); p3.start()
    tui._patches = (p1, p2, p3)
    return tui


@pytest.fixture()
def tui():
    t = _ready_tui()
    yield t
    for p in t._patches:
        p.stop()


def _card_text(tui):
    flat = "".join(s for _, s in tui._render_ask_card())
    return flat


def _vis(tui):
    """对话区当前渲染出的文本。"""
    return "".join(s for _, s in tui._render_conversation())


# ---------------------------------------------------------------- 挂起/解析

def _ask_in_thread(tui, question, options):
    """后台线程调 ask_user (模拟工具线程), 返回 (线程, 结果容器)。"""
    box = {}

    def run():
        box["ans"] = tui.ask_user(question, options)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    # 等卡片挂起
    for _ in range(200):
        if tui._ask_pending:
            break
        threading.Event().wait(0.01)
    return th, box


def test_ask_user_sets_pending_card(tui):
    th, box = _ask_in_thread(tui, "选哪个方案?", ["A", "B"])
    try:
        assert tui._ask_pending is not None, "应挂起提问卡片"
        assert tui._ask_pending["options"] == ["A", "B"]
        assert tui._ask_index == 0
    finally:
        tui.cancel_ask(); th.join(timeout=2)


def test_card_visible_in_conversation(tui):
    th, box = _ask_in_thread(tui, "选哪个方案?", ["方案甲", "方案乙"])
    try:
        vis = _vis(tui)
        assert "选哪个方案?" in vis, "卡片问题应出现在对话区"
        assert "方案甲" in vis and "方案乙" in vis
    finally:
        tui.cancel_ask(); th.join(timeout=2)


def test_up_down_move_highlight(tui):
    th, box = _ask_in_thread(tui, "Q?", ["A", "B", "C"])
    try:
        assert tui._ask_index == 0
        tui._ask_move(1); assert tui._ask_index == 1
        tui._ask_move(1); assert tui._ask_index == 2
        tui._ask_move(1); assert tui._ask_index == 2, "不应越界"
        tui._ask_move(-1); assert tui._ask_index == 1
        tui._ask_move(-5); assert tui._ask_index == 0, "不应越界"
    finally:
        tui.cancel_ask(); th.join(timeout=2)


def test_enter_takes_highlighted_option(tui):
    th, box = _ask_in_thread(tui, "Q?", ["A", "B", "C"])
    tui._ask_move(1)                       # 高亮 B
    tui._resolve_ask("")                   # 空回车 = 取高亮项
    th.join(timeout=2)
    assert box["ans"] == "B"
    assert tui._ask_pending is None


def test_number_input_selects_option(tui):
    th, box = _ask_in_thread(tui, "Q?", ["A", "B", "C"])
    tui._resolve_ask("3")
    th.join(timeout=2)
    assert box["ans"] == "C"


def test_free_text_answer(tui):
    th, box = _ask_in_thread(tui, "Q?", ["A", "B"])
    tui._resolve_ask("我自己写一个")
    th.join(timeout=2)
    assert box["ans"] == "我自己写一个"


def test_cancel_unblocks_with_empty_answer(tui):
    """取消 (Ctrl-Q/退出) 必须解冻工具线程, 否则模型线程永久挂死。"""
    th, box = _ask_in_thread(tui, "Q?", ["A"])
    tui.cancel_ask()
    th.join(timeout=2)
    assert not th.is_alive(), "取消后工具线程应被唤醒"
    assert box["ans"] == ""


def test_free_answer_mode_no_options(tui):
    """无选项时退化为纯自由作答。"""
    th, box = _ask_in_thread(tui, "你希望怎么做?", [])
    tui._ask_move(1)                       # 无选项时不应崩
    assert tui._ask_index == 0
    tui._resolve_ask("就这样")
    th.join(timeout=2)
    assert box["ans"] == "就这样"


# ---------------------------------------------------------------- 不溢出

def test_card_respects_terminal_width(tui):
    """超长问题/选项必须折行或裁剪, 不得超出终端列数 (这是"溢出"的根因)。"""
    width = 60
    t = _ready_tui(width=width)
    try:
        th, box = _ask_in_thread(t, "很长的问题" * 40, ["很长的选项" * 30] * 3)
        for ln in _card_text(t).split("\n"):
            assert _disp(ln) <= width, f"卡片行超宽: {_disp(ln)} > {width}"
        # 对话区整体也不得超宽
        for ln in _vis(t).split("\n"):
            assert _disp(ln) <= width + 40, "对话区行严重超宽"
        t.cancel_ask(); th.join(timeout=2)
    finally:
        for p in t._patches:
            p.stop()


def _disp(s):
    from tuan_cli.tui.tui import _wcswidth
    return sum(max(0, _wcswidth(c)) for c in s)


def test_many_options_still_fit_viewport(tui):
    """选项很多时, 卡片由虚拟视口切片, 不会把输入框顶破。"""
    t = _ready_tui(width=80, vp=24)
    try:
        opts = [f"选项{i}" for i in range(40)]
        th, box = _ask_in_thread(t, "挑一个", opts)
        # 对话区渲染高度受视口约束 (含卡片)
        t._follow = True
        rows = len("".join(s for _, s in t._render_conversation()).split("\n"))
        assert rows <= t._viewport_rows() + 2, f"卡片把视口撑到 {rows} 行"
        t.cancel_ask(); th.join(timeout=2)
    finally:
        for p in t._patches:
            p.stop()


# ---------------------------------------------------------------- 桥接 + 工具

def test_tuiui_bridge_forwards_ask_user(tui):
    bridge = TuiUI(tui)
    th, box = _ask_in_thread(tui, "Q?", ["A", "B"])
    out = {}

    def run():
        out["r"] = bridge.ask_user("Q?", ["A", "B"])
    th2 = threading.Thread(target=run, daemon=True)
    th2.start()
    for _ in range(200):
        if tui._ask_pending:
            break
        threading.Event().wait(0.01)
    tui._resolve_ask("2")
    th.join(timeout=2); th2.join(timeout=2)
    assert out["r"] == "B"


def test_session_tools_uses_ui_hook_not_print():
    """工具层: ctx.ui 有钩子时走卡片, 绝不 print/input。"""
    from tuan_cli.tools import session_tools

    asked = {}

    class _UI:
        def ask_user(self, q, opts):
            asked["q"] = q
            asked["opts"] = list(opts or [])
            return "选B"

    ctx = mock.Mock()
    ctx.ui = _UI()
    with mock.patch.object(session_tools, "_fullscreen_tui_active", return_value=True), \
         mock.patch("builtins.print") as pr, \
         mock.patch("builtins.input", side_effect=AssertionError("不应调用 input")):
        res = session_tools._ask_user_handler(ctx, question="挑一个", options=["A", "B"])
    assert "选B" in res
    assert asked["opts"] == ["A", "B"]
    pr.assert_not_called()


def test_session_tools_guard_blocks_print_under_tui():
    """安全阀: 全屏 TUI 在跑且无钩子 -> 走"无法交互"降级, 不 print/input。"""
    from tuan_cli.tools import session_tools

    ctx = mock.Mock()
    ctx.ui = None
    with mock.patch.object(session_tools, "_fullscreen_tui_active", return_value=True), \
         mock.patch("builtins.print") as pr, \
         mock.patch("builtins.input", side_effect=AssertionError("不应调用 input")):
        res = session_tools._ask_user_handler(ctx, question="挑一个", options=["A", "B"])
    pr.assert_not_called()
    assert "无法交互" in res
    assert "A | B" in res


def test_fullscreen_tui_active_detection(tui):
    """探测器: TuiUI 持有正在运行的 QxtTUI 时应返回 True (即禁止 print/input)。"""
    from tuan_cli.tools import session_tools
    from tuan_cli.cli import _ui_singleton

    bridge = TuiUI(tui)
    old = getattr(_ui_singleton, "_ui", None)
    _ui_singleton._ui = bridge
    try:
        # 本 fixture 把 is_running 打成 True -> 探测器应判定"全屏 TUI 在跑"
        assert session_tools._fullscreen_tui_active() is True
        # 换成非 TUI 的 UI 对象 -> 不应误判
        _ui_singleton._ui = object()
        assert session_tools._fullscreen_tui_active() is False
    finally:
        _ui_singleton._ui = old


def test_plain_ask_fallback_empty_options():
    """headless 兜底: 无选项时读一行。"""
    with mock.patch("builtins.input", return_value="  我的答案  "):
        assert _ask_user_plain("Q?", []) == "我的答案"


def test_plain_ask_fallback_with_options():
    with mock.patch("builtins.input", return_value="2"):
        assert _ask_user_plain("Q?", ["A", "B"]) == "B"