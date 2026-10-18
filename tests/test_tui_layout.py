"""TUI 对话区排版 + 双 ✨ 修复 + /命令 提示 回归测试。"""

from tuan_cli.tui.tui import QxtTUI, USER_MESSAGE_BULLET


def _tui(**kw):
    kw.setdefault("on_submit", lambda _text: "ok")
    tui = QxtTUI(**kw)
    # 跳过加载屏状态, 直接测对话区渲染
    tui._booting = False
    tui._boot_error = None
    return tui


# ---------------------------------------------------------------- 双 ✨ 修复

def test_msg_to_lines_no_double_bullet():
    """用户消息已带 ✨ 前缀 (事件角色标记) 时, 渲染不再叠加第二颗。"""
    tui = _tui()
    # 事件写入时带前缀 (append_log 路径); 最早版行为: 无左缩进, 正文直接贴行首
    lines = tui._msg_to_lines("user", f"{USER_MESSAGE_BULLET}你好")
    first = "".join(seg for _, seg in lines[0])
    assert first.count("✨") == 1
    assert first == "✨ 你好"
    # 纯文本 (防御) 渲染时补一颗
    lines2 = tui._msg_to_lines("user", "你好")
    first2 = "".join(seg for _, seg in lines2[0])
    assert first2 == "✨ 你好"


def test_msg_to_lines_user_block_bg():
    """用户消息块带暖金底 (气泡感), 首行与续行一致 (最早版行为: 首行即金底正文)。"""
    tui = _tui()
    lines = tui._msg_to_lines("user", f"{USER_MESSAGE_BULLET}第一行\n第二行")
    assert lines[0][0] == ("class:roleuser bg:#2b2416", "✨ 第一行")  # 首行金底正文
    assert any("bg:#2b2416" in cls for cls, _ in lines[1])  # 续行金底延续


# ---------------------------------------------------------------- 排版分组

def test_scrolled_lines_separates_message_blocks():
    """消息块之间的空行规则 (对标 Claude Code 的紧凑排版)。

    两条规则:
    1. 提问与其回答**之间不留空行** —— 一次问答是一个整体, 空行会把它拆成
       两个视觉区块, 这是"行距偏松"的最大来源;
    2. 其余块间仍留一个空行, 保证多轮对话可读。
    """
    tui = _tui()
    tui.append_log("✨ 第一问")
    tui.append_log("第一答")
    tui.append_log("✨ 第二问")
    screen = tui._scrolled_lines()

    # 问1→答1 不空行; 答1→问2 留 1 个空行
    blank_rows = sum(1 for line in screen if not line)
    assert blank_rows == 1, "问答之间不应有空行, 仅轮次之间保留一个"

    flat = ["".join(seg for _, seg in line) for line in screen]
    # 提问与紧邻的回答必须物理相邻
    i_q = next(i for i, r in enumerate(flat) if "第一问" in r)
    i_a = next(i for i, r in enumerate(flat) if "第一答" in r)
    assert i_a == i_q + 1, "提问与回答应紧邻, 中间不得有空行"


def test_scrolled_lines_no_double_sparkle_in_full_pipeline():
    """全链路 (append_log -> scrolled) 用户消息只渲染一颗 ✨。"""
    tui = _tui()
    tui.append_log("✨ 你好")
    screen = tui._scrolled_lines()
    flat = "".join(seg for line in screen for _, seg in line)
    assert flat.count("✨") == 1
    assert "✨ 你好" in flat


# ---------------------------------------------------------------- /命令 提示

def test_slash_completer_uses_meta():
    """补全菜单 display_meta 取命令描述表。"""
    from tuan_cli.tui.tui import _SlashCompleter
    from prompt_toolkit.document import Document

    comp = _SlashCompleter(
        ["/help", "/tools"],
        {"/help": "显示帮助", "/tools": "列出可用工具"},
    )
    completions = list(comp.get_completions(Document("/"), None))
    meta = {c.text: str(c.display_meta) for c in completions}
    assert "显示帮助" in meta.get("/help", "")
    assert "列出可用工具" in meta.get("/tools", "")


def test_slash_command_meta_covers_major_commands():
    """命令描述表覆盖常用命令 (补全菜单与 /help 共用)。"""
    from tuan_cli.cli.cmd_slash import slash_command_meta, list_slash_commands

    meta = slash_command_meta()
    names = list_slash_commands()
    for essential in ("/help", "/model", "/effort", "/plan", "/mode", "/clear", "/compact"):
        assert essential in names, f"命令表缺 {essential}"
    for cmd in ("/help", "/model", "/effort", "/plan", "/mode", "/clear", "/compact"):
        assert meta.get(cmd), f"{cmd} 缺描述"


def test_help_text_covers_command_names():
    """/help 输出覆盖全部内置命令 (SLASH_COMMAND_NAMES 与 _HELP 同步)。"""
    from tuan_cli.cli.cmd_slash import _HELP, SLASH_COMMAND_NAMES

    for name in SLASH_COMMAND_NAMES:
        assert name in _HELP, f"/help 未收录 {name}"
