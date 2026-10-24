"""TUI 溢出不变式测试 —— 任何渲染路径都不得产出超宽行。

背景 —— 为什么需要这个文件:
    对话区/审计面板的 Window 是 `wrap_lines=True`, 长文本软换行是**正常**的
    (长消息本就该折行), 因此"内容超宽"本身不是 bug。真正的 bug 是
    `wrap_lines=False` 的**单行控件** (顶栏 / 底栏 / slash 面板 / diff 面板):
    它们不会软换行, 一旦超宽就被终端折成两行, 把整幅全屏布局顶错位 ——
    用户看到的就是"文字溢出 / 界面错乱"。

    本文件按控件类型分别断言:
      - 单行控件: 每一行的显示宽度必须 ≤ 终端列宽;
      - 折行控件: 不做宽度断言 (交给 `_line_heights` + 虚拟视口切片处理),
        但要求卡片类内容自带折行, 不依赖控件软换行来救。

覆盖的渲染路径: 欢迎盒 / 启动屏 / 信任卡片 / 命令确认卡片 / 模型提问卡片 /
slash 面板 / diff 面板 / 顶栏 / 底栏 / 审计面板标题 / 对话区流式与工具行。
"""
from unittest import mock

import pytest
from prompt_toolkit.layout.controls import FormattedTextControl

from tuan_cli.i18n import t
from tuan_cli.tui.tui import QxtTUI, _disp_width


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


class _FakeSize:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class _FakeTTY:
    def __init__(self, columns, rows):
        self._size = _FakeSize(columns, rows)
        self._buf = []

    def get_size(self):
        return self._size

    def get_default_color_depth(self):
        return 24

    def write(self, data):
        self._buf.append(data)

    def flush(self):
        pass

    def isatty(self):
        return True

    def fileno(self):
        return 0


class _FakeApp:
    def __init__(self, columns, rows=24):
        self._size = _FakeSize(columns, rows)
        self.is_running = False
        self._inval = 0

    class _Out:
        def __init__(self, size):
            self._size = size

        def get_size(self):
            return self._size

    @property
    def output(self):
        return _FakeApp._Out(self._size)

    def invalidate(self):
        self._inval += 1


# 从 200 列一路压到 12 列 —— 覆盖 80 列常规、60/44 窄屏、以及 conpty 极窄窗口
WIDTHS = [200, 120, 100, 80, 60, 44, 40, 32, 24, 20, 16, 12]

LONG_ASCII = "x" * 500
LONG_CJK = "中文测试内容" * 80


def _make(width, rows=24, n=3):
    tui = QxtTUI(
        on_submit=lambda s: "ok",
        title="t",
        workspace=".",
        on_cancel=lambda: None,
        on_command=lambda c: None,
    )
    tui._app = _FakeApp(width, rows)
    tui.set_ready(_FakeConfig(), _FakeAgent(), ".")
    for i in range(n):
        tui.append_log(f"MSG{i:03d}")
    return tui


def _rows_of(flat):
    """把扁平 [(cls,text)] 按 \\n 拆成逻辑行。"""
    out, cur = [], []
    for cls, seg in flat:
        parts = seg.split("\n")
        for i, p in enumerate(parts):
            if i > 0:
                out.append(cur)
                cur = []
            if p:
                cur.append((cls, p))
    out.append(cur)
    return out


def _wide_rows(rows):
    """返回 [(显示宽度, 文本)] —— 显示宽度超出 limit 的。"""
    bad = []
    for r in rows:
        w = sum(_disp_width(s) for _, s in r)
        if w > 0:
            bad.append((w, "".join(s for _, s in r)))
    return bad


def _assert_rows_fit(rows, width, what):
    for w, txt in _wide_rows(rows):
        assert w <= width, f"{what} @w={width}: 行宽 {w} > {width} —— {txt[:60]!r}"


# ============================================================ 单行控件


@pytest.mark.parametrize("width", WIDTHS)
def test_header_never_exceeds_width(width):
    """顶栏是 height=1 单行控件 —— 超宽即被终端折行、布局错位。

    三个状态分支都要覆盖: 启动中 (转圈帧 + i18n 串)、思考中 (月亮帧 + i18n)、
    就绪; 并叠加超长模型名与 plan 徽标 (最容易撑爆顶栏的组合)。
    """
    for state in ("ready", "booting", "busy"):
        tui = _make(width)
        if state == "booting":
            tui._booting = True
        elif state == "busy":
            tui._busy = True
            tui._streaming = True
        tui._model_label = "some-very-long-provider-name/" + "m" * 200
        tui._plan_mode = True
        rows = _rows_of(tui._render_header())
        _assert_rows_fit(rows, width, f"header/{state}")


@pytest.mark.parametrize("width", WIDTHS)
def test_footer_never_exceeds_width(width):
    """底栏同height=1；长模型名/长目录/长状态提示都不得溢出。"""
    tui = _make(width)
    tui._model_label = "provider-name-that-is-long/" + "z" * 200
    tui.workspace = "/some/really/deep/nested/workspace/path/for/testing"
    tui._no_key = True
    tui._no_key_env = "A_VERY_LONG_ENVIRONMENT_VARIABLE_NAME"
    tui._scroll_top = 5          # 触发回卷指示 (底栏最长的分支)
    rows = _rows_of(tui._render_footer())
    _assert_rows_fit(rows, width, "footer")


@pytest.mark.parametrize("width", WIDTHS)
def test_slash_menu_never_exceeds_width(width):
    """slash 面板 wrap_lines=False —— 命令名本身也必须裁进宽度预算。

    旧实现只裁描述、命令名 `mark+cmd` 全宽输出, 窄屏下整行超宽。
    """
    tui = _make(width)
    tui._slash_items = ["/help", "/model", "/provider", "/clear",
                        "/compact", "/init", "/login", "/logout"]
    tui._command_meta = {c: LONG_CJK for c in tui._slash_items}
    tui._slash_open = True
    tui._slash_index = 2
    tui._slash_scroll = 0
    rows = _rows_of(tui._render_slash_menu())
    _assert_rows_fit(rows, width, "slash_menu")


@pytest.mark.parametrize("width", WIDTHS)
def test_diff_panel_never_exceeds_width(width):
    """diff 面板 wrap_lines=False —— 中文 diff 行必须按显示宽度裁剪。

    旧实现用 `raw[:width]` 按**字符数**截断, 一个汉字占2 列, 中文注释行
    实际宽度可达预算的两倍, 直接把面板顶出终端右边界。
    """
    tui = _make(width)
    tui._diff_visible = True
    tui._diff_fetched_at = 1e18          # 阻止真跑 git
    tui._diff_error = ""
    tui._diff_summary = t("tui.diff_summary", files=9, added=508, removed=75)
    tui._diff_cache = [
        ("class:primary", "diff --git a/" + LONG_CJK + " b/x"),
        ("class:diffadd", "+" + LONG_CJK),
        ("class:diffdel", "-" + LONG_ASCII),
        ("class:accent", "@@" + LONG_ASCII),
    ]
    budget = max(1, tui._diff_panel_width())
    rows = _rows_of(tui._render_diff_panel())
    _assert_rows_fit(rows, budget, "diff_panel")


@pytest.mark.parametrize("width", WIDTHS)
def test_diff_error_line_clipped(width):
    """diff 错误信息 (含路径/异常) 同样必须裁剪。"""
    tui = _make(width)
    tui._diff_visible = True
    tui._diff_fetched_at = 1e18
    tui._diff_error = "fatal: not a git repository: " + LONG_CJK
    tui._diff_cache = []
    budget = max(1, tui._diff_panel_width())
    rows = _rows_of(tui._render_diff_panel())
    _assert_rows_fit(rows, budget, "diff_error")


# ============================================================ 卡片类 (自带折行)


@pytest.mark.parametrize("width", WIDTHS)
def test_welcome_box_rows_fit_width(width):
    """欢迎盒/加载屏盒: 每一行(含左右边框)都必须恰好 ≤ 终端列宽。

    这类内容最终进入对话区 (wrap_lines=True), 一旦某行超宽就会被软换行,
    右边框 `│` 掉到下一行 —— 观感就是"文字溢出 / 盒子错位"。
    """
    tui = _make(width)
    tui._events = []
    tui._show_welcome()
    for r in tui._events:
        _assert_rows_fit([r], width, "welcome_box")


@pytest.mark.parametrize("width", WIDTHS)
def test_boot_screen_rows_fit_width(width):
    """启动屏: 进度条长度必须随宽度自适应 (旧实现固定 30 格 = 37 列)。"""
    tui = _make(width)
    for pct in (0, 37, 100):
        tui._booting = True
        tui._boot_progress = pct
        tui._boot_error = None
        tui._boot_status = LONG_CJK
        _assert_rows_fit(_rows_of(tui._render_boot()), width, f"boot/{pct}")
    # 启动失败态: 错误详情也可能很长
    tui._boot_error = "OSError: " + LONG_CJK
    _assert_rows_fit(_rows_of(tui._render_boot()), width, "boot/error")


@pytest.mark.parametrize("width", WIDTHS)
def test_trust_card_rows_fit_width(width):
    """信任卡片: 超长工作区路径不得把右边框顶飞。"""
    tui = _make(width)
    tui._trust_pending = {
        "workspace": "/very/long/path/" + "deep/" * 80 + "project",
        "on_confirm": lambda x: None,
    }
    tui._trust_index = 0
    _assert_rows_fit(_rows_of(tui._render_trust_confirm()), width, "trust_card")


@pytest.mark.parametrize("width", WIDTHS)
def test_confirm_card_rows_fit_width(width):
    """命令确认卡片: 长命令 (折行铺开) 每行仍须 ≤ 宽度。"""
    tui = _make(width)
    tui._confirm_pending = {
        "prompt": "rm -rf /" + "a" * 400 + "\nsecond " + LONG_CJK,
        "expected": "YES",
        "on_confirm": lambda x: None,
    }
    _assert_rows_fit(_rows_of(tui._render_confirm_card()), width, "confirm_card")


@pytest.mark.parametrize("width", WIDTHS)
def test_ask_card_rows_fit_width(width):
    """模型提问卡片: 长问题 + 超长选项每行须 ≤ 宽度。"""
    tui = _make(width)
    tui._ask_pending = {
        "question": LONG_CJK + "\n" + LONG_ASCII,
        "options": [LONG_ASCII, LONG_CJK, "短选项", "another option"],
    }
    tui._ask_index = 1
    _assert_rows_fit(_rows_of(tui._render_ask_card()), width, "ask_card")


# ============================================================ 辅助函数


def test_clip_dw_zero_width_returns_empty():
    """`_clip_dw(s, 0)` 必须返回空串。

    旧实现返回 "…" (1 列), 在"预算已用尽"的调用点凭空多出 1 列 ——
    这正是 slash 面板在 12 列终端下仍有一行 13 列的原因。
    """
    tui = _make(80)
    assert tui._clip_dw("hello", 0) == ""
    assert tui._clip_dw("", 0) == ""
    assert _disp_width(tui._clip_dw("hello", 0)) == 0


def test_clip_dw_one_width_is_single_ellipsis():
    tui = _make(80)
    assert tui._clip_dw("hello", 1) == "…"
    assert _disp_width(tui._clip_dw("hello", 1)) == 1


@pytest.mark.parametrize("n", [1, 2, 3, 5, 10])
def test_clip_dw_respects_display_width(n):
    """裁剪结果必须 ≤ n 列 (CJK 按 2 列计)。"""
    tui = _make(80)
    for s in ("hello world", "中文测试内容", "a中b文c", "🎉🎉🎉 emoji"):
        assert _disp_width(tui._clip_dw(s, n)) <= n, (s, n)


def test_box_row_respects_inner_width():
    """`_box_row` 输出宽度 = 1(左框) + pad + body + 补白 + 1(右框) ≤ inner+2。

    旧实现硬编码 `-2` 扣内边距, 且inner 很小时补空格数为负 → 整行仍超宽。
    """
    tui = _make(80)
    for inner in (2, 3, 4, 6, 10, 40):
        segs = [("class:text", LONG_CJK)]
        row = tui._box_row(segs, inner, "  ")
        w = sum(_disp_width(s) for _, s in row)
        assert w <= max(2, inner) + 2, f"inner={inner}: 行宽 {w}"


def test_box_budget_floor_on_tiny_terminal():
    """极窄终端 (conpty 窗口被拖到最小) 下盒子预算不低于 4 列。

    否则 `width-2` 为负会让边框退化成 `╭╮`, 上下边框对不齐。
    """
    tui = _make(2)
    width, inner = tui._box_budget()
    assert width >= 4
    assert inner >= 2
    assert inner == width - 2


# ============================================================ 对话区 (折行控件)


def test_conversation_long_lines_are_wrapped_not_clipped():
    """对话区长消息走软换行 (正常), 但**每屏行数**必须仍等于视口高。

    这是回卷正确性的前提: 若长行折行数与 `_line_heights` 估算不符,
    切片就会露白/跳行。
    """
    tui = _make(80)
    for i in range(40):
        tui.append_log(f"MSG{i:03d} " + LONG_ASCII)
    tui._log_window.measured_height = 20
    screen = tui._viewport_slice(tui._scrolled_lines())
    heights = tui._line_heights(screen)
    assert sum(heights) <= 20
    assert sum(heights) > 0


def test_stream_line_fits_one_row():
    """流式缓冲按可视宽度裁剪 —— "本应一行"的元素不该被折成多行。

    否则用户会以为界面在重复刷同一段内容。
    """
    tui = _make(80)
    tui._events = []# 去掉欢迎盒, 只留流式内容
    tui._streaming = True
    tui._stream_buf = LONG_CJK
    rows = tui._scrolled_lines()
    assert rows
    for line in rows:
        w = sum(_disp_width(s) for _, s in line)
        assert w <= max(8, tui._log_width()), f"流式行宽 {w}"


def test_tool_run_line_fits_one_row():
    """在途工具行 (长工具名 + 耗时) 同样裁到一屏宽。"""
    tui = _make(80)
    tui._events = []              # 去掉欢迎盒, 只留本轮内容
    tui._turn_tool_lines = ["▸ " + "t" * 300 + " (9.9s)"]
    tui._tool_detail = True
    tui._streaming = False
    rows = tui._scrolled_lines()
    assert rows, "本轮工具行应进入对话区"
    for line in rows:
        w = sum(_disp_width(s) for _, s in line)
        assert w <= max(8, tui._log_width()), f"工具行宽 {w}"


# ============================================================ 宽度实测


def test_log_width_prefers_measured():
    """对话区宽度优先用实测值 —— diff 面板会吃掉一块, 估算必然偏大。

    估算偏大 → 长消息折行数算少 → 虚拟视口切片错位 (回卷露白/跳行)。
    """
    tui = _make(120)
    assert tui._log_width() > 0                    # 未实测时走估算
    tui._log_window.measured_width = 71
    assert tui._log_width() == 71                  # 实测后精确


def test_log_width_falls_back_when_unmeasured():
    """实测值缺失/非法时必须回退到估算, 不能返回 0 或负数。"""
    tui = _make(100)
    tui._log_window.measured_width = 0
    assert tui._log_width() > 0
    tui._log_window.measured_width = -5
    assert tui._log_width() > 0


def test_measured_window_records_both_dims():
    """`_MeasuredWindow` 必须同时记录宽和高 (视口切片两都要精确)。

    记录错字段的话回卷就会露白/跳行: 高度算错 → 每屏行数不对; 宽度算错 →
    长消息折行数不对。这里直接构造一个窗口并喂真实 `WritePosition`。
    """
    from prompt_toolkit.layout.mouse_handlers import MouseHandlers
    from prompt_toolkit.layout.screen import Screen, WritePosition

    from tuan_cli.tui.tui import _MeasuredWindow

    win = _MeasuredWindow(FormattedTextControl(lambda: [("", "hi")]))
    assert win.measured_width == 0 and win.measured_height == 0

    win.write_to_screen(
        Screen(initial_width=100, initial_height=30),
        MouseHandlers(),
        WritePosition(xpos=0, ypos=0, width=77, height=23),
        "", True, 0,
    )
    assert win.measured_width == 77
    assert win.measured_height == 23

    # 宽/高为 0 的退化 WritePosition 不得覆盖已记录的精确值。
    # (负值不可能出现 —— prompt_toolkit 的 WritePosition.__init__ 自身就
    #assert height >= 0。)
    win.write_to_screen(
        Screen(initial_width=100, initial_height=30),
        MouseHandlers(),
        WritePosition(xpos=0, ypos=0, width=0, height=0),
        "", True, 0,
    )
    assert win.measured_width == 77
    assert win.measured_height == 23