"""QxtTUI 启动信任确认 (Kimi/Claude Code 风格) + 加载屏贴顶布局的回归测试。

覆盖:
- prompt_trust 设置确认态后渲染确认卡片 (含路径/选项/提示)
- _resolve_trust: y/n/无效输入的行为与回调
- _handle_enter 在确认态挂起普通对话输入
- _render_boot 贴顶布局 (不再垂直居中 / 无 pad_top)
"""
import pytest

from qingxiaotuan.tui.tui import QxtTUI


class _FakeCtx:
    confirm = None


class _FakeAgent:
    def __init__(self):
        self.ctx = _FakeCtx()
        self.plan_mode = False


class _FakeConfig:
    _data = {"model.provider": "opencode-zen", "model.model": "deepseek-v4-flash-free"}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def api_key(self):
        return None


def _make_tui(workspace="."):
    return QxtTUI(
        lambda s: "ok",
        title="青小团",
        workspace=workspace,
        on_cancel=lambda: None,
        on_command=lambda c: None,
    )


def _flat(tui):
    rendered = tui._render_conversation()
    return "".join(seg for _, seg in rendered)


def test_prompt_trust_renders_confirm_card():
    tui = _make_tui(workspace="C:\\proj\\new")
    res = []
    tui.prompt_trust("C:\\proj\\new", project_name="new",
                     on_confirm=lambda ok: res.append(ok))
    assert tui._trust_pending is not None
    assert tui._trust_pending["workspace"] == "C:\\proj\\new"
    flat = _flat(tui)
    assert "首次访问此文件夹" in flat          # 标题
    assert "C:\\proj\\new" in flat             # 路径
    assert "y" in flat and "n" in flat         # 选项
    # 确认卡片渲染期间不显示欢迎盒
    assert "Welcome to 青小团" not in flat


def test_prompt_trust_hides_boot_loading_state():
    tui = _make_tui()
    assert tui._booting is True
    tui.prompt_trust("C:\\proj\\new", on_confirm=lambda ok: None)
    # 退出加载态: 确认卡片替代加载屏, 输入框可用
    assert tui._booting is False
    assert tui._boot_error is None


def test_resolve_trust_y_calls_back_true():
    tui = _make_tui()
    res = []
    tui.prompt_trust("C:\\proj\\new", on_confirm=lambda ok: res.append(ok))
    tui._resolve_trust("y")
    assert res == [True]
    assert tui._trust_pending is None


def test_resolve_trust_n_calls_back_false():
    tui = _make_tui()
    res = []
    tui.prompt_trust("C:\\proj\\new", on_confirm=lambda ok: res.append(ok))
    tui._resolve_trust("n")
    assert res == [False]
    assert tui._trust_pending is None


def test_resolve_trust_accepts_variants():
    for key, expected in [("Y", [True]), ("yes", [True]), ("N", [False]), ("no", [False])]:
        tui = _make_tui()
        res = []
        tui.prompt_trust("C:\\proj\\new", on_confirm=lambda ok: res.append(ok))
        tui._resolve_trust(key)
        assert res == expected, key


def test_resolve_trust_invalid_keeps_pending():
    tui = _make_tui()
    res = []
    tui.prompt_trust("C:\\proj\\new", on_confirm=lambda ok: res.append(ok))
    tui._resolve_trust("zzz")
    assert res == []                 # 回调未触发
    assert tui._trust_pending is not None  # 仍等待确认
    # 无效输入有提示日志
    assert any("无效输入" in str(e) for e in tui._events)


def test_handle_enter_suspended_during_trust_confirm():
    """确认态下回车只做信任解析, 不进入普通对话提交。"""
    tui = _make_tui()
    submitted = []
    tui.on_submit = lambda s: submitted.append(s) or "ok"
    res = []
    tui.prompt_trust("C:\\proj\\new", on_confirm=lambda ok: res.append(ok))

    # 模拟输入框有文本后回车
    tui._input.text = "y"
    # 直接走 _handle_enter 的内部路径: 用轻量桩 event, 避免真实 app 触发事件循环
    class _StubApp:
        def invalidate(self):
            pass

    class _Ev:
        current_buffer = tui._input.buffer
        app = _StubApp()

    tui._input.buffer.text = "y"
    tui._handle_enter(_Ev())
    assert res == [True]
    assert submitted == []   # 未进入对话提交


def test_boot_render_top_aligned_not_centered():
    """加载屏盒子贴顶: 首个内容行即盒子顶边, 无垂直居中 pad_top。"""
    tui = _make_tui()
    tui.set_boot_progress(40, "构建内核…")
    flat = tui._render_conversation()
    # 扁平化后首段应是盒子顶边 (╭), 前面没有 pad_top 空行
    first_texts = []
    for cls, seg in flat:
        if seg.strip():
            first_texts.append(seg)
            if len(first_texts) >= 3:
                break
    assert first_texts, "boot 渲染不应为空"
    assert "╭" in first_texts[0], "加载屏应以盒子顶边开头 (贴顶), 而不是垂直居中的空行"


def test_boot_error_top_aligned():
    tui = _make_tui()
    tui.boot_error("boom")
    flat = tui._render_conversation()
    first_texts = []
    for cls, seg in flat:
        if seg.strip():
            first_texts.append(seg)
            if len(first_texts) >= 2:
                break
    assert first_texts
    assert "╭" in first_texts[0]


def _rendered_line_widths(tui, box_width):
    """强制盒子宽度后渲染信任卡片, 返回每行显示宽度列表 (含 prompt 提示行)。"""
    from qingxiaotuan.tui.tui import _disp_width
    tui._box_width = lambda: box_width  # type: ignore[method-assign]
    tui.prompt_trust("C:\\very\\long\\path\\" + "x" * 80,
                     on_confirm=lambda ok: None)
    flat = "".join(seg for _, seg in tui._render_conversation())
    return [_disp_width(ln) for ln in flat.split("\n") if ln]


def test_trust_card_narrow_44_no_broken_border():
    """窄屏 (盒子宽度下限 44): 长路径/长描述/长选项都必须被截断, 任何行不超宽。"""
    widths = _rendered_line_widths(_make_tui(), 44)
    assert widths, "信任卡片渲染不应为空"
    assert all(w <= 44 for w in widths), (
        f"窄屏下有行宽超 44: {[w for w in widths if w > 44]}")
    # 长内容应确实被截断 (存在省略号), 而不是把边框挤出去
    assert "…" in _rendered_flat(_make_tui(), 44), (
        "窄屏下长描述/选项应显示省略号截断")


def test_trust_card_wide_120_full_width_rows():
    """宽屏 120: 边框行右缘对齐 120, 内容完整不截断。"""
    widths = _rendered_line_widths(_make_tui(), 120)
    assert widths
    # prompt 提示行是缩进副文本 (无边框), 其余盒子行都应为全宽
    box_rows = [w for w in widths if w < 120]
    assert len(box_rows) == 1, (
        f"宽屏下应有且仅有一行非全宽 (prompt 提示行), 实际 {len(box_rows)} 行: {box_rows}")
    assert all(w == 120 for w in widths if w != box_rows[0])
    assert "…" not in _rendered_flat(_make_tui(), 120), (
        "宽屏 120 下内容不应被截断")


def _rendered_flat(tui, box_width):
    from qingxiaotuan.tui.tui import _disp_width  # noqa: F401  (保持导入一致)
    tui._box_width = lambda: box_width  # type: ignore[method-assign]
    tui.prompt_trust("C:\\very\\long\\path\\" + "x" * 80,
                     on_confirm=lambda ok: None)
    return "".join(seg for _, seg in tui._render_conversation())
