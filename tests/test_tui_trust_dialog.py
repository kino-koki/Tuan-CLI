"""TUI 信任确认对话框回归测试 (防"对话框又没了")。

背景: cmd_chat._boot 用 ``hasattr(tui, "prompt_trust")`` 判断是否显示
"首次访问未知目录" 的信任确认卡片。该方法曾在一次 TUI 重写中被误删,
导致 hasattr 恒为 False、确认对话框被静默跳过 (用户观感"对话框又没了")。
本文件锁定契约: 方法必须存在、挂起态生效、y/n 正确回调。
"""
from tuan_cli.tui.tui import QxtTUI


def _tui():
    tui = QxtTUI(on_submit=lambda _t: "ok")
    tui._booting = False
    tui._boot_error = None
    return tui


def test_prompt_trust_method_exists():
    """cmd_chat 依赖 hasattr(tui, "prompt_trust") —— 方法必须存在。"""
    tui = _tui()
    assert hasattr(tui, "prompt_trust")
    assert callable(tui.prompt_trust)
    assert hasattr(tui, "_resolve_trust")
    assert hasattr(tui, "_render_trust_confirm")


def test_prompt_trust_enters_pending_state():
    """prompt_trust 应挂起确认态并退出加载态 (否则输入框被 _ready 过滤隐藏)。"""
    tui = _tui()
    tui._booting = True
    tui.prompt_trust("E:/proj", project_name="proj", on_confirm=lambda _ok: None)
    assert tui._trust_pending is not None
    assert tui._trust_pending["workspace"] == "E:/proj"
    assert tui._booting is False          # 关键: 卡片可见, 输入框不被隐藏


def test_resolve_trust_yes_calls_confirm_true():
    tui = _tui()
    got = []
    tui.prompt_trust("E:/proj", on_confirm=got.append)
    tui._resolve_trust("y")
    assert got == [True]
    assert tui._trust_pending is None     # 确认后清态, 允许后续 set_ready


def test_resolve_trust_no_calls_confirm_false():
    tui = _tui()
    got = []
    tui.prompt_trust("E:/proj", on_confirm=got.append)
    tui._resolve_trust("n")
    assert got == [False]


def test_resolve_trust_invalid_keeps_pending():
    """非法输入不消费确认态 (继续等待有效 y/n)。"""
    tui = _tui()
    got = []
    tui.prompt_trust("E:/proj", on_confirm=got.append)
    tui._resolve_trust("maybe")
    assert got == []
    assert tui._trust_pending is not None


def test_trust_confirm_card_renders_with_border():
    """确认卡片应渲染出 codex 无边框背景块 (render_menu_surface 同款), 不抛异常。

    对齐 codex selection_popup_common.rs: 弹窗是整块 ``user_message_style`` 背景
    (``Block::default().style(...)``, 无 border), 因此**不含** ``╭``/``╯`` 边框字符,
    而是每行片段携带背景色 ``bg:#333B47`` (USER_MESSAGE_BG)。
    """
    tui = _tui()
    tui.prompt_trust("E:/some/workspace", on_confirm=lambda _ok: None)
    segs = tui._render_trust_confirm()
    text = "".join(seg for cls, seg in segs)
    assert "╭" not in text and "╯" not in text   # 无边框 (对齐 codex 悬浮背景块)
    assert any("bg:#333B47" in cls for cls, _ in segs)   # 背景填充
    assert "E:/some/workspace" in text


def test_trust_pending_hides_conversation_shows_card():
    """挂起确认态时对话区应渲染确认卡片 (而非对话内容)。"""
    tui = _tui()
    tui.prompt_trust("E:/proj", on_confirm=lambda _ok: None)
    lines = tui._scrolled_lines()
    flat = "".join(seg for line in lines for _, seg in line)
    assert "E:/proj" in flat


# ---------------------------------------------------------------- 不得阻塞就绪
class _Cfg:
    def get(self, k, d=None):
        return {"model.provider": "sensenova", "model.model": "x"}.get(k, d)

    def api_key(self):
        return ""


class _Ag:
    plan_mode = False

    class ctx:
        confirm = None


def test_trust_prompt_does_not_block_ready():
    """信任确认**不得阻塞就绪**: 挂出卡片后输入框仍可见。

    回归: 早期 `_boot` 在确认分支里 `return` 且不调用 `set_ready`,
    结果确认态下 TUI 既没进正常对话、用户不按 y/n 就永久卡住 ——
    表现即"所有 TUI 都没有输入框"。现在确认卡片只是提示, 就绪流程照常推进。
    """
    from prompt_toolkit.layout import ConditionalContainer

    tui = _tui()
    tui.prompt_trust("E:/proj", on_confirm=lambda _ok: None)
    tui.set_ready(_Cfg(), _Ag(), "E:/proj", tools=["read_file"])
    assert tui._booting is False
    assert tui._boot_error is None
    vis = [bool(c.filter()) for c in tui._app.layout.walk()
           if isinstance(c, ConditionalContainer)]
    assert True in vis, "确认态下输入框容器仍必须可见"


def test_resolve_trust_reports_whether_consumed():
    """_resolve_trust 需返回"是否消费了本次输入", 供上层决定是否自动信任并继续。"""
    tui = _tui()
    tui.prompt_trust("E:/proj", on_confirm=lambda _ok: None)
    assert tui._resolve_trust("hello") is False   # 非 y/n → 不消费, 保持确认态
    assert tui._trust_pending is not None
    assert tui._resolve_trust("y") is True        # y → 消费并清态
    assert tui._trust_pending is None


def test_resolve_trust_no_consumes():
    tui = _tui()
    got = []
    tui.prompt_trust("E:/proj", on_confirm=got.append)
    assert tui._resolve_trust("n") is True
    assert got == [False]
