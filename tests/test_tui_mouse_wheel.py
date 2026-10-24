"""TUI 鼠标滚轮回看对话历史 (Claude Code 同款) 回归测试。

背景 —— 为什么不能用"往管道里灌转义序列"来测:
    prompt_toolkit 的鼠标事件有**两条互斥通道** (见其key_binding/bindings/mouse.py):
      - `Keys.Vt100MouseEvent`: 解析 VT100/xterm/SGR 序列 (`ESC [ < 64 ; c ; r M`),
        Linux/macOS 与测试管道走这条;
      - `Keys.WindowsMouseEvent`: Windows 原生控制台 `MOUSE_EVENT_RECORD`
        (见 input/win32.py::_handle_mouse, 靠 `MOUSE_WHEELED` 标志 +
        `ButtonState` 正负判方向), **本项目用户在 Windows 上走的正是这条**。
    而 `input/vt100.py` 顶部就 `assert sys.platform != "win32"` —— 在 Windows
    上根本无法构造 VT100 输入, 灌序列永远不会被解析成 MouseEvent。

    所以测试直接构造 win32 通道真实产生的 `KeyPress(MouseEvent)` 来驱动绑定,
    这与用户实机路径完全一致 (且不依赖平台)。

覆盖: 滚轮方向与行数 / 上下往返无漂移 / 到底恢复跟随 / 到顶到最早历史 /
交互卡片态滚轮让位给选项 / 卡片让位不影响翻页 / 鼠标开关环境变量 /
非滚轮鼠标事件不被消费。
"""
from unittest import mock

import pytest
from prompt_toolkit.data_structures import Point
from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.keys import Keys
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType


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


N_MESSAGES = 400
VP = 20


def _tui(n=N_MESSAGES, vp=VP):
    tui = _make()
    for i in range(n):
        tui.append_log(f"MSG{i:04d} 内容")
    tui._log_window.measured_height = vp
    tui._log_window.measured_width = 80
    return tui


def _make():
    from tuan_cli.tui.tui import QxtTUI

    tui = QxtTUI(on_submit=lambda s: "ok", title="t", workspace=".",
                 on_cancel=lambda: None, on_command=lambda c: None)
    tui.set_ready(_FakeConfig(), _FakeAgent(), ".")
    return tui


def _mouse_event(etype, button=MouseButton.NONE):
    """构造 MouseEvent (签名: position/event_type/button/modifiers)。"""
    return MouseEvent(position=Point(x=10, y=10), event_type=etype,
                      button=button, modifiers=frozenset())


def _wheel_event(up: bool, channel="win32"):
    """构造一条滚轮按键事件 (形态与 prompt_toolkit 真实产出一致)。"""
    etype = MouseEventType.SCROLL_UP if up else MouseEventType.SCROLL_DOWN
    key = Keys.WindowsMouseEvent if channel == "win32" else Keys.Vt100MouseEvent
    return KeyPress(key, _mouse_event(etype))


class _FakeEvent:
    """最小 KeyPressEvent 替身: 只需 app.invalidate 与 data。"""

    def __init__(self, keypress):
        self.data = keypress.data
        self.key_sequence = keypress.key
        self.invalidated = 0
        self.app = self

    def invalidate(self):
        self.invalidated += 1


def _wheel(tui, up, count=1, channel="win32"):
    """驱动 `_mouse_wheel` n 次,方向由 event.data.event_type 决定。

    走的是与实机完全相同的分派逻辑 (`_mouse_wheel` 内部按 event_type 判方向),
    而不是直接调 `_scroll_log` —— 后者会绕过"卡片让位"等全部策略,测不到真东西。
    绑定是否注册到正确键名由 `test_binding_registered_*` 单独断言。
    """
    for _ in range(count):
        tui._mouse_wheel(_FakeEvent(_wheel_event(up, channel)), up=up)
    return tui


# ============================================================ 绑定注册


def test_binding_registered_for_both_mouse_channels():
    """两个鼠标通道的键名都必须注册 —— Windows 走 win32, 其他平台走 vt100。"""
    import prompt_toolkit.keys as pt_keys

    tui = _make()
    # 让 _build_keys 真的跑一遍 (需要 app 已存在)
    kb = tui._app.key_bindings if tui._app else None
    if kb is None:
        pytest.skip("headless 环境下未构建键位表")
    registered = {str(getattr(b.keys[0], "value", b.keys[0]))
                  for b in kb.bindings if b.keys}
    assert pt_keys.Keys.WindowsMouseEvent.value in registered
    assert pt_keys.Keys.Vt100MouseEvent.value in registered


def test_wheel_step_size_positive_and_small():
    """一格滚轮的行数必须是正数且不大 (太大则一格就翻出屏幕)。"""
    from tuan_cli.tui.tui import QxtTUI

    assert 1 <= QxtTUI._MOUSE_WHEEL_LINES <= 6


# ============================================================ 翻页行为


def test_wheel_up_moves_view_toward_history():
    tui = _tui()
    tui._scroll_to_bottom()          # 先确保在底部跟随
    before = tui._scroll_state()
    # _scroll_state() 第一项是 "已上翻"(= not follow), 底部时为 False
    assert before[0] is False
    _wheel(tui, up=True, count=3)
    scrolled_back, top, total, vp = tui._scroll_state()
    assert scrolled_back is True, "向上滚后应处于已上翻状态"
    assert top < before[1], "向上滚应让视口顶端上移(回到更早的历史)"


def test_wheel_down_moves_view_toward_newest():
    tui = _tui()
    tui._scroll_to_bottom()
    _wheel(tui, up=True, count=5)
    up_top = tui._scroll_state()[1]
    _wheel(tui, up=False, count=2)
    _back, down_top, _t, _v = tui._scroll_state()
    assert down_top > up_top, "向下滚应让视口顶端下移(回到更新的内容)"


def test_wheel_step_is_exact_multiple():
    """一次滚轮平移的行数必须精确等于 _MOUSE_WHEEL_LINES (不多不少)。"""
    from tuan_cli.tui.tui import QxtTUI

    tui = _tui()
    tui._scroll_to_bottom()
    start = tui._scroll_state()[1]
    _wheel(tui, up=True, count=1)
    one = tui._scroll_state()[1]
    assert start - one == QxtTUI._MOUSE_WHEEL_LINES

    _wheel(tui, up=True, count=2)
    three = tui._scroll_state()[1]
    assert one - three == 2 * QxtTUI._MOUSE_WHEEL_LINES


def test_wheel_up_then_down_no_drift():
    """上滚 N 格再下滚 N 格必须精确回到原位 (无累积漂移)。"""
    from tuan_cli.tui.tui import QxtTUI

    tui = _tui()
    tui._scroll_to_bottom()
    _wheel(tui, up=True, count=7)
    mid = tui._scroll_state()[1]
    _wheel(tui, up=False, count=7)
    back = tui._scroll_state()
    assert back[0] is False, "回到原位应恢复跟随(已上翻标记消失)"
    assert back[1] == mid + 7 * QxtTUI._MOUSE_WHEEL_LINES


def test_wheel_to_top_reaches_oldest():
    tui = _tui()
    _wheel(tui, up=True, count=5000)
    scrolled_back, top, _total, _vp = tui._scroll_state()
    assert top == 0, "应能一路滚到最早的历史"
    assert scrolled_back is True


def test_wheel_to_bottom_restores_follow():
    tui = _tui()
    _wheel(tui, up=True, count=50)
    assert tui._scroll_state()[0] is True, "上翻后应标记为已上翻"
    _wheel(tui, up=False, count=5000)
    scrolled_back, top, _total, _vp = tui._scroll_state()
    assert scrolled_back is False, "滚到底应恢复跟随(已上翻标记消失)"
    assert top > 0


def test_wheel_does_nothing_when_content_fits_one_screen():
    """内容不足一屏时滚轮不应产生位移 (也不能把 follow 弄丢)。"""
    tui = _tui(n=3)
    tui._scroll_to_bottom()
    before = tui._scroll_state()
    _wheel(tui, up=True, count=10)
    after = tui._scroll_state()
    assert after[1] == before[1]


# ============================================================ 交互卡片让位


def test_wheel_moves_ask_option_not_history():
    """模型提问卡片激活时, 滚轮应移动选项高亮, **不**翻历史。

    这正是上一轮ask_user "能看不能选" 问题的同类: 若滚轮抢走上下语义,
    用户看到的选项列表却不动。
    """
    tui = _tui(n=50)
    tui._ask_pending = {"question": "选一个", "options": ["A", "B", "C", "D"],
                        "event": None}
    tui._ask_index = 0
    tui._scroll_to_bottom()
    top_before = tui._scroll_state()[1]
    _wheel(tui, up=False, count=2)
    assert tui._ask_index == 2, "滚轮应把高亮移到第3 项"
    assert tui._scroll_state()[1] == top_before, "提问卡片态不应翻历史"

    _wheel(tui, up=True, count=1)
    assert tui._ask_index == 1, "向上滚应回到上一项"


def test_wheel_ask_index_clamps_at_bounds():
    tui = _tui(n=50)
    tui._ask_pending = {"question": "q", "options": ["A", "B"], "event": None}
    tui._ask_index = 0
    _wheel(tui, up=True, count=5)
    assert tui._ask_index == 0, "上滚到顶应停在第一项"
    _wheel(tui, up=False, count=5)
    assert tui._ask_index == 1, "下滚到底应停在最后一项"


def test_wheel_moves_trust_option():
    """信任确认卡片是两项 radiolist, 滚轮应在其间切换。"""
    tui = _tui(n=50)
    tui._trust_pending = {"workspace": "/tmp/x", "on_confirm": lambda x: None}
    tui._trust_index = 0
    _wheel(tui, up=False, count=1)
    assert tui._trust_index == 1
    _wheel(tui, up=True, count=1)
    assert tui._trust_index == 0


def test_wheel_moves_slash_menu_index():
    """/" 面板展开时滚轮应移动命令高亮, 不翻历史。"""
    tui = _tui(n=50)
    tui._slash_items = ["/help", "/model", "/provider", "/clear"]
    tui._command_meta = {c: "desc" for c in tui._slash_items}
    tui._slash_open = True
    tui._slash_index = 0
    top_before = tui._scroll_state()[1]
    _wheel(tui, up=False, count=2)
    assert tui._slash_index == 2
    assert tui._scroll_state()[1] == top_before


def test_wheel_owner_reports_active_card():
    tui = _tui(n=50)
    assert tui._wheel_owner() is False
    tui._ask_pending = {"question": "q", "options": ["A"], "event": None}
    assert tui._wheel_owner() is True
    tui._ask_pending = None
    tui._slash_open = True
    tui._slash_items = ["/help"]
    assert tui._wheel_owner() is True
    tui._slash_items = []
    assert tui._wheel_owner() is False


# ============================================================ 非滚轮事件 / 开关


def test_non_scroll_mouse_event_does_not_scroll():
    """点击/移动不应触发翻页 —— 那些事件要留给终端做文本选择。"""
    from tuan_cli.tui.tui import QxtTUI

    tui = _tui(n=50)
    tui._scroll_to_bottom()
    top_before = tui._scroll_state()[1]
    for etype in (MouseEventType.MOUSE_DOWN, MouseEventType.MOUSE_UP,
                  MouseEventType.MOUSE_MOVE):
        ev = _FakeEvent(KeyPress(Keys.WindowsMouseEvent,
                                 _mouse_event(etype, MouseButton.LEFT)))
        # 点击/移动事件会进同一个绑定, 但绑定内部只处理 SCROLL_*, 其余不消费
        tui._mouse_wheel(ev, up=(etype == MouseEventType.SCROLL_UP))
    assert tui._scroll_state()[1] == top_before


def test_scroll_binding_ignores_non_scroll_events():
    """绑定层: 非滚轮鼠标事件不应触发滚动 (必须交回终端做文本选择)。

    这条直接验"绑定只对 SCROLL_UP/SCROLL_DOWN 反应"—— 绑定里若漏了
    event_type 判断, 点击就会变成翻页。
    """
    from tuan_cli.tui.tui import QxtTUI

    tui = _tui(n=50)
    tui._scroll_to_bottom()
    top_before = tui._scroll_state()[1]

    # 复用真实绑定: 构造绑定表并找出鼠标通道的处理器
    kb = tui._build_keys()
    mouse_bindings = [
        b for b in kb.bindings
        if b.keys and str(getattr(b.keys[0], "value", "")) in (
            Keys.WindowsMouseEvent.value, Keys.Vt100MouseEvent.value)
    ]
    assert mouse_bindings, "鼠标通道未注册绑定"
    handler = mouse_bindings[-1].handler

    for etype in (MouseEventType.MOUSE_DOWN, MouseEventType.MOUSE_MOVE):
        handler(_FakeEvent(KeyPress(Keys.WindowsMouseEvent,
                                    _mouse_event(etype, MouseButton.LEFT))))
    assert tui._scroll_state()[1] == top_before

    # 同一处理器对滚轮则必须有反应
    handler(_FakeEvent(_wheel_event(up=True)))
    assert tui._scroll_state()[1] < top_before
    assert isinstance(QxtTUI, type)


def test_mouse_env_flag_disables_mouse_support():
    """TUAN_NO_MOUSE=1 时必须关掉鼠标上报 (恢复鼠标选中复制)。"""
    from tuan_cli.tui.tui import _env_flag

    with mock.patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("TUAN_NO_MOUSE", None)
        assert _env_flag("TUAN_NO_MOUSE") is False
        os.environ["TUAN_NO_MOUSE"] = "1"
        assert _env_flag("TUAN_NO_MOUSE") is True
        os.environ["TUAN_NO_MOUSE"] = "0"
        assert _env_flag("TUAN_NO_MOUSE") is False
        os.environ["TUAN_NO_MOUSE"] = "true"
        assert _env_flag("TUAN_NO_MOUSE") is True
        os.environ.pop("TUAN_NO_MOUSE", None)


def test_scroll_hint_mentions_mouse():
    """滚动提示应告诉用户可以用鼠标滚轮 (否则功能存在但无人知晓)。"""
    from tuan_cli.i18n import t

    hint = t("tui.scroll_back_hint") + t("tui.scroll_hint")
    assert ("滚轮" in hint) or ("wheel" in hint.lower()) or ("鼠标" in hint)