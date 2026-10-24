"""TUI 全量重绘 (_reset_renderer) 回归测试: 不得退出备用屏 + 线程安全。

根因 (Bug: "TUI 输入框失去渲染"):
    ``prompt_toolkit.renderer.Renderer.reset()`` 的默认参数是
    ``leave_alternate_screen=True``。一旦漏传, 它会执行
    ``output.quit_alternate_screen()``, 把这个**全屏 TUI 踢出备用屏缓冲** ——
    终端回退到进入 TUI 之前的主屏内容, 而 TUI 仍按全屏绘制, 于是输入框
    (乃至整幅界面) "失去渲染" (Windows conpty / Windows Terminal 尤其明显)。
    ``set_ready`` / ``boot_error`` 在 boot→ready 切换时都会调用 _reset_renderer,
    故这是每次启动必经的路径。

线程安全 (同源):
    ``set_ready`` 由 ``_boot`` **后台线程** 调用 (见 cmd_chat), 而渲染循环在
    主线程。后台线程直接操作 renderer 会与主线程渲染竞争 —— 故运行态下必须
    把重置投递到主事件循环 (call_soon_threadsafe)。
"""
from unittest import mock

from tuan_cli.tui.tui import QxtTUI


def _tui():
    return QxtTUI(
        on_submit=lambda s: "ok",
        title="t",
        workspace=".",
        on_cancel=lambda: None,
        on_command=lambda c: None,
    )


class _FakeRenderer:
    """记录 erase/reset 的关键字参数, 复刻 prompt_toolkit Renderer 签名。"""

    def __init__(self):
        self.erase_kwargs = None
        self.reset_kwargs = None

    def erase(self, leave_alternate_screen=True):
        self.erase_kwargs = {"leave_alternate_screen": leave_alternate_screen}

    def reset(self, _scroll=False, leave_alternate_screen=True):
        self.reset_kwargs = {"leave_alternate_screen": leave_alternate_screen}


def test_reset_renderer_stays_in_alternate_screen():
    """_reset_renderer 必须对 erase() 与 reset() 都显式传 leave_alternate_screen=False。"""
    tui = _tui()
    r = _FakeRenderer()
    with mock.patch.object(tui._app, "renderer", r, create=True):
        tui._reset_renderer()
    assert r.erase_kwargs == {"leave_alternate_screen": False}
    # 关键回归点: 裸 reset() 会用默认 True 退出备用屏 -> 输入框失去渲染
    assert r.reset_kwargs == {"leave_alternate_screen": False}


def test_set_ready_does_not_quit_alternate_screen():
    """走完整 set_ready 路径后, renderer 仍未被要求退出备用屏。"""
    tui = _tui()
    r = _FakeRenderer()

    class _FakeCtx:
        confirm = None

    class _FakeAgent:
        def __init__(self):
            self.ctx = _FakeCtx()
            self.plan_mode = False

    class _FakeConfig:
        _d = {"model.provider": "opencode-zen", "model.model": "m", "agent.effort": "high"}

        def get(self, k, d=None):
            return self._d.get(k, d)

        def api_key(self):
            return None

    with mock.patch.object(tui._app, "renderer", r, create=True):
        tui.set_ready(_FakeConfig(), _FakeAgent(), ".", tools=None, no_key=False)
    assert r.reset_kwargs == {"leave_alternate_screen": False}


def test_reset_renderer_deferred_to_event_loop_when_running():
    """运行态下重置必须投递到主事件循环, 而非在调用线程直接操作 renderer。"""
    tui = _tui()
    r = _FakeRenderer()
    scheduled = []
    fake_loop = mock.Mock()
    fake_loop.call_soon_threadsafe.side_effect = lambda cb: scheduled.append(cb)
    fake_app = mock.Mock()
    fake_app.renderer = r
    fake_app.is_running = True
    fake_app.loop = fake_loop

    with mock.patch.object(tui, "_app", fake_app):
        tui._reset_renderer()

    # 此时还没真正执行 —— 说明是"投递"而非同步调用
    assert scheduled, "运行态下 _reset_renderer 未投递到事件循环"
    assert r.reset_kwargs is None, "运行态下不应在后台线程直接操作 renderer"
    # 执行回调后才真正重置, 且仍留在备用屏
    scheduled[0]()
    assert r.reset_kwargs == {"leave_alternate_screen": False}