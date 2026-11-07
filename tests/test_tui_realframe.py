"""TUI 真实帧渲染 + 真实键位管线端到端回归。

背景: 普通单元测试只调 _scrolled_lines()/_msg_to_lines() 等纯函数, 不经过
prompt_toolkit 的真实 Application 渲染管线 (Renderer / layout / key bindings),
因此"布局溢出 / 键位绑定 / 输入框聚焦 / 信任 Enter 确认"这类只有真实终端才
暴露的问题会被漏掉。本文件用 **真实** prompt_toolkit 管线:

  - create_pipe_input(): 把按键以真实转义序列写入管道, 驱动真实 key bindings;
  - Vt100_Output(StringIO): 捕获 Renderer 实际下发的 ANSI 转义序列;
  - QxtTUI.run() 在后台线程运行, 主线程脚本按键 → 断言渲染输出 / 状态迁移。

覆盖:
  1. 就绪态真实帧: 渲染出 codex 会话头 (">_ Tuan-CLI (vX)" + 目录), 无 ╭─╮ 盒;
  2. 信任确认态真实帧: 渲染出信任卡片;
  3. 信任卡 Enter 确认 → 进入工作区 (on_confirm=True, trust_pending=False);
  4. 真实输入 + Enter 提交 → on_submit 收到文本 (输入框聚焦 + 键位管线可用);
  5. 窄屏 (16/44 列) 真实帧不抛异常、渲染行不超宽 (逐行 wcwidth ≤ width)。
"""
import io
import re
import threading
import time

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

from tuan_cli.tui.tui import QxtTUI, USER_MESSAGE_BULLET

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _mk_tui(workspace="E:\\Tuan-CLI", **kw):
    """构造 QxtTUI (不启动 app.run()), 注入真实 output 捕获器。"""
    calls = {"submit": [], "confirm": [], "cancel": []}

    def on_submit(s):
        calls["submit"].append(s)
        return "ok"

    tui = QxtTUI(
        on_submit=on_submit,
        title="青小团",
        workspace=workspace,
        on_cancel=lambda: calls["cancel"].append(True),
        on_command=lambda c: None,
        **kw,
    )
    # 关闭 booting, 进入就绪态渲染 (不依赖 _boot 线程)
    tui._booting = False
    tui._boot_error = None
    tui._events = []
    tui._closed = False
    tui._confirm_pending = False
    tui._ask_pending = False
    tui._trust_pending = False
    return tui, calls


def _set_ready(tui):
    """填充就绪态会话头事件 (等价 set_ready 的事件填充)。"""
    try:
        tui._show_welcome()
    except AttributeError:
        tui._events.append([("", " ")])
        tui._events.append([("class:primary", "  >_ "),
                            ("class:textstrong", "Tuan-CLI"),
                            ("class:textdim", f" ({tui.VERSION})")])
        tui._events.append([("class:textdim", "     E:\\Tuan-CLI")])
        tui._events.append([("", "")])


def _render_frame(tui, width=80, height=24):
    """用真实 Renderer 渲染一帧到 StringIO, 返回纯文本行列表 (去 ANSI)。"""
    from prompt_toolkit.data_structures import Size
    out = io.StringIO()
    output = Vt100_Output(
        out,
        lambda: Size(columns=width, rows=height),
        term="xterm-256color",
        default_color_depth=None,
    )
    app = tui._app
    old_out = app.output
    old_running = getattr(app, "_is_running", None)
    old_in_term = getattr(app, "_running_in_terminal", None)
    try:
        app.output = output
        if app.renderer is not None:
            app.renderer.output = output
        app._output = output  # Application 内部缓存
        # _redraw 只在 _is_running 时真正渲染; 测试环境模拟运行态。
        app._is_running = True
        app._running_in_terminal = False
        # 先同步布局尺寸再渲染
        from prompt_toolkit.renderer import Renderer
        if app.renderer is None:
            app.renderer = Renderer(
                app.layout, app.output, app.terminal_size,
                app.art, app.search_buffer, app._style_transformation,
                app.include_default_pygments_style,
            )
        # 手动渲染一帧: 直接调 renderer.render (不经 _redraw, 后者需 app.context
        # 非空才真正渲染, 而未 run 的 app 其 context 为 None)。需在 asyncio 循环内,
        # 因为 TextArea 的 buffer 加载历史会 create_background_task 需要运行循环。
        import asyncio
        from prompt_toolkit.application.current import set_app

        async def _do_render() -> None:
            with set_app(app):
                app.renderer.render(app, app.layout)

        asyncio.run(_do_render())
    finally:
        app.output = old_out
        if app.renderer is not None:
            app.renderer.output = old_out
        app._is_running = old_running
        app._running_in_terminal = old_in_term
    data = out.getvalue()
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", data)
    text = text.replace("\x1b[?25l", "").replace("\x1b[?25h", "")
    return text.split("\n"), data


# ------------------------------------------------------------------ 真实管线
def test_real_pipe_ready_submit():
    """真实键位管线: 就绪态输入文本 + Enter → on_submit 收到文本。"""
    tui, calls = _mk_tui()
    _set_ready(tui)
    app = tui._app
    with create_pipe_input() as pipe:
        old_in = app.input
        app.input = pipe
        thread = threading.Thread(target=lambda: tui.run(), daemon=True)
        try:
            thread.start()
            time.sleep(0.3)
            pipe.send_text("hello\r")
            time.sleep(0.6)
        finally:
            app.input = old_in
            tui.close()
            thread.join(timeout=3)
    assert calls["submit"], "on_submit 未收到文本 (真实键位管线应可提交)"
    assert calls["submit"][0] == "hello"


def test_realframe_ready_header_no_ascii_box():
    """就绪态真实帧: 渲染出 codex 会话头, 无 ╭─╮ ASCII 盒。"""
    tui, calls = _mk_tui()
    _set_ready(tui)
    lines, _ = _render_frame(tui, width=80, height=24)
    flat = "\n".join(lines)
    assert ">_ Tuan-CLI" in flat, "就绪态应渲染 codex 会话头标题"
    assert "╭" not in flat and "╮" not in flat, "就绪态不应有 ASCII 盒残留"


def test_realframe_trust_card_enter_accepts():
    """信任确认态真实帧 + Enter → on_confirm(True), 进入工作区。

    回归点: 此前空输入 + Enter 在 `if not text: return` 提前退出, 永远到不了
    信任分支 → 信任卡卡死。真实键位管线验证修复。
    """
    tui, calls = _mk_tui()
    tui.prompt_trust("E:\\Tuan-CLI", on_confirm=calls["confirm"].append)
    assert tui._trust_pending is not None
    lines, _ = _render_frame(tui, width=80, height=24)
    flat = "\n".join(lines)
    assert ("信任此文件夹" in flat or "trust" in flat.lower()), \
        "信任态真实帧应渲染信任卡片文案"
    # 真实键位: 空输入 + Enter 确认 (默认高亮 = 信任)
    app = tui._app
    with create_pipe_input() as pipe:
        old_in = app.input
        app.input = pipe
        thread = threading.Thread(target=lambda: tui.run(), daemon=True)
        try:
            thread.start()
            time.sleep(0.3)
            pipe.send_text("\r")  # 空输入 + Enter
            time.sleep(0.6)
        finally:
            app.input = old_in
            tui.close()
            thread.join(timeout=3)
    assert tui._trust_pending is None, "信任卡应按 Enter 关闭 (清空 pending)"
    assert calls["confirm"], "on_confirm 应被调用 (信任=True)"
    assert calls["confirm"][0] is True


def test_realframe_narrow_width_no_overflow():
    """窄屏 (16/44 列) 真实帧: 渲染行不超宽 (逐行 wcwidth ≤ width)。"""
    from wcwidth import wcswidth
    for width in (16, 44, 60, 80, 200):
        tui, calls = _mk_tui()
        _set_ready(tui)
        tui.append_log(f"{USER_MESSAGE_BULLET}" + "测" * 60)
        lines, _ = _render_frame(tui, width=width, height=24)
        for line in lines:
            w = wcswidth(line.rstrip("\r"))
            if w >= 0:
                assert w <= width, f"width={width}: 行超宽 {w}>{width}: {line!r}"
        tui.close()
