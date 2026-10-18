"""青小团 TUI —— 单一 Application (启动加载屏 + 对话界面)。

以 splash.py 的蓝色吉祥物加载屏为基底, 扩展出对话模块:
  - 启动期: 内嵌加载屏 (蓝字吉祥物 ▐█▛█▛█▌ + braille 转圈 + 进度条 + Ctrl-C 退出)
  - 就绪后: 对话界面 (对话区 + 输入栏 + 底部上下文条), 无侧栏, 保持简陋。

单一 Application / 事件循环: 启动加载屏与对话界面共用同一 App, 杜绝
Splash→TUI 双全屏 alt-screen 切换在 Windows Terminal(conpty) 下的崩溃与卡顿。
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from wcwidth import wcswidth as _wcswidth_impl  # 终端显示宽度 (prompt_toolkit 同源依赖)
except Exception:  # noqa: BLE001
    _wcswidth_impl = None  # type: ignore[assignment]


def _wcswidth(s: str) -> int:
    """兼容包装: 有 wcwidth 用 wcwidth, 否则退化为逐字符估算。"""
    if _wcswidth_impl is not None:
        return _wcswidth_impl(s)
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)

from ..i18n import t
from ..core.prompt_tier import PROVIDER_CONTEXT_WINDOWS

_HAS_PT = False
try:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import (ConditionalContainer, Dimension, HSplit,
                                        Layout, VSplit, Window)
    from prompt_toolkit.filters import Condition, to_filter
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.data_structures import Point
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import TextArea
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.output.base import DummyOutput
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.completion import Completer, Completion
    _HAS_PT = True
except Exception:
    # prompt_toolkit 是可选依赖, 缺失时本模块仍必须可导入 —— cli/cmd_chat.py 会
    # import 本文件取配色/常量, 若在 `class _SlashCompleter(Completer)` 处 NameError,
    # 整个 CLI 会连带炸掉。这里补占位符号: 类定义能通过, 真正用到补全时才报清晰错误。
    _HAS_PT = False

    class Completer:  # type: ignore[no-redef]
        """占位基类: prompt_toolkit 缺失时仅为让下面的类定义通过。"""

    def Completion(*args, **kwargs):  # type: ignore[no-redef]
        """占位构造器: prompt_toolkit 缺失时给出可读错误, 而不是 NameError。"""
        raise RuntimeError(
            "prompt_toolkit 未安装, 无法使用 TUI 输入补全; 安装 prompt_toolkit 或改用 CLI 模式"
        )


# ---- 配色: 青小团自研的深色视觉语言 ----
# 主界面观感与 Kimi Code 保持一致的清爽蓝色系; 法定署名见仓库根 NOTICE。
_PRIMARY = "#4FA8FF"      # 主品牌蓝: 盒子边框 / 吉祥物 / 标题 / 输入框提示符
_BLUE_DIM = "#5E97CC"     # 次级蓝: 盒子副标题 / 信息行

# 通用界面 (对话 / 输入 / 底栏) 的深色字号层次
_TEXT = "#E0E0E0"
_TEXT_STRONG = "#F5F5F5"
_DIM = "#888888"
_MUTED = "#6B6B6B"
_BORDER = "#5A5A5A"
_ACCENT = "#5BC0BE"
_SUCCESS = "#4EC87E"
_WARNING = "#E8A838"
_ERROR = "#E85454"
_ROLEUSER = "#FFCB6B"
_SHELL = "#BD93F9"

try:
    from .. import __version__  # pyproject.toml 的真实版本
    VERSION = f"v{__version__}"
except Exception:  # noqa: BLE001
    VERSION = "v0.3.1"

#: TUI 启动时写入的终端窗口/标签标题 (Windows Terminal 标签页 / ConHost 标题栏)。
#: 环境变量 TUAN_TERMINAL_TITLE 可覆盖 (留空则不修改标题)。
TERMINAL_TITLE = os.environ.get("TUAN_TERMINAL_TITLE", "").strip() or "Tuan-CLI"

# 加载屏转圈帧
_SPLASH_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# 思考态月亮转圈帧 (每帧 90ms, 8 相走完一圈约 0.72s, 观感更流畅稳定)
_MOON_FRAMES = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
_MOON_INTERVAL = 0.09

# ---- 输出溢出防护 (规范化: 单条/流式缓冲/思考全文都有界, 防止巨文本拖垮渲染) ----
_MAX_LOG_LEN = 2000      # 单条日志/审计行最大字符, 超出截断并标注
_MAX_STREAM_BUF = 20000  # 流式缓冲上限, 超出将前段固化为日志
_MAX_REASON_LEN = 30000  # 思考全文上限, 超出截断并标注

# ---- "/" 命令面板 (Claude Code 同款 slash menu) ----
_SLASH_MAX_VISIBLE = 9   # 面板最大可见行数 (超出滚动, 与 Claude Code 观感一致)

# 吉祥物字符标
KIMI_LOGO = ['▐█▛█▛█▌', '▐█████▌']

# prompt_toolkit 缺失时 (仅 import 本模块) 也要能安全导入:
# STYLE 降级为 None, 真正使用 TUI 时自会因缺少 pt 而报清晰错误。
_STYLE_DICT = {
    # 盒子 (吉祥物 / 模型 / 目录) 保持主品牌蓝
    "title": _PRIMARY,        # 盒子: 吉祥物 / 标题 (蓝)
    "boxsub": _BLUE_DIM,      # 盒子: 副标题 / 信息行 (Directory/Model/Version, 蓝)
    "dim": _DIM,
    "text": _TEXT,
    "textstrong": _TEXT_STRONG,
    "textdim": _DIM,
    "textmuted": _MUTED,
    "accent": _ACCENT,
    "error": _ERROR,
    "warning": _WARNING,
    "success": _SUCCESS,
    "primary": _PRIMARY,      # 盒子边框 / 输入框提示符 (蓝)
    "roleuser": _ROLEUSER,    # 用户消息: 金
    "border": _BORDER,        # 输入框边框: 灰
    "shellmode": _SHELL,
    # ---- "/" 命令面板 (Claude Code 同款: 高亮选择 + 描述) ----
    "slashbg": "bg:#16202C",          # 面板背景 (深色终端下与对话区区分)
    "slashsel": "bg:#26456B #FFFFFF bold",  # 选中行: 亮底加粗反显
    "slashcmd": _PRIMARY,             # 命令名 (品牌蓝)
    "slashdesc": _DIM,                # 命令描述 (弱化)
    "slashhint": _MUTED,              # 面板底部操作提示
}
STYLE = Style.from_dict(_STYLE_DICT) if _HAS_PT else None

# 对话区符号约定
USER_MESSAGE_BULLET = "✨ "
STATUS_BULLET = "● "
SUCCESS_MARK = "✓"
FAILURE_MARK = "✗"


def _disp_width(text: str) -> int:
    """显示宽度 (CJK/绘图形字符按实际列宽), 用于对齐欢迎盒右边框。"""
    try:
        from prompt_toolkit.utils import get_cwidth
        return sum(get_cwidth(ch) for ch in text)
    except Exception:
        return len(text)


def _split_flat_lines(paste: List[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
    """把扁平片段列表 (含 "\\n" 分隔) 切成逐行片段列表。"""
    lines: List[List[Tuple[str, str]]] = []
    cur: List[Tuple[str, str]] = []
    for cls, seg in paste:
        if seg == "\n":
            lines.append(cur)
            cur = []
        else:
            cur.append((cls, seg))
    if cur:
        lines.append(cur)
    return lines if lines else [[]]


class _TuiLogHandler(logging.Handler):
    """模块级日志转发器: 把 tuan logger 的终端输出转发进 TUI 对话区日志。

    定义在模块级 (而非 attach_ui 方法内), 保证多次 attach_ui 时
    isinstance 判等成立, 幂等替换不会重复挂载/重复输出。
    """

    def __init__(self, tui: Any) -> None:
        super().__init__()
        self._tui = tui

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from ..logging_conf import redact
            msg = redact(record.getMessage())
            if not msg:
                return
            if record.levelno >= logging.ERROR:
                self._tui.append_log(f"  ✗ {msg}", cls="class:error")
            elif record.levelno >= logging.WARNING:
                self._tui.append_log(f"  ⚠ {msg}", cls="class:warning")
            else:
                self._tui.append_log(msg, cls="class:textdim")
        except Exception:  # noqa: BLE001
            pass


class _SlashCompleter(Completer):
    """TUI 输入框的命令补全: 同时支持 `/cmd` 与 Kimi 同款 `+/cmd`。

    只对以 `/` 或 `+/` 开头的输入弹出命令提示; 选择补全项时会把 `+` 前缀
    一并写回, 使 `+/help` 这类命令能直接被回车执行。
    """

    def __init__(self, words: List[str], metas: Optional[Dict[str, str]] = None) -> None:
        self._words = list(words)
        self._metas = dict(metas or {})

    def get_completions(self, document, complete_event):  # noqa: C901
        text = document.text_before_cursor
        # 仅在命令前缀下补全: `/xxx` 或 `+/xxx`
        if text.startswith("+/"):
            plus, cut = "+", 2
            rest = text[2:]
        elif text.startswith("/"):
            plus, cut = "", 1
            rest = text[1:]
        else:
            return
        rest = rest.lower()
        for w in self._words:
            name = w[1:]  # 去掉前导 "/"
            if rest and not name.startswith(rest):
                continue
            full = plus + w
            yield Completion(
                full,
                start_position=-cut - len(rest),  # 替换光标前的命令前缀+已输入部分
                display=w,
                display_meta=self._metas.get("/" + name, t("tui.cmd_meta")),
            )


class QxtTUI:
    """青小团 TUI: 蓝色吉祥物加载屏 + 对话界面 (无侧栏, 单一 Application)。

    对外接口与 cmd_chat.py 完全对齐:
      QxtTUI(on_submit, title=, workspace=, on_cancel=, on_command=)
      方法: set_boot_progress / set_ready / boot_error / begin_tool / end_tool /
            end_any_tool / stream_assistant / end_stream / append_log /
            set_context_info / set_model / set_tools / set_plan_mode /
            confirm / close / run ...
    """

    def __init__(
        self,
        on_submit: Callable[[str], Optional[str]],
        title: str = "青小团",
        workspace: str = ".",
        on_cancel: Optional[Callable[[], None]] = None,
        on_command: Optional[Callable[[str], Optional[str]]] = None,
        commands: Optional[List[str]] = None,
        command_meta: Optional[Dict[str, str]] = None,
    ) -> None:
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.on_command = on_command
        self.title = title
        self.workspace = workspace
        # Kimi 同款 `+/命令` 补全词表: 传入则启用补全, 缺省 (兼容旧调用) 则不启用。
        self._commands: List[str] = list(commands or [])
        self._command_meta: Dict[str, str] = dict(command_meta or {})
        # "/" 命令面板状态 (Claude Code 同款: 输入 / 自动高亮列出全部命令,
        # ↑↓ 选择, Enter/Tab 确认填入, Esc 关闭)。取代 prompt_toolkit 自带
        # 补全菜单 —— 后者在输入框位于屏幕底部时下拉菜单无处渲染 (被底栏/
        # 屏幕边缘裁掉), 且无法做整行高亮。见 _on_input_changed / _render_slash_menu。
        self._slash_open = False            # 面板是否展开
        self._slash_items: List[str] = []   # 当前过滤后的命令列表
        self._slash_index = 0               # 高亮项索引
        self._slash_scroll = 0              # 滚动窗口起始索引
        self._slash_accepting = False       # 程序化写入文本时抑制联动 (防递归)
        self._slash_arg_mode = False        # 命令参数补全态 (/model <partial> 等)
        self._slash_arg_prefix = ""         # 参数补全时回填用的命令前缀 (如 "/model ")

        # 状态
        self._events: List[Any] = []
        self._closed = False
        self._busy = False
        self._cancel_requested = threading.Event()

        # 模式
        self._mode = "standard"
        self._plan_mode = False
        self._permission_mode = "default"
        self._no_key = False
        self._no_key_env = ""

        # Token / Context
        self._ctx_tokens: Optional[int] = None
        self._ctx_budget: Optional[int] = None
        self._context_pct: float = 0.0
        self._model_label = os.environ.get("TUAN_MODEL_LABEL", "")
        self._tools: List[str] = []

        # 启动引导 (loading) 状态: 内核后台构建期间显示内嵌加载屏,
        # 就绪后切到对话界面。同一 Application / 事件循环, 杜绝双屏切换崩溃。
        self._booting = True
        self._boot_progress = 0
        self._boot_status = t("tui.boot_starting")
        self._boot_error: Optional[str] = None
        self._agent: Any = None
        # 首次访问未知目录的信任确认态 (Kimi/Claude Code 风格卡片):
        # 由 prompt_trust() 挂起, _resolve_trust() 消费后经 on_confirm 回调写回
        # workspace_trust.json; 确认前 set_ready 不被调用 (由 cmd_chat._boot 完成)。
        self._trust_pending: Optional[Dict[str, Any]] = None
        self._trust_index: int = 0  # 信任确认 radiolist 高亮项: 0=信任 / 1=不信任
        # 命令执行确认态 (Kimi 风格卡片): 由 confirm() 挂起 —— 工具线程阻塞在
        # threading.Event 上, 卡片渲染在对话区底部, 用户在输入框敲 y/n 后由
        # _resolve_confirm() 唤醒。取代旧的 run_in_terminal(print+input) 方案:
        # 后者把提示打到输入框位置, 长命令直接撑破边框且语义上属于"输入框内容"。
        self._confirm_pending: Optional[Dict[str, Any]] = None
        self._frame = 0
        self._moon_frame = 0

        # 流式 / 工具状态
        self._stream_buf = ""
        self._streaming = False
        self._streamed = False
        self._running: List[str] = []
        self._tool_start_times: dict = {}
        # 抑制月亮: 流式收尾到回合真正结束之间, 不渲染"刚答完还转月亮"的鬼影。
        # 新一轮输入 / 新工具开始时清零, 保证多step回合里后续思考仍会显示。
        self._moon_suppressed = False

        # 审计面板 (kimi 折叠思考): 收集模型推理 + 重试/工具审计日志
        self._reason_buf: List[str] = []      # 本轮思考分片
        self._reason_full = ""                # 本轮累计思考全文
        self._audit_visible = False           # Ctrl+O 折叠面板开关
        self._audit_log: List[Tuple[str, str]] = []  # (cls, text) 审计行

        # 对话区滚动: 自定义跟随光标定位 (见 _log_cursor_pos), 支持回到历史
        # `follow` 为 True 时自动钉在最新内容底部; `pin` 为手动上翻时钉住的行号。
        self._follow = True
        self._pin = 0
        self._pin_t = 0        # 滚动钉住位置, 终端行单位 (逻辑行↔终端行换算见 _scroll_log)
        self._cursor_line = 0
        # 工具调用折叠 (Claude/TraeWork 风格 "see"): 本轮工具完成记录先折叠成
        # 一行摘要, Ctrl+O 展开查看每步细节 (同时镜像进审计面板)。
        self._turn_tool_lines: List[str] = []
        self._tool_detail = False

        # prompt_toolkit
        self._app: Optional[Any] = None
        self._log_control = FormattedTextControl(
            self._render_conversation,
            show_cursor=False,
            get_cursor_position=self._log_cursor_pos,
        )
        self._footer_control = FormattedTextControl(self._render_footer)
        self._input = TextArea(
            prompt=FormattedText([("class:primary", "> ")]),
            multiline=False,
            # 单行输入必须横向滚动: 若 wrap_lines=True 且 height=1, 中文/宽字符贴到
            # 右边界触发裁剪式软换行 → 最后列宽核算错一位, 高亮重绘(思考动画)把错位
            # 残影卷进输入栏, 表现为 IME 打字/粘贴/英文全变乱码。
            wrap_lines=False,
            scrollbar=False,
            height=1,
            history=InMemoryHistory(),
            # "/" 命令面板由 QxtTUI 自绘 (见 _render_slash_menu): 输入 "/" 即弹出,
            # ↑↓ 选择 · Enter/Tab 确认 · Esc 关闭。不走 prompt_toolkit 补全器 ——
            # 其下拉菜单位于输入框下方, 而本布局输入框贴屏幕底部, 菜单会被裁掉。
            completer=None,
            complete_while_typing=False,
        )
        # 输入文本变化 → 命令面板开合/过滤 (Claude Code 同款体验)
        try:
            self._input.buffer.on_text_changed += self._on_input_changed
        except Exception:  # noqa: BLE001 - 测试桩/旧版 pt 无该事件时静默降级
            pass

        # 输入框: 单行细边框 (可见性优先)。裸 TextArea 在深色终端 conpty 下
        # 无边框无背景, 观感"输入框消失"; 恢复三层 ╭─╮ 细边框保证任何终端可见,
        # 内部 prompt 仍是 Kimi 同款 "> "。
        _b = "class:border"
        input_top = VSplit([
            Window(width=1, char="╭", style=_b, height=1),
            Window(char="─", style=_b, height=1),
            Window(width=1, char="╮", style=_b, height=1),
        ])
        input_mid = VSplit([
            Window(width=1, char="│", style=_b),
            self._input,
            Window(width=1, char="│", style=_b),
        ])
        input_bottom = VSplit([
            Window(width=1, char="╰", style=_b, height=1),
            Window(char="─", style=_b, height=1),
            Window(width=1, char="╯", style=_b, height=1),
        ])
        input_frame = HSplit([
            input_top,
            input_mid,
            input_bottom,
        ])

        # 对话区占满剩余空间: 用普通 Window + 自定义光标定位实现滚动,
        # 替代 ScrollablePane (后者在 Windows/conpty 下碎滚动且无法回看历史)。
        self._log_window = Window(
            self._log_control,
            wrap_lines=True,
            height=Dimension(min=1, weight=1),
        )
        conversation = self._log_window
        # 审计面板 (kimi 折叠思考): 默认隐藏, Ctrl+O 展开; 展开约占 45% 高度
        self._audit_control = FormattedTextControl(self._render_audit)
        audit_wrap = ConditionalContainer(
            HSplit([
                Window(char="─" * 1, height=1, style="class:border"),
                Window(self._audit_control, wrap_lines=True, height=Dimension(min=3, weight=2)),
            ]),
            filter=to_filter(self._audit_visible),
        )
        # 就绪前 (booting / 启动失败) 隐藏输入框与底栏: 加载屏只显示盒子+进度条,
        # 避免"输入框空悬 + 底栏信息残缺"的杂乱观感; boot→ready 切换时强制
        # renderer.reset() 全量重绘, 杜绝 prompt_toolkit diff 残影 (旧帧的 boot
        # 状态/旧 footer 叠在新帧上, 观感"字符残留/双行状态栏")。
        _ready = Condition(lambda: not self._booting and not self._boot_error)
        # "/" 命令面板: 输入 "/" 即在输入框上方弹出 (Claude Code 同款位置),
        # 高度随条目数动态伸缩 (callable → prompt_toolkit 布局期求值), 最多 9 行。
        self._slash_control = FormattedTextControl(
            self._render_slash_menu, show_cursor=False, focusable=False,
        )
        slash_menu = ConditionalContainer(
            Window(
                self._slash_control,
                height=self._slash_menu_rows,
                style="class:slashbg",
                wrap_lines=False,
            ),
            filter=Condition(lambda: self._slash_open and bool(self._slash_items)),
        )
        bottom = ConditionalContainer(
            HSplit([
                slash_menu,
                input_frame,
                Window(self._footer_control, height=1),
            ]),
            filter=_ready,
        )
        layout = Layout(
            HSplit([
                conversation,
                # 审计面板: 仅当展开时占空间
                audit_wrap,
                bottom,
            ])
        )

        output = None
        try:
            is_test = bool(
                os.environ.get("PYTEST_CURRENT_TEST")
                or os.environ.get("PYTEST_VERSION")
                or os.environ.get("CI")
                or "pytest" in sys.modules
            )
            if is_test or not getattr(sys.stdout, "isatty", lambda: False)():
                output = DummyOutput()
            elif os.name == "nt":
                # Windows 原生体验 (Major #6): 真终端下先启用 VT 处理 + UTF-8 代码页,
                # 否则 prompt_toolkit 的 ANSI 颜色与 CJK 框线被 ConHost 渲染成乱码。
                from .win_compat import enable_virtual_terminal
                enable_virtual_terminal()
        except Exception:
            pass

        try:
            self._app = Application(
                layout=layout,
                key_bindings=self._build_keys(),
                style=STYLE,
                full_screen=True,
                mouse_support=False,
                output=output,
            )
        except Exception as exc:
            if type(exc).__name__ != "NoConsoleScreenBufferError":
                raise
            self._app = Application(
                layout=layout,
                key_bindings=self._build_keys(),
                style=STYLE,
                full_screen=True,
                mouse_support=False,
                output=DummyOutput(),
            )

    # ============================================================ 键位

    def _request_exit(self, event) -> None:
        """Ctrl-C / Ctrl-Q 退出: 先解冻挂起的确认 (按"拒绝"处理) 再退出应用。

        否则工具线程会一直阻塞在确认 Event 上 —— 线程的等待循环虽有应用退出
        兜底, 但显式解冻能让"用户取消"这一结果被正常回传与记录, 语义更干净。
        """
        self.cancel_confirm()
        self._closed = True
        event.app.exit()

    def _build_keys(self) -> "KeyBindings":
        kb = KeyBindings()

        @kb.add("c-c")
        def _(event):
            self._request_exit(event)

        @kb.add("c-q")
        def _(event):
            self._request_exit(event)

        @kb.add("enter")
        def _(event):
            self._handle_enter(event)

        @kb.add("c-o")
        def _(event):
            self.toggle_audit()

        # ---- 对话区回卷: PgUp/PgDn 上翻/下翻, Home/End 到顶/底 ----
        # (不用 Ctrl+U/Ctrl+D: 会被输入框的编辑键抢占, 见 TextArea buffer 绑定)
        @kb.add("pageup")
        def _(event):
            self._scroll_log(-self._page_rows())
            event.app.invalidate()

        @kb.add("pagedown")
        def _(event):
            self._scroll_log(self._page_rows())
            event.app.invalidate()

        @kb.add("home")
        def _(event):
            self._follow = False
            self._pin_t = 0
            event.app.invalidate()

        @kb.add("end")
        def _(event):
            self._follow = True
            self._pin_t = 0
            event.app.invalidate()

        # ---- "/" 命令面板: Tab 确认填入, ↑↓ 游走菜单 (关闭时回退默认行为), Esc 关闭 ----
        @kb.add("c-i")  # Tab
        def _(event):
            if self._slash_open and self._slash_items:
                self._accept_slash(event)
                return
            b = event.current_buffer
            if b.complete_state:  # 兼容旧补全路径 (外部直接驱动 buffer 的场景)
                b.complete_next()
            else:
                b.start_completion(select_first=True)

        @kb.add("down")
        def _(event):
            if self._trust_pending:
                self._trust_index = 1
                event.app.invalidate()
                return
            if self._slash_open and self._slash_items:
                self._slash_move(1)
                event.app.invalidate()
                return
            b = event.current_buffer
            if b.complete_state:
                b.complete_next()
            else:
                # 面板关闭: 交还默认行为 (↑↓ 历史导航 / 光标移动)。
                # 早先这里"匹配却不代理"吞掉了按键, 导致历史导航失效。
                b.auto_down(count=event.arg or 1)

        @kb.add("up")
        def _(event):
            if self._trust_pending:
                self._trust_index = 0
                event.app.invalidate()
                return
            if self._slash_open and self._slash_items:
                self._slash_move(-1)
                event.app.invalidate()
                return
            b = event.current_buffer
            if b.complete_state:
                b.complete_previous()
            else:
                # 同 down: 面板关闭时交还默认行为, 修复 ↑ 历史导航被吞。
                b.auto_up(count=event.arg or 1)

        @kb.add("escape")
        def _(event):
            # Esc: 关闭 "/" 命令面板 (未展开时不消费按键, 不影响信任/确认等其它流程)
            if self._slash_open:
                self._close_slash_menu()
                event.app.invalidate()
                return

        return kb

    def toggle_audit(self) -> None:
        """Ctrl+O 切换"see"折叠: 收起/展开工具调用详情 + 审计面板 (思考过程)。

        折叠态在对话区只显示一行 "see N tool calls", 展开态逐条展示每步调用;
        审计面板同步显示完整思考过程与工具记录。类似 Claude/TraeWork 的折叠观察窗。
        """
        self._audit_visible = not self._audit_visible
        self._tool_detail = self._audit_visible
        if self._app and self._app.is_running:
            self._app.invalidate()

    # ---- 对话区滚动 (自定义光标定位, Windows/conpty 下可靠) ----

    def _page_rows(self) -> int:
        """单次翻页的行数 = 可视区高度 (减输入框 3 行 + 底栏 1 行)。"""
        try:
            rows = self._app.output.get_size().rows if self._app else 0
        except Exception:
            rows = 0
        if rows <= 0:
            try:
                rows = shutil.get_terminal_size((80, 24)).lines
            except Exception:
                rows = 24
        return max(3, rows - 4)

    def _log_width(self) -> int:
        """对话区可视列宽 (供软换行高度估算)。"""
        try:
            cols = self._app.output.get_size().columns if self._app else 0
        except Exception:
            cols = 0
        if cols <= 0:
            try:
                cols = shutil.get_terminal_size((80, 24)).columns
            except Exception:
                cols = 80
        return max(20, cols - 2)

    def _log_line_heights(self) -> List[int]:
        """每个逻辑行在 wrap_lines 下的终端行高 (宽字符感知)。

        与 prompt_toolkit Window 的换行规则对齐: 按显示宽度断行,
        空行/零宽内容占 1 终端行。滚动以终端行为单位, 避免长消息
        (无换行大段) 使逻辑行与终端行错位 → 中间内容翻不到。
        """
        width = self._log_width()
        heights: List[int] = []
        for line in self._scrolled_lines(logic_only=True):
            text = "".join(seg for _, seg in line)
            if not text:
                heights.append(1)
                continue
            disp = sum(max(0, _wcswidth(ch)) for ch in text)
            heights.append(max(1, math.ceil(disp / width)))
        return heights

    def _terminal_total(self) -> int:
        return sum(self._log_line_heights())

    def _pin_t_to_logic(self, pin_t: int) -> int:
        """终端行位置 → 其所在逻辑行索引 (滚动锚点换算)。"""
        acc = 0
        heights = self._log_line_heights()
        for i, h in enumerate(heights):
            if acc + h > pin_t:
                return i
            acc += h
        return max(0, len(heights) - 1)

    def _scroll_log(self, delta: int) -> None:
        """按 delta 终端行上/下滚动对话区。到顶/到底时分别转 follow=False/True。

        增量单位为终端行 (软换行后的可视行), 保证每次 PgUp/PgDn 正好一屏、
        且可一路翻到顶部 —— 修复长消息导致"逻辑行↔终端行错位、中间内容
        看不了"的问题。
        """
        total = self._terminal_total()
        if total <= 0:
            return
        if self._follow:
            # 首次上翻: 从当前底部位置起算
            self._follow = False
            self._pin_t = max(0, total - self._page_rows())
        self._pin_t = max(0, min(total - 1, self._pin_t + delta))
        if self._pin_t >= total - 1:
            self._follow = True
            self._pin_t = 0

    def _log_cursor_pos(self):
        """返回对话区应钉住的光标行号 (FormattedTextControl.get_cursor_position)。

        follow 时钉在最后一行 -> Window 自动滚动到底部 (跟随新内容);
        手动上翻时钉在 _pin -> 视图稳定在被选历史处, 不会因新内容跳动。
        """
        return Point(x=0, y=self._cursor_line)

    def _current_line_count(self) -> int:
        """当前渲染内容的段落行数 (供滚动钳位)。"""
        try:
            lines = self._scrolled_lines(logic_only=True)
            return len(lines)
        except Exception:
            return 0

    def _render_audit(self):
        """审计面板内容: 顶部标题 + 思考全文 + 审计日志 (kimi 折叠思考)。"""
        line: List[Tuple[str, str]] = [("class:primary", t("tui.audit_title"))]
        if not self._audit_visible:
            return line
        line.append(("class:textdim", "  Ctrl+O 收起"))
        out: List[List[Tuple[str, str]]] = [line]
        # 进行中的思考 (实时)
        if self._reason_full:
            out.append([("class:textdim", self._reason_full)])
        for cls, text in self._audit_log[-40:]:
            out.append([(cls, text)])
        if len(out) == 1:
            out.append([("class:textdim", t("tui.audit_empty"))])
        flat: List[Tuple[str, str]] = []
        for i, r in enumerate(out):
            for cls, seg in r:
                flat.append((cls, seg))
            if i < len(out) - 1:
                flat.append(("", "\n"))
        return flat

    def _push_history(self, text: str) -> None:
        """把输入写入输入框历史, 跳过与上一条完全相同的重复输入。

        配合 ↑/↓ 历史导航: 连发同一条命令/多轮同句式时不刷屏, 回看更干净。
        历史读写失败绝不影响发送主流程。
        """
        try:
            history = self._input.buffer.history
            if history is None:
                return
            try:
                entries = history.get_strings()
                if entries and entries[-1] == text:
                    return
            except Exception:
                pass
            history.append_string(text)
        except Exception:
            pass

    # ============================================================ "/" 命令面板

    def _term_width(self) -> int:
        """终端真实列宽 (探测失败回退 shutil/80)。"""
        try:
            if self._app is not None:
                w = self._app.output.get_size().columns
                if w and w > 0:
                    return int(w)
        except Exception:
            pass
        try:
            return shutil.get_terminal_size((80, 24)).columns
        except Exception:
            return 80

    def _on_input_changed(self, buffer=None) -> None:
        """输入文本变化 → 命令面板开合/过滤 (Claude Code 同款体验)。

        规则:
        - 输入以 "/" 或 "+/" 开头且尚未输空格 → 展开面板, 按已输入前缀过滤;
          空前缀 ("/") 列出全部命令并高亮第一项;
        - 出现空格 (命令已定, 开始输参数) / 删空 / 非命令输入 → 关闭面板;
        - boot / 信任确认 / 命令确认 / 思考进行中 → 不展开 (输入框是答复通道)。
        """
        if self._slash_accepting:
            return
        try:
            text = self._input.text
        except Exception:  # noqa: BLE001 - 输入框未就绪 (极早期启动)
            return
        if (not self._commands or self._booting or self._boot_error
                or self._trust_pending or self._confirm_pending):
            self._close_slash_menu()
            return
        # 命令参数补全: /model <partial> 或 /provider <partial> 时列出候选值
        # (复用 "/" 命令面板: ↑↓ 选择, Enter/Tab 确认填入, Esc 关闭)
        am = re.match(r'^([+/]?(?:model|provider|providers?))\s+(\S*)$', text)
        if am:
            self._slash_arg_mode = True
            self._slash_arg_prefix = am.group(1) + " "
            partial = am.group(2).lower()
            cands = self._arg_completions(am.group(1).lstrip("+/").lower(), partial)
            if not cands:
                self._close_slash_menu()
                return
            self._slash_items = cands
            self._slash_index = 0
            self._slash_scroll = 0
            self._slash_open = True
            return
        self._slash_arg_mode = False
        if text.startswith("/"):
            typed = text[1:]
        elif text.startswith("+/"):
            typed = text[2:]
        else:
            self._close_slash_menu()
            return
        if " " in typed or "\n" in typed:
            self._close_slash_menu()
            return
        low = typed.lower()
        items = [c for c in self._commands if c[1:].lower().startswith(low)]
        if not items:
            self._close_slash_menu()
            return
        self._slash_items = items
        self._slash_index = 0
        self._slash_scroll = 0
        self._slash_open = True

    def _close_slash_menu(self) -> None:
        """关闭命令面板 (幂等)。"""
        self._slash_open = False
        self._slash_items = []
        self._slash_index = 0
        self._slash_scroll = 0
        self._slash_arg_mode = False
        if self._app and self._app.is_running:
            try:
                self._app.invalidate()
            except Exception:  # noqa: BLE001
                pass

    def _arg_completions(self, cmd: str, partial: str) -> List[str]:
        """命令参数补全候选: /model 返回模型 ID 全集, /provider 返回供应商名。

        partial 为空列出全部 (面板可滚动); 否则按前缀过滤。模型 ID 取自各供应商
        MODEL_LISTS (剥 |free/|paid 标注), 并附供应商名便于 "provider/model" 速选。
        """
        try:
            from ..models.provider_catalog import ALL_PROVIDER_NAMES, MODEL_LISTS
        except Exception:
            return []
        if cmd in ("provider", "providers"):
            cands = list(ALL_PROVIDER_NAMES)
        else:  # model
            seen: set = set()
            cands = []
            for _p, models in MODEL_LISTS.items():
                for m in models:
                    mid = m.split("|")[0]
                    if mid not in seen:
                        seen.add(mid)
                        cands.append(mid)
            for p in ALL_PROVIDER_NAMES:
                if p not in seen:
                    seen.add(p)
                    cands.append(p)
        if partial:
            return [c for c in cands if c.lower().startswith(partial)]
        return cands

    def _slash_move(self, delta: int) -> None:
        """面板内移动高亮 (循环滚动), 并保持滚动窗口可见。"""
        if not self._slash_items:
            return
        n = len(self._slash_items)
        self._slash_index = (self._slash_index + delta) % n
        self._slash_clamp_scroll()

    def _slash_clamp_scroll(self) -> None:
        visible = min(_SLASH_MAX_VISIBLE, len(self._slash_items))
        if self._slash_index < self._slash_scroll:
            self._slash_scroll = self._slash_index
        elif self._slash_index >= self._slash_scroll + visible:
            self._slash_scroll = self._slash_index - visible + 1

    def _accept_slash(self, event=None) -> bool:
        """Enter/Tab 确认: 把高亮命令填入输入框并关闭面板 (不直接执行)。

        与 Claude Code 一致: 选中只是补全, 用户可继续输入参数, 再按回车执行。
        """
        if not (self._slash_open and self._slash_items):
            return False
        idx = max(0, min(self._slash_index, len(self._slash_items) - 1))
        if self._slash_arg_mode:
            cmd = self._slash_arg_prefix + self._slash_items[idx]
            self._slash_arg_mode = False
        else:
            cmd = self._slash_items[idx]
        try:
            from prompt_toolkit.document import Document

            self._slash_accepting = True
            try:
                self._input.buffer.document = Document(cmd, cursor_position=len(cmd))
            finally:
                self._slash_accepting = False
        except Exception:  # noqa: BLE001 - 极端环境退回纯文本赋值
            self._slash_accepting = False
            try:
                self._input.buffer.text = cmd
            except Exception:
                pass
        self._slash_open = False
        self._slash_items = []
        self._slash_index = 0
        self._slash_scroll = 0
        if self._app and self._app.is_running:
            try:
                self._app.invalidate()
            except Exception:  # noqa: BLE001
                pass
        return True

    def _slash_menu_rows(self) -> int:
        """面板高度 (布局期 callable 求值): 条目数封顶 _SLASH_MAX_VISIBLE, 至少 1 行。"""
        return max(1, min(len(self._slash_items), _SLASH_MAX_VISIBLE))

    def _render_slash_menu(self):
        """"/" 命令面板: 高亮行 + 命令名 + 描述 (+ 溢出时滚动提示行)。

        每行按终端显示宽度裁剪 (CJK 宽字符感知), 防止超宽描述顶破布局。
        """
        items = self._slash_items
        if not items:
            return []
        width = self._term_width()
        visible = min(len(items), _SLASH_MAX_VISIBLE)
        start = self._slash_scroll
        if self._slash_index >= start + visible:
            start = self._slash_index - visible + 1
        elif self._slash_index < start:
            start = self._slash_index
        window = range(start, min(start + visible, len(items)))
        rows: List[List[Tuple[str, str]]] = []
        for i in window:
            cmd = items[i]
            sel = (i == self._slash_index)
            mark = "▶ " if sel else "  "
            desc = self._command_meta.get(cmd) or t("tui.cmd_meta")
            line = f"{mark}{cmd}"
            room = max(1, width - _disp_width(line) - 3)
            desc = self._clip_dw(desc, room) if _disp_width(desc) > room else desc
            sel_cls = "class:slashsel" if sel else ""
            rows.append([
                (sel_cls or "class:slashcmd", line),
                (sel_cls, "  "),
                (sel_cls or "class:slashdesc", desc),
            ])
        if len(items) > _SLASH_MAX_VISIBLE:
            hidden = len(items) - visible
            hint = t("tui.slash_more", n=hidden, pos=f"{self._slash_index + 1}/{len(items)}")
            rows.append([("class:slashhint", self._clip_dw(hint, max(1, width - 1)))])
        out: List[Tuple[str, str]] = []
        for r_i, row in enumerate(rows):
            for cls, seg in row:
                out.append((cls, seg))
            if r_i < len(rows) - 1:
                out.append(("", "\n"))
        return out

    def _clip_parts(self, parts: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """按终端显示宽度裁剪一行分段 (防文字溢出顶破全屏布局)。

        Window(height=1, wrap_lines=False) 自身不裁切内容: 超宽文本会被终端
        自行软换行, 把整行布局顶错位 (观感即"文字溢出/状态行跳行")。这里按
        列宽硬裁并补省略号, 与 prompt_toolkit 内部行为无关地保证单行控件不溢出。
        """
        width = self._term_width()
        out: List[Tuple[str, str]] = []
        used = 0
        for cls, seg in parts:
            if not seg:
                continue
            w = _disp_width(seg)
            if used + w <= width:
                out.append((cls, seg))
                used += w
                continue
            room = width - used
            if room > 0:
                out.append((cls, self._clip_dw(seg, room)))
            break
        return out

    def _handle_enter(self, event) -> None:
        # "/" 命令面板展开: Enter 确认高亮项 (填入输入框, 不直接执行 —— 与
        # Claude Code 一致, 填好后可继续输参数或再按回车执行)
        if self._slash_open and self._slash_items:
            self._accept_slash(event)
            return
        text = self._input.text.strip()
        if not text:
            return
        # 信任确认态: 优先按 y/n 解析; 若用户直接输入了别的内容, 说明他就是要用这个
        # 工作区 —— 自动记为信任, 并把这句当作正常消息继续往下走。
        # (此前非 y/n 输入只提示"无效"并停在确认态: 用户不按 y/n 就永远进不了对话,
        #  表现即"TUI 没有输入框 / 输入没反应"。)
        if self._trust_pending:
            _ws = (self._trust_pending or {}).get("workspace", "")
            # ① 用户直接输入了明确的 y/n/1/2/是/否/信任/只读 → 按文本解析
            if text and self._resolve_trust(text):
                self._input.buffer.reset()
                event.app.invalidate()
                return
            # ② 否则按当前 ↑↓ 高亮项确认 (默认高亮=信任, 空回车也能进工作区);
            #    既修复"对话框没有选项"的渲染缺失, 也修复"不按 y/n 就永远卡在确认态"。
            self._resolve_trust("y" if self._trust_index == 0 else "n")
            self._input.buffer.reset()
            event.app.invalidate()
            return
        # 命令确认态: 同样只接受 y/n (或确认码)。必须排在 _busy 判断之前 ——
        # 确认期间 _busy=True (防止用户又提交一轮对话), 但输入框此刻正是答复通道。
        if self._confirm_pending:
            self._resolve_confirm(text)
            self._input.buffer.reset()
            event.app.invalidate()
            return
        if self._booting or self._boot_error:
            self.append_log(t("tui.booting_wait"))
            return
        if self._busy:
            self.append_log(t("tui.busy_wait"))
            return

        self._push_history(text)
        self._input.buffer.reset()
        self._busy = True
        self._cancel_requested.clear()
        self._moon_suppressed = False  # 新一轮回合, 思考月亮恢复可用
        # 新一轮: 重置工具折叠缓冲, 并回到自动跟随底部 (让最新回复可见)
        self._turn_tool_lines = []
        self._tool_detail = False
        self._follow = True
        self._pin = 0

        # 命令: 支持 `/cmd` 与 Kimi 同款 `+/cmd` (归一化后统一走 on_command)
        cmd = None
        if text.startswith("/"):
            cmd = text
        elif text.startswith("+/"):
            cmd = "/" + text[2:]
        if cmd and self.on_command:
            result = self.on_command(cmd)
            if result:
                self.append_log(result)
            self._busy = False
            event.app.invalidate()
            return

        self.append_log(f"{USER_MESSAGE_BULLET}{text}")
        threading.Thread(
            target=self._run_submit, args=(text,),
            name="tuan-submit", daemon=True,
        ).start()

    # ============================================================ 启动引导 (加载屏)

    def set_boot_progress(self, pct: int, status: str = "") -> None:
        self._boot_progress = min(100, max(0, int(pct)))
        if status:
            self._boot_status = status
        if self._app and self._app.is_running:
            self._app.invalidate()

    def attach_ui(self) -> None:
        """把 _ui_singleton.ui 替换为 TUI 桥接, 使 slash 命令 / 后台线程
        (如 /web 服务器) 的输出进入本界面, 不再直接打 stdout 挤爆全屏渲染。

        同时把 tuan 根 logger 的终端 handler 替换为 TUI 转发器 (模块级
        _TuiLogHandler): MCP / 内核等模块的 logging 输出不再裸写 stdout
        污染全屏界面, 而是以整齐的错误/警告/普通行进入对话区日志。
        """
        from ..cli import _ui_singleton
        from ..ui.tui_bridge import TuiUI

        _ui_singleton._ui = TuiUI(self)
        try:
            import logging as _logging

            lg = _logging.getLogger("tuan")
            for h in list(lg.handlers):
                if isinstance(h, _logging.StreamHandler):
                    lg.removeHandler(h)
            # 幂等: 先移除旧转发器再挂新实例, 避免 attach_ui 被多次调用时重复输出
            for h in list(lg.handlers):
                if isinstance(h, _TuiLogHandler):
                    lg.removeHandler(h)
            lg.addHandler(_TuiLogHandler(self))

            # ---- 关键: 模块日志的桥接 ----
            # 各模块用 logging.getLogger(__name__) 取 logger, 名字是
            # "tuan_cli.core.xxx" —— **不是** "tuan" 的子级, 因此只挂 "tuan"
            # 会让全部模块日志绕过桥接、直接写 stdout, 出现在全屏界面下方
            # (观感"报错消息都在输入框里冒出来, 还一次好几条")。
            # 所以转发器要挂到根 logger 与 "tuan_cli" logger 上; 根上只留
            # WARNING+ (避免 httpx/openai 等三方库的 INFO 刷屏),
            # 根上写终端的 StreamHandler 一并移除 (文件 handler 保留)。
            root = _logging.getLogger()
            for h in list(root.handlers):
                if isinstance(h, _TuiLogHandler):
                    root.removeHandler(h)
                elif isinstance(h, _logging.StreamHandler):
                    stream = getattr(h, "stream", None)
                    if stream is getattr(_logging.sys, "__stdout__", None) or \
                            stream is getattr(_logging.sys, "__stderr__", None):
                        root.removeHandler(h)
            fwd = _TuiLogHandler(self)
            fwd.setLevel(_logging.WARNING)
            root.addHandler(fwd)
            mod_logger = _logging.getLogger("tuan_cli")
            for h in list(mod_logger.handlers):
                if isinstance(h, _TuiLogHandler):
                    mod_logger.removeHandler(h)
            mod_logger.addHandler(_TuiLogHandler(self))
            # 关闭向根传播: 否则 WARNING+ 会同时被 tuan_cli 与 root 两个转发器
            # 各渲染一次 (观感"一次发送好几条相同的报错")。
            mod_logger.propagate = False
        except Exception:  # noqa: BLE001
            pass

    def set_no_key(self, no_key: bool, env: str = "") -> None:
        """刷新"未配置 API Key"横幅状态 (配置密钥后立即清除, 无需重启会话)。"""
        self._no_key = bool(no_key)
        if env:
            self._no_key_env = env
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_ready(self, config: Any, agent: Any, workspace: str,
                  tools: Optional[List[str]] = None, no_key: bool = False,
                  no_key_env: str = "", mode: Optional[str] = None) -> None:
        """内核就绪: 从加载屏切换到对话界面。mode=standard/yolo/plan 驱动底部徽标。"""
        self._booting = False
        self._boot_error = None
        self._no_key = bool(no_key)
        self._no_key_env = no_key_env or ""
        self._agent = agent
        if tools:
            self.set_tools(list(tools))
        try:
            agent.ctx.confirm = self.confirm
        except Exception:
            pass
        if mode:
            # 显式传入的运行模式优先 (standard / yolo / plan)
            self.set_mode(mode)
        else:
            self.set_plan_mode(getattr(agent, "plan_mode", False))
        prov = config.get("model.provider", "") or ""
        mdl = config.get("model.model", "") or ""
        self._model_label = f"{prov}/{mdl}"
        # 初始化真实上下文占用条: 预算取模型真实上下文窗口 (fallback 到配置)
        self._ctx_budget = self._model_context_window(prov, mdl)
        self.set_context_info(0, self._ctx_budget)
        self._show_welcome()
        hint = t("tui.readonly_hint")
        if no_key:
            hint += " " + t("tui.no_key_hint")
        # 接线: 把 _ui_singleton.ui 替换为 TUI 桥接, 使 slash 命令 / 后台线程
        # 的输出进入渲染层 (append_log), 不再直接打 stdout 挤爆全屏界面。
        self.attach_ui()
        # 只读提示作为普通日志行展示 (紧凑布局, 不单独占 hint 行)
        self.append_log(hint, cls="class:textdim")
        # 滚动键提示: 让用户知道可以回看历史 (否则长会话"无法回溯"的反馈会归因于产品)
        try:
            self.append_log(t("tui.scroll_hint"), cls="class:textdim")
        except Exception:  # noqa: BLE001
            pass
        self._reset_renderer()
        if self._app and self._app.is_running:
            self._app.invalidate()

    def _reset_renderer(self) -> None:
        """全量重绘: boot→ready / boot→error / trust→ready 切换时清掉上一帧。

        **必须先 erase() 再 reset()**: 只调 `reset()` 会丢弃 `_last_screen` 却
        **不擦掉屏幕上已有的内容**, 下一次渲染就把新帧直接画在旧帧下面 ——
        观感正是底栏/状态行"堆叠成两份"。`erase()` 会把光标移回起点并向下擦除,
        之后 `reset()` 才能从干净画布重绘。
        `leave_alternate_screen=False`: 本 TUI 是全屏 (alternate screen) 应用,
        不能因为重绘而退出备用屏。
        """
        try:
            r = getattr(self._app, "renderer", None)
            if r is None:
                return
            try:
                r.erase(leave_alternate_screen=False)
            except Exception:
                pass
            if hasattr(r, "reset"):
                r.reset()
        except Exception:
            pass

    def boot_error(self, message: str) -> None:
        """内核构建失败: 显示错误态 (不再静默闪退), 用户可读后 Ctrl-Q 退出。"""
        self._boot_error = str(message)
        self._booting = False
        self.append_log(f"{t('tui.boot_error_title')} {message}")
        self.append_log(t("tui.boot_error_hint"))
        self._reset_renderer()
        if self._app and self._app.is_running:
            self._app.invalidate()

    def _box_width(self) -> int:
        """盒子/输入框可用宽度 = 真实 App 列宽 (避免与 wrap_lines 的窗口宽度偏差导致错位/圆角外拐)。

        2026-10-18 修复文字溢出: 旧实现 ``max(44, w)`` 在窄终端 (<44 列) 下
        强制 44 宽, 盒子右边框被顶出屏幕, 对话区 (wrap_lines=True) 把超宽行
        软换行 → 右边框掉到下一行, 观感即"文字溢出/盒子错位"。现完全尊重
        真实宽度, 仅在探测失败时回退 shutil/80。
        """
        try:
            if self._app is not None:
                w = self._app.output.get_size().columns
                if w and w > 0:
                    return int(w)  # type: ignore[no-any-return]  # columns 为 Any
        except Exception:
            pass
        try:
            return shutil.get_terminal_size((80, 24)).columns
        except Exception:
            return 80

    def _kimi_box(self, title: str, subtitle: str,
                   info_pairs: List[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
        """欢迎盒: 全宽圆角边框 + 2 空格内边距 + 吉祥物与标题并排 + 标签(蓝次级)/值(浅色)。

        返回 List[行]; 每行是 (class, text) 分段列表, 便于在 events 路径逐行渲染,
        保证 CJK/绘图形字符下右边框仍对齐。
        """
        width = self._box_width()           # 真实 App 列宽, 全宽
        inner = max(1, width - 2)            # 边框内侧显示列数 (= 宽度 - 左右两个 │), 右侧竖线对齐
        pad = "  "
        pad_w = 2
        logo_w = max(_disp_width(r) for r in KIMI_LOGO)
        gap_w = 2
        head_text_w = max(4, inner - pad_w - logo_w - gap_w)
        info_w = max(4, inner - pad_w)

        def clip_dw(s: str, n: int) -> str:
            if _disp_width(s) > n:
                res = ""
                for ch in s:
                    if _disp_width(res) + _disp_width(ch) > n:
                        break
                    res += ch
                return res
            return s + " " * (n - _disp_width(s))

        # 头部两行: 吉祥物 + 右侧文字并排 (row0 蓝标题 / row1 蓝次级)
        head: List[List[Tuple[str, str]]] = []
        rights = [clip_dw(title, head_text_w), clip_dw(subtitle, head_text_w)]
        for i, lg in enumerate(KIMI_LOGO):
            seg: List[Tuple[str, str]] = []
            seg.append(("class:primary", "│"))
            seg.append(("", pad))
            seg.append(("class:title", lg.ljust(max(1, logo_w))))
            seg.append(("", "  "))
            r = rights[i]
            seg.append(("class:title" if i == 0 else "class:boxsub", r))
            rp = max(0, (inner - pad_w - logo_w - gap_w) - _disp_width(r))
            seg.append(("", " " * rp))
            seg.append(("class:primary", "│"))
            head.append(seg)

        # 信息行: 标签(蓝次级) + 值(浅色)
        info_rows: List[List[Tuple[str, str]]] = []
        for label, value in info_pairs:
            label = str(label)
            value = str(value)
            # 值超长 (窄屏 / 长绝对路径 / 长模型名) 时按显示宽度截断补省略号,
            # 否则右侧竖线被顶飞 → 文字溢出 (2026-10-18 修复)。
            v_room = max(1, info_w - _disp_width(label))
            value = clip_dw(value, v_room)
            seg = []
            seg.append(("class:primary", "│"))
            seg.append(("", pad))
            seg.append(("class:boxsub", label))
            seg.append(("class:text", value))
            rp = max(0, info_w - _disp_width(label) - _disp_width(value))
            seg.append(("", " " * rp))
            seg.append(("class:primary", "│"))
            info_rows.append(seg)

        blank = [("class:primary", "│" + " " * (width - 2) + "│")]
        rows: List[List[Tuple[str, str]]] = [
            [("class:primary", "╭" + "─" * (width - 2) + "╮")],
            *head,
            blank,
            *info_rows,
            [("class:primary", "╰" + "─" * (width - 2) + "╯")],
        ]
        return rows

    def _render_boot(self) -> List[Tuple[str, str]]:
        frame = _SPLASH_FRAMES[self._frame % len(_SPLASH_FRAMES)]
        out: List[Tuple[str, str]] = []
        box_rows = self._kimi_box(
            title=t("tui.welcome_title"),
            subtitle=t("tui.welcome_subtitle"),
            info_pairs=[],
        )
        for i, row in enumerate(box_rows):
            for cls, seg in row:
                out.append((cls, seg))
            if i < len(box_rows) - 1:
                out.append(("", "\n"))
        out.append(("", "\n"))
        if self._boot_error:
            out.append(("class:error", f"  ✗ {self._boot_error}\n"))
            out.append(("class:textdim", f"  {t('tui.exit_ctrl_c')}\n"))
        elif self._boot_progress >= 100:
            out.append(("class:success", f"  {SUCCESS_MARK} {t('fs.ready')}\n"))
        else:
            out.append(("class:text", f"  {frame} {self._boot_status}\n"))
        bar_len = 30
        filled = int(self._boot_progress / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        out.append(("class:dim", f"  [{bar}] {self._boot_progress}%\n"))
        out.append(("", "\n"))
        out.append(("class:dim", f"  {t('tui.exit_ctrl_c')}\n"))
        return out

    # ============================================================ 流式 / 工具

    def _throttled_invalidate(self, min_interval: float = 0.033) -> None:
        """限频刷新: 高频事件 (流式/审计) 每帧至多刷新一次 (~30fps), 减少闪烁与 CPU。

        低频事件 (begin_tool/end_tool) 仍即时刷新; 末态由 end_stream/submit finally
        兜底刷新, 不会因限频漏画最终画面。
        """
        if not (self._app and self._app.is_running):
            return
        now = time.monotonic()
        if now - getattr(self, "_last_invalidate", 0.0) >= min_interval:
            self._last_invalidate = now
            self._app.invalidate()

    def stream_assistant(self, delta: str) -> None:
        if not delta:
            return
        self._streaming = True
        self._streamed = True
        self._stream_buf += delta
        # 缓冲有界: 模型吐超长回复时把前段固化为日志, 避免内存/渲染无限膨胀
        if len(self._stream_buf) > _MAX_STREAM_BUF:
            head, self._stream_buf = self._stream_buf[:_MAX_STREAM_BUF], self._stream_buf[_MAX_STREAM_BUF:]
            self._events.append(f"{STATUS_BULLET}{head.lstrip(chr(10))}…[流式超长, 已分段]")
            if len(self._events) > 5000:
                del self._events[: len(self._events) - 4000]
        self._throttled_invalidate()

    def stream_reason(self, delta: str) -> None:
        """接收模型推理分片, 累积成思考全文, 写入审计面板 (全文有界, 超长截断)。"""
        if not delta:
            return
        self._reason_buf.append(delta)
        self._reason_full += delta
        if len(self._reason_full) > _MAX_REASON_LEN:
            self._reason_full = self._reason_full[:_MAX_REASON_LEN] + "…[思考超长, 已截断]"
        self._throttled_invalidate()

    def audit(self, cls: str, text: str) -> None:
        """向审计面板追加一行日志 (类标志: textdim/accent/warning 等, 单条截断)。"""
        text = str(text)
        if len(text) > _MAX_LOG_LEN:
            text = text[:_MAX_LOG_LEN] + f"…[已截断 {len(text) - _MAX_LOG_LEN} 字符]"
        self._audit_log.append((cls, text))
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]
        self._throttled_invalidate()

    def end_stream(self) -> None:
        if self._stream_buf:
            # 模型输出常以空行开头, 去掉前导换行, 否则 ● 指示符会单独成行、
            # 正文缩进到下一行 (消息头与正文不在同一行的 bug)。
            buf = self._stream_buf.lstrip("\n")
            if buf:
                self.append_log(f"{STATUS_BULLET}{buf}", max_len=_MAX_LOG_LEN * 4)
            self._stream_buf = ""
        # 本轮思考收尾进审计面板: 折叠后首行是标题, 展开看全文
        if self._reason_full:
            self._audit_log.append(("class:primary", "▸ 思考 (本轮)"))
            self._audit_log.append(("class:textdim", self._reason_full))
            self._reason_buf = []
            self._reason_full = ""
        self._streaming = False
        # 流式收尾: 到回合结束前抑制月亮, 避免与刚落库的回复同屏出现鬼影。
        # 若回合不结束, 由随后 begin_tool 重启指示。
        self._moon_suppressed = True
        # 收尾刷新交给 _run_submit 的 finally (彼时 _busy 已清)。
        if not self._busy and self._app and self._app.is_running:
            self._app.invalidate()

    def begin_tool(self, name: str) -> None:
        self._running.append(name)
        self._busy = True
        self._moon_suppressed = False  # 新工具开始: 后续思考重新亮出指示
        self._tool_start_times[name] = time.monotonic()
        if self._app and self._app.is_running:
            self._app.invalidate()

    def end_tool(self, name: str, ok: bool = True) -> None:
        if name in self._running:
            self._running.remove(name)
        mark = SUCCESS_MARK if ok else FAILURE_MARK
        elapsed = self._tool_start_times.pop(name, None)
        elapsed_str = f" ({elapsed:.1f}s)" if elapsed is not None else ""
        label = t("tui.tool_done") if ok else t("tui.tool_failed")
        line = f"{mark}{name} {label}{elapsed_str}"
        # 工具完成记录进折叠缓冲 (see N tool calls), 并镜像进审计面板供 Ctrl+O 展开。
        self._turn_tool_lines.append(line)
        self._audit_log.append(("class:success" if ok else "class:error", line))
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]
        # _busy 由回合生命周期 (submit 开始置 True、finally 清) 统一掌管, 不在
        # 工具中途置 False, 否则多步回合会反复"掉指示/复现"造成月亮闪烁。
        if self._app and self._app.is_running:
            self._app.invalidate()

    def end_any_tool(self) -> None:
        if self._running:
            self.end_tool(self._running[0], ok=False)

    def set_model(self, label: str) -> None:
        self._model_label = str(label or "")
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_tools(self, tools: List[str]) -> None:
        self._tools = list(tools or [])

    def set_mode(self, mode: str) -> None:
        """设置运行模式 (standard / yolo / plan), 底部状态栏徽标随之更新。"""
        self._mode = mode or "standard"
        self._plan_mode = (mode == "plan")
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_plan_mode(self, enabled: bool) -> None:
        self._plan_mode = bool(enabled)
        if enabled:
            self._mode = "plan"
        elif self._mode == "plan":
            self._mode = "standard"

    def set_context_info(self, estimated: int, budget: int) -> None:
        self._ctx_tokens = int(estimated)
        self._ctx_budget = int(budget) if budget else 0
        bud = self._ctx_budget
        # 关键: budget 为 0/未知时回落到 0%, 不得算出 300000% 之类荒谬值
        self._context_pct = (
            min(100.0, self._ctx_tokens / bud * 100.0) if bud is not None and bud > 0 else 0.0
        )
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_context_used(self, estimated: int) -> None:
        """刷新上下文已用 token, 保持分母 (模型上下文窗口) 不变。

        只在回合结束后更新已用量, 不改 budget, 从而避免分母在"模型窗口/配置预算"
        之间来回切换造成的百分比跳变 (此前肉眼观感随机)。
        """
        self._ctx_tokens = max(0, int(estimated))
        bud = self._ctx_budget
        self._context_pct = (
            min(100.0, self._ctx_tokens / bud * 100.0) if bud is not None and bud > 0 else 0.0
        )
        if self._app and self._app.is_running:
            self._app.invalidate()

    # 供应商级默认上下文窗口表已上移到 core.prompt_tier.PROVIDER_CONTEXT_WINDOWS
    # (单一真相源: 同一份规则同时驱动底栏分母与提示词分层定档)。本类不再维护副本,
    # 避免两处数字漂移。
    _PROVIDER_CONTEXT: Dict[str, int] = PROVIDER_CONTEXT_WINDOWS

    def _model_context_window(self, provider: str, model: str) -> int:
        """推断当前模型真实上下文窗口 (token), 驱动底栏 context 分母。

        尺寸后缀 / 长上下文家族的识别**委托给 core.prompt_tier.infer_context_window**
        (单一真相源), 本方法只在其之上叠加用户显式配置 ``model.context_window``
        (网关有自定义限额时以配置为准)。纯展示用途, 别拿它当硬性预算。
        """
        from ..core.prompt_tier import infer_context_window

        try:
            configured = self._app.state.config.get("model.context_window") \
                if getattr(self, "_app", None) is not None else None
        except Exception:  # noqa: BLE001
            configured = None
        return infer_context_window(model=model, provider=provider, configured=configured)

    def _context_string(self) -> str:
        """底部上下文占用: context: X% (est/budget)。"""
        est = self._ctx_tokens or 0
        bud = self._ctx_budget or 0
        pct = min(100.0, est / bud * 100.0) if bud > 0 else 0.0
        self._context_pct = pct

        def _fmt(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:.0f}M"
            if n >= 1_000:
                return f"{n / 1_000:.1f}k"
            return str(n)

        return f"context: {pct:.0f}% ({_fmt(est)}/{_fmt(bud)})"

    def append_log(self, text: str, cls: Optional[str] = None,
                   max_len: int = _MAX_LOG_LEN) -> None:
        """追加一条事件日志 (超长自动截断, 防巨文本挤爆渲染)。

        max_len=0 表示不截断; 默认 2000 字符, 超出后截断并标注省略字数。
        """
        text = str(text)
        if max_len and len(text) > max_len:
            text = text[:max_len] + f"…[已截断 {len(text) - max_len} 字符]"
        if cls:
            self._events.append((cls, text))
        else:
            self._events.append(text)
        # 修剪: 超过 600 条才裁到 500 (避免每次 append 都做 O(n) 切片)
        if len(self._events) > 5000:
            del self._events[: len(self._events) - 4000]
        if self._app and self._app.is_running:
            self._app.invalidate()

    def confirm(self, prompt: str, *, expected: Optional[str] = None,
                position: Optional[int] = None) -> bool:
        """安全确认: 卡片渲染在对话区, 输入框只收 y/n (Kimi 风格)。

        旧实现是 ``app.run_in_terminal(lambda: input(...))`` —— 它会把提示直接
        print 到当前光标位置 (也就是输入框那一行), 长命令于是撑破输入框边框,
        观感上"确认框长在输入框里", 语义上也把确认混成了输入内容。

        现改为挂起式卡片: 工具线程阻塞在 threading.Event 上, 主线程继续渲染
        对话区 (底部追加确认卡片), 用户在输入框敲 y/n 后由 _resolve_confirm()
        写回结果并唤醒工具线程。
        """
        from tuan_cli.core.whitelist import interactive_confirm

        app = self._app
        running = app is not None and getattr(app, "is_running", False)
        if not running:
            # headless / 应用未启动: 没有 UI 可挂卡片, 退回终端 input (保持旧行为)
            return interactive_confirm(prompt, expected=expected, position=position)

        done = threading.Event()
        pending: Dict[str, Any] = {
            "prompt": prompt,
            "expected": expected,
            "position": position,
            "event": done,
            "result": False,
        }
        self._confirm_pending = pending
        self._follow = True          # 确认卡片必须可见: 强制回到底部
        # 刻意不碰 _busy: 确认发生在工具执行过程中 (此时 _busy 已为 True), 若在
        # 这里置 True 再于返回前置 False, 会把"工具仍在运行"误清成"已就绪",
        # 顶部状态提前显示就绪勾。输入框已由 _handle_enter 的 confirm_pending
        # 分支独占为答复通道, 不需要借 _busy 拦截新提交。
        try:
            app.invalidate()
        except Exception:  # noqa: BLE001
            pass

        # 阻塞等待用户应答。带 0.5s 心跳轮询是防死锁兜底: 若卡片被取消或应用
        # 已退出 (用户 Ctrl-Q), 不能让工具线程永远挂在这里。
        while not done.wait(timeout=0.5):
            if self._confirm_pending is not pending:
                break                       # 已被 _resolve_confirm 消费/替换
            if not getattr(app, "is_running", True):
                pending["result"] = False   # 应用退出 → 保守视为拒绝
                break
        return bool(pending.get("result", False))

    def _resolve_confirm(self, text: str) -> None:
        """解析命令确认输入并唤醒等待中的工具线程。

        - 无确认码时: y/yes/是 → 执行; n/no/否 → 取消;
        - 有确认码 (expected) 时: 必须精确键入该码才授权 (防误触放行高危命令)。
        """
        pending = self._confirm_pending
        if not pending:
            return
        raw = text.strip()
        choice = raw.lower()
        expected = pending.get("expected")
        if expected is not None:
            # 确认码模式: 必须精确键入, 否则一律视为拒绝 (不允许用 y 绕过)
            if raw.upper() == str(expected).upper():
                pending["result"] = True
                self.append_log(f"{SUCCESS_MARK} {t('tui.confirm_ok')}", cls="class:success")
            elif choice in ("n", "no", "2", "否", "取消", "cancel"):
                pending["result"] = False
                self.append_log(f"{FAILURE_MARK} {t('tui.confirm_no')}", cls="class:warning")
            else:
                self.append_log(t("tui.confirm_invalid_code", code=expected), cls="class:textdim")
                return
        elif choice in ("y", "yes", "1", "是", "执行", "ok"):
            pending["result"] = True
            self.append_log(f"{SUCCESS_MARK} {t('tui.confirm_ok')}", cls="class:success")
        elif choice in ("n", "no", "2", "否", "取消", "cancel"):
            pending["result"] = False
            self.append_log(f"{FAILURE_MARK} {t('tui.confirm_no')}", cls="class:warning")
        else:
            self.append_log(t("tui.confirm_invalid"), cls="class:textdim")
            return

        self._confirm_pending = None
        ev = pending.get("event")
        if ev is not None:
            ev.set()

    def cancel_confirm(self) -> None:
        """取消挂起中的确认 (退出/Ctrl-C 兜底), 一律按"拒绝"解冻工具线程。"""
        pending = self._confirm_pending
        if not pending:
            return
        self._confirm_pending = None
        pending["result"] = False
        ev = pending.get("event")
        if ev is not None:
            ev.set()

    # ============================================================ 运行

    def _run_submit(self, text: str) -> None:
        try:
            result = self.on_submit(text)
            self.end_stream()
            if result and not self._streamed:
                self.append_log(result)
        except Exception as exc:
            self.append_log(f"[错误] {type(exc).__name__}: {exc}")
        finally:
            self._busy = False
            self._streamed = False
            self._streaming = False
            self._moon_suppressed = False
            self._running.clear()
        if self._app and self._app.is_running:
            self._app.invalidate()

    def run(self) -> None:
        """启动 TUI: 默认处于加载态, 内核就绪后由 set_ready 切换。

        单一 Application / 事件循环: 不再有独立 Splash 全屏 App,
        因此不存在双屏 alt-screen 切换在 Windows Terminal(conpty) 下的崩溃。

        启动即把终端窗口/标签标题改为 "Tuan-CLI" (OSC 转义 + ConHost API
        双通道, 见 win_compat.set_terminal_title); 非 TTY / 失败静默跳过。

        若全屏模式在特殊终端下仍崩溃, 自动以内联模式 (full_screen=False,
        不抢占整屏/不走 alt-screen) 重试一次; 仍失败则抛给调用方回退 REPL。
        """
        # 窗口标题: "Windows powershell" 标签 → "Tuan-CLI" (启动即改, 退出不还原
        # —— 终端标题无标准查询接口, 竞品 TUI 同样留标题)。
        try:
            from .win_compat import set_terminal_title
            set_terminal_title(TERMINAL_TITLE)
        except Exception:  # noqa: BLE001 - 标题设置绝不阻断启动
            pass
        animator = threading.Thread(target=self._animate, name="tuan-anim", daemon=True)
        animator.start()
        try:
            if self._app is not None:
                self._app.run()
        except BaseException:
            import traceback as _rt
            _rt.print_exc()
            # 全屏 alt-screen 在某些 conpty 配置下会崩溃 -> 退回内联模式重试
            if self._app is not None:
                try:
                    from prompt_toolkit import Application
                    self._app = Application(
                        layout=self._app.layout,
                        key_bindings=self._app.key_bindings,
                        style=STYLE,
                        full_screen=False,
                        mouse_support=False,
                    )
                    self._app.run()
                    return
                except BaseException:
                    _rt.print_exc()
            raise
        finally:
            self._closed = True

    def close(self) -> None:
        self._closed = True
        if self._app and self._app.is_running:
            self._app.exit()

    def _animate(self) -> None:
        while not self._closed:
            if self._booting:
                self._frame = (self._frame + 1) % len(_SPLASH_FRAMES)
                time.sleep(0.08)
            elif self._busy or self._streaming or self._running:
                # 模型思考/流式/工具期间: 月亮转圈, 每帧 120ms
                self._moon_frame = (self._moon_frame + 1) % len(_MOON_FRAMES)
                self._frame = (self._frame + 1) % len(_SPLASH_FRAMES)
                time.sleep(_MOON_INTERVAL)
            else:
                time.sleep(0.3)
            if self._app and self._app.is_running:
                self._app.invalidate()

    # ============================================================ 渲染: 对话区

    # ============================================================ Markdown 渲染 (代码语法高亮)
    # pygments token 类别 -> 暗色主题十六进制前景 (GitHub Dark 风, 与品牌蓝协调)
    _CODE_TOKEN_COLORS: Dict[str, str] = {
        "Keyword": "#FF7B72",
        "Keyword.Constant": "#79C0FF",
        "Name.Function": "#D2A8FF",
        "Name.Class": "#FFA657",
        "Name.Builtin": "#79C0FF",
        "Name.Decorator": "#D2A8FF",
        "Name.Namespace": "#C9D1D9",
        "String": "#A5D6FF",
        "String.Doc": "#A5D6FF",
        "String.Escape": "#FFA657",
        "Number": "#79C0FF",
        "Comment": "#7D8590",
        "Operator": "#FF7B72",
        "Punctuation": "#C9D1D9",
        "Literal": "#A5D6FF",
        "Generic.Deleted": "#FFA198",
        "Generic.Inserted": "#7EE787",
        "Generic.Strong": "#C9D1D9 bold",
        "Generic.Emph": "#C9D1D9 italic",
        "Text": "#C9D1D9",
    }
    _CODE_DEFAULT = "#C9D1D9"

    def _color_for_token(self, ttype) -> str:
        """pygments token 类型 -> 十六进制前景色 (从具体到通用逐级回退)。"""
        for t in ttype.split():
            parts = str(t).split(".")
            key = ".".join(parts[1:]) if len(parts) > 1 else parts[0]
            if key in self._CODE_TOKEN_COLORS:
                return self._CODE_TOKEN_COLORS[key]
        return self._CODE_DEFAULT

    def _highlight_code(self, code: str, lang: str) -> List[List[Tuple[str, str]]]:
        """按语言做 pygments 语法着色, 返回逐逻辑行的 (颜色, 文本) 段列表。

        每段仅前景着色 (不铺背景), 以区别于正文; 每行即一个逻辑行, 供对话区
        软换行高度估算; 无法识别的语言回落纯文本。
        """
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token as _PToken
        code = code.rstrip("\n")
        try:
            lexer = get_lexer_by_name((lang or "text").lower(), stripnl=False)
            tokens = list(lexer.get_tokens(code))
        except Exception:
            tokens = [(_PToken.Text, code)]
        lines: List[List[Tuple[str, str]]] = []
        cur: List[Tuple[str, str]] = []
        for ttype, value in tokens:
            color = self._color_for_token(ttype)
            for idx, piece in enumerate(value.split("\n")):
                if idx > 0:
                    lines.append(cur)
                    cur = []
                if piece:
                    cur.append((color, piece))
        if cur:
            lines.append(cur)
        if not lines:
            lines.append([("", "")])
        return [ln if ln else [("", "")] for ln in lines]

    def _render_markdown_message(self, text: str) -> List[List[Tuple[str, str]]]:
        """把助手消息按 Markdown 渲染: 代码块语法高亮 + 语言标签, 其余纯文本。

        首行带 ● 状态符 (若事件已带则复用, 避免双 bullet); 正文延续行缩进 2 格;
        代码块以 `› lang` 标签引导、块内不缩进、结束补空行分隔。返回逻辑行列表。
        """
        import re
        fence_re = re.compile(r"^\s*```(\w*)\s*$")
        text = str(text)
        if text.startswith(STATUS_BULLET):
            text = text[len(STATUS_BULLET):]
        lines = text.lstrip("\n").split("\n")
        out: List[List[Tuple[str, str]]] = []
        first = True

        def push(segs: List[Tuple[str, str]], indent: bool = False) -> None:
            nonlocal first
            if first:
                if not (segs and segs[0][1].startswith(STATUS_BULLET)):
                    segs = [("class:textdim", STATUS_BULLET)] + segs
                first = False
            elif indent:
                segs = [("class:text", "  ")] + segs
            out.append(segs)

        i, n = 0, len(lines)
        while i < n:
            raw = lines[i]
            m = fence_re.match(raw)
            if m:
                lang = m.group(1) or ""
                code: List[str] = []
                i += 1
                while i < n and not lines[i].strip().startswith("```"):
                    code.append(lines[i])
                    i += 1
                i += 1  # 跳过结束围栏 (若存在)
                push([("class:textdim", f"› {lang}" if lang else "› code")])
                for cl in self._highlight_code("\n".join(code), lang):
                    out.append(cl)
                push([("", "")])
            else:
                push([("class:text", raw)], indent=True)
                i += 1
        return out

    def _msg_to_lines(self, role: str, text: str) -> List[List[Tuple[str, str]]]:
        # 用户消息: 整块暖金底 (气泡感) + 金色正文; 助手消息走 Markdown 渲染。
        if role == "user":
            bullet = USER_MESSAGE_BULLET
            userbg = "class:roleuser bg:#2b2416"
            bcls = ccls = cont = userbg
        else:
            # log/助手: 直接走 Markdown (代码块语法高亮), 不再逐行纯文本。
            return self._render_markdown_message(text)
        # 事件可能已带 bullet 前缀 (写入时角色标记), 渲染时防重复叠加 (修复双 ✨)。
        lines = str(text).lstrip("\n").split("\n")
        out: List[List[Tuple[str, str]]] = []
        for i, ln in enumerate(lines):
            if i == 0:
                seg: List[Tuple[str, str]] = []
                if bullet and not ln.startswith(bullet):
                    seg.append((bcls, bullet))
                if ln:
                    seg.append((ccls, ln))
                out.append(seg)
            else:
                out.append([(cont, "  " + ln)])
        return out

    def _colored_lines(self, cls: str, text: str) -> List[List[Tuple[str, str]]]:
        out: List[List[Tuple[str, str]]] = []
        for ln in str(text).split("\n"):
            out.append([(cls, ln)] if ln else [("", ln)])
        return out

    def _scrolled_lines(self, logic_only: bool = False) -> List[List[Tuple[str, str]]]:
        """构建对话区完整内容 (段落行列表), 并按滚动状态钉住光标行号。

        - 工具完成记录默认折叠为一行 "see N tool calls", Ctrl+O 展开逐条;
        - 返回的 list 每项是一行 (list[ (cls,text) ])。
        """
        # 信任确认态优先: 未知目录首次访问时整屏显示确认卡片 (不显示对话区)
        if self._trust_pending:
            paste = self._render_trust_confirm()
            if logic_only:
                return [[seg for seg in line] for line in _split_flat_lines(paste)]
            self._cursor_line = 0
            return _split_flat_lines(paste)

        if self._booting or self._boot_error:
            paste = self._render_boot()
            if logic_only:
                return [[seg for seg in line] for line in _split_flat_lines(paste)]
            self._cursor_line = 0
            return _split_flat_lines(paste)

        screen: List[List[Tuple[str, str]]] = []
        for ev in self._events:
            if isinstance(ev, tuple):
                screen.extend(self._colored_lines(ev[0], ev[1]))
            elif isinstance(ev, list):
                screen.append(ev)
            else:
                # 消息块间空行分隔: 对话不再是堆砌文字, 每轮提问/回答自成区块
                if screen and screen[-1]:
                    screen.append([])
                role = "user" if ev.startswith(USER_MESSAGE_BULLET) else "log"
                screen.extend(self._msg_to_lines(role, ev))

        # 本轮工具调用: 折叠成一行摘要 (see N), 展开时逐条; 始终镜像进审计面板
        if self._turn_tool_lines:
            if self._tool_detail:
                for ln in self._turn_tool_lines:
                    screen.append([("class:textdim", ln)])
            else:
                n = len(self._turn_tool_lines)
                screen.append([("class:primary", f"▸ see {n} tool calls (Ctrl+O)")])

        # 流式
        if self._streaming and self._stream_buf:
            screen.append([("class:text", STATUS_BULLET + self._stream_buf.lstrip(chr(10)))])
        elif self._busy and not self._running and not self._streaming and not self._moon_suppressed:
            moon = _MOON_FRAMES[self._moon_frame % len(_MOON_FRAMES)]
            screen.append([("class:primary", f"{moon} {t('tui.thinking')}")])
        # 在途工具
        for name in self._running:
            elapsed = self._tool_start_times.get(name)
            elapsed_str = f" ({time.monotonic() - elapsed:.1f}s)" if elapsed else ""
            screen.append([("class:textdim", t("tui.tool_run", name=name, time=elapsed_str))])

        if not screen:
            screen.append([("class:textdim", t("tui.ready_empty"))])

        # 命令确认卡片: 追加在对话区底部 (输入框上方)。放在这里而不是输入框里,
        # 是修复"确认框撑破输入框边框"的关键 —— 它现在是内容, 不是输入提示。
        if self._confirm_pending:
            screen.extend(_split_flat_lines(self._render_confirm_card()))

        if not logic_only:
            # 滚动定位: follow -> 钉在最后一行 (Window 自动滚到底); 否则钉在 _pin_t
            # (终端行单位) 映射回逻辑行, 保证长消息下也能逐屏回看顶部。
            n = len(screen)
            if self._follow:
                self._pin = 0
                self._pin_t = 0
                self._cursor_line = n - 1
            else:
                self._pin_t = max(0, min(self._pin_t, self._terminal_total() - 1))
                self._pin = self._pin_t_to_logic(self._pin_t)
                self._cursor_line = self._pin
        return screen

    def _render_conversation(self):
        """扁平化对话内容供 FormattedTextControl 渲染 (行间加 \\n)。"""
        screen = self._scrolled_lines()
        if not screen:
            return [("class:textdim", t("tui.ready_empty"))]
        flat: List[Tuple[str, str]] = []
        for i, line in enumerate(screen):
            for cls, seg in line:
                flat.append((cls, seg))
            if i < len(screen) - 1:
                flat.append(("", "\n"))
        return flat

    def _render_header(self):
        """顶部状态 HUD: 实时状态(启动转圈/思考月亮/就绪勾) + 模式 + 模型。"""
        parts: List[Tuple[str, str]] = []
        if self._trust_pending:
            parts.append(("class:warning", f"? {t('tui.trust_title')}"))
            return parts
        if self._confirm_pending:
            parts.append(("class:warning", f"? {t('tui.confirm_title')}"))
            return parts
        if self._booting:
            frame = _SPLASH_FRAMES[self._frame % len(_SPLASH_FRAMES)]
            parts.append(("class:primary", f"{frame} {t('tui.boot_starting')}"))
        elif self._busy or self._running or self._streaming:
            moon = _MOON_FRAMES[self._moon_frame % len(_MOON_FRAMES)]
            parts.append(("class:primary", f"{moon} {t('fs.processing')}"))
        else:
            parts.append(("class:success", f"{SUCCESS_MARK} {t('fs.ready')}"))
        if self._plan_mode:
            parts.append(("class:primary", f"  [{t('tui.plan_badge')}]"))
        if self._model_label:
            parts.append(("class:text", f"  {self._model_label}"))
        return parts

    def _render_footer(self):
        """单行底部状态栏: 模式 + 命令提示 + 模型 + 状态 + 目录 + git + context。

        格式: standard  +/命令  deepseek-v4-free 就绪  Qingxiaotuan Agent CLI  main[±]  ctx 0% (0/131.1k)
        模型名省略 provider 前缀 (欢迎盒 Model 行已含完整 prov/model);
        context 在窄屏下自动降级为 "ctx 0%" 保证 80 列不截断。
        """
        parts: List[Tuple[str, str]] = []

        # 信任确认期: 底栏只显示确认提示 (不展示模型/状态/目录; 超宽裁剪防溢出)
        if self._trust_pending:
            return self._clip_parts([("class:warning", " " + t("tui.trust_footer"))])
        # 命令确认期: 同上, 底栏让位给确认提示
        if self._confirm_pending:
            return self._clip_parts([("class:warning", " " + t("tui.confirm_footer"))])

        # 模式徽标 (standard / yolo / plan)
        mode_label = self._mode or "standard"
        if mode_label == "yolo":
            mode_cls = "class:error"
        elif mode_label == "plan":
            mode_cls = "class:primary"
        else:
            mode_cls = "class:warning"
        parts.append((mode_cls, mode_label))

        # Kimi 同款命令行提示: 仅当启用了命令补全且空闲时展示, 保持简短
        if self._commands and not self._busy and not self._streaming:
            parts.append(("class:textdim", f"  {t('tui.cmd_hint')}"))

        # 模型名 (去 provider 前缀) + 状态 (未配 key / thinking / ready / running tool)
        model = self._model_label or "default"
        if "/" in model:
            model = model.rsplit("/", 1)[-1]
        if self._no_key and not self._booting:
            status = t("tui.no_key_hint", env=self._no_key_env or "API Key")
            status_cls = "class:warning"
        elif self._booting:
            status = t("tui.boot_starting")
            status_cls = "class:textdim"
        elif self._busy or self._streaming:
            status = t("tui.thinking")
            status_cls = "class:text"
        elif self._running:
            tool = self._running[-1] if self._running else ""
            status = tool if tool else t("fs.ready")
            status_cls = "class:accent"
        else:
            status = t("fs.ready")
            status_cls = "class:success"
        parts.append(("class:text", f"  {model}"))
        parts.append((status_cls, f" {status}"))

        # 工作目录
        cwd = os.path.basename(os.path.normpath(self.workspace)) or self.workspace
        parts.append(("class:textdim", f"  {cwd}"))

        # git 分支 (紧凑: 去空格)
        git_branch = self._git_branch()
        if git_branch:
            parts.append(("class:textdim", f"  {git_branch.replace(' ', '')}"))

        # 注: 此处曾显示 "context: X% (est/budget)" 上下文占用条, 已移除 ——
        # 预算靠模型名猜 (所有模型都退化成 131.1k), 用量是字符数估算而非真实 token,
        # 数字既不准确又占版面。需要真实用量请用 /context 或 Web 工作台的上下文面板。
        # 收尾: 单行控件 (Window height=1 无软换行) 必须按显示宽度裁剪,
        # 否则 no_key 长提示/长模型名/长目录名会把底栏顶出屏幕 (文字溢出)。
        return self._clip_parts(parts)

    def _git_branch(self) -> str:
        """探测当前 git 分支 (带缓存, 避免每行渲染都调 git)。"""
        if not hasattr(self, "_git_branch_cache"):
            self._git_branch_cache = None
            self._git_branch_ts = 0.0
        now = time.monotonic()
        if now - self._git_branch_ts < 5.0 and self._git_branch_cache is not None:
            return self._git_branch_cache or ""
        try:
            import subprocess
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.workspace, capture_output=True, text=True, timeout=1
            )
            if r.returncode == 0 and r.stdout.strip():
                branch = r.stdout.strip()
                # 探测是否有未提交改动
                r2 = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=self.workspace, capture_output=True, text=True, timeout=1
                )
                dirty = " [±]" if r2.stdout.strip() else ""
                self._git_branch_cache = branch + dirty
            else:
                self._git_branch_cache = ""
        except Exception:
            self._git_branch_cache = ""
        self._git_branch_ts = now
        return self._git_branch_cache or ""

    # ============================================================ 信任确认对话框
    # 首次访问未知目录时由 cmd_chat._boot 调用 prompt_trust(): 挂起确认卡片并
    # 等待用户输入 y/n, 结果经 on_confirm 回调写回 workspace_trust.json 后才 set_ready。
    # 此方法曾在一次 TUI 重写中被误删, 导致 cmd_chat 的 hasattr(tui, "prompt_trust")
    # 恒为 False、确认对话框"又没了" —— 现恢复并加回归测试 (tests/test_tui_fixes.py)。
    def _resolve_trust(self, text: str) -> None:
        """解析信任确认输入: y/Y/yes → 信任 (trusted); n/N/no → 只读 (untrusted)。

        结果通过 on_confirm 回调写回 workspace_trust.json, 随后由 cmd_chat._boot
        的回调里调用 set_ready 完成就绪切换 (确认期间对话输入被挂起)。
        """
    def _resolve_trust(self, text: str) -> bool:
        """解析信任确认输入: y/Y/yes → 信任 (trusted); n/N/no → 只读 (untrusted)。

        返回是否**消费**了这次输入 (True = 已按 y/n 处理; False = 不是 y/n,
        由调用方决定后续, 例如把这句当正常消息继续)。
        """
        pending = self._trust_pending or {}
        cb = pending.get("on_confirm")
        choice = text.strip().lower()
        if choice in ("y", "yes", "1", "是", "信任", "trust"):
            trusted = True
            self.append_log(f"{SUCCESS_MARK} {t('tui.trust_ok')} {pending.get('workspace', '')}",
                            cls="class:success")
        elif choice in ("n", "no", "2", "否", "只读", "readonly"):
            trusted = False
            self.append_log(f"{FAILURE_MARK} {t('tui.trust_no')} {pending.get('workspace', '')}",
                            cls="class:warning")
        else:
            return False
        self._trust_pending = None
        if callable(cb):
            try:
                cb(trusted)
            except Exception as exc:  # noqa: BLE001
                self.append_log(f"[信任确认回调] {type(exc).__name__}: {exc}", cls="class:error")
        return True

    def prompt_trust(self, workspace: str, project_name: str = "",
                     on_confirm: Optional[Callable[[bool], None]] = None) -> None:
        """首次访问未知目录: 显示 Kimi/Claude Code 风格信任确认卡片, 等待用户输入 y/n。

        确认后通过 on_confirm(trusted) 回调写回 workspace_trust.json 并继续就绪流程;
        在此之前 set_ready 不会被调用 (由 cmd_chat._boot 在回调里完成)。
        """
        self._trust_pending = {
            "workspace": workspace,
            "project_name": project_name,
            "on_confirm": on_confirm,
        }
        self._trust_index = 0  # 重置高亮到默认项 (信任)
        self._booting = False       # 退出加载态, 显示确认卡片 + 输入框
        self._boot_error = None
        if self._app and self._app.is_running:
            self._app.invalidate()

    def _clip_dw(self, s: str, n: int) -> str:
        """按显示宽度截断到 ≤ n, 末尾补省略号 (省略号占 1 列, 不超上限)。"""
        if _disp_width(s) <= n:
            return s
        res = ""
        for ch in s:
            if _disp_width(res) + _disp_width(ch) > n - 1:  # 留 1 列给 "…"
                break
            res += ch
        return res + "…"

    def _box_row(self, segs: List[Tuple[str, str]], inner: int,
                 pad: str = "  ") -> List[Tuple[str, str]]:
        """把一段 (cls, text) 拼成带左右边框的一行, 右侧对齐竖线。

        内容总宽超过 inner-2 时从最后一段按显示宽度截断 (补省略号),
        防止窄屏下长标题/说明/选项行撑破右边框。供信任确认卡片与命令
        确认卡片共用, 保证两类卡片排版完全一致。
        """
        body_w = sum(_disp_width(s) for _, s in segs)
        if body_w > inner - 2:
            avail = inner - 2
            clipped: List[Tuple[str, str]] = []
            for cls, s in segs:
                w = _disp_width(s)
                if w <= avail:
                    clipped.append((cls, s))
                    avail -= w
                else:
                    clipped.append((cls, self._clip_dw(s, avail)))
                    avail = 0
                    break
            segs = clipped
            body_w = sum(_disp_width(s) for _, s in segs)
        line: List[Tuple[str, str]] = [("class:primary", "│")]
        line.append(("", pad))
        line.extend(segs)
        line.append(("", " " * max(0, inner - 2 - body_w)))
        line.append(("class:primary", "│"))
        return line

    def _render_trust_confirm(self) -> List[Tuple[str, str]]:
        """Kimi/Claude Code 风格信任确认卡片 (全宽盒子, 复用欢迎盒排版)。"""
        pending = self._trust_pending or {}
        ws = str(pending.get("workspace", ""))
        width = self._box_width()
        inner = max(1, width - 2)   # 边框内侧显示列数
        pad = "  "

        clip_dw = self._clip_dw

        def row(segs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            return self._box_row(segs, inner, pad)

        out: List[Tuple[str, str]] = [("class:primary", "╭" + "─" * (width - 2) + "╮\n")]
        out += row([("class:warning", t("tui.trust_title"))])
        out.append(("", "\n"))
        out += row([("class:boxsub", t("tui.trust_folder") + ": "),
                    ("class:text", clip_dw(ws, max(1, inner - 4 - _disp_width(t("tui.trust_folder") + ": "))))])
        out.append(("", "\n"))
        for ln in t("tui.trust_desc").split("\n"):
            out += row([("class:textdim", ln)])
            out.append(("", "\n"))
        out += row([("class:success", t("tui.trust_opt"))])
        out.append(("", "\n"))
        # 选项列表 (↑↓ 选择 · Enter 确认; 也可直接输入 1/2 或 y/n):
        # 此前这两行选项被遗漏渲染, 导致对话框"有标题没选项、完全无法进入工作区"。
        for _i, (_label, _desc) in enumerate((
            (t("tui.trust_opt_trust"), t("tui.trust_opt_trust_desc")),
            (t("tui.trust_opt_distrust"), t("tui.trust_opt_distrust_desc")),
        )):
            _sel = self._trust_index == _i
            _mark = "▶ " if _sel else "  "
            out += row([("class:accent" if _sel else "class:textdim",
                         f"{_mark}{_i + 1}) {_label}")])
            out.append(("", "\n"))
            out += row([("class:textdim", "   " + clip_dw(_desc, max(1, inner - 4)))])
            out.append(("", "\n"))
        out.append(("class:primary", "╰" + "─" * (width - 2) + "╯\n"))
        out.append(("", "\n"))
        out.append(("class:textdim", "  " + clip_dw(t("tui.trust_prompt"), max(1, inner - 2)) + "\n"))
        return out

    def _wrap_dw(self, text: str, width: int) -> List[str]:
        """按显示宽度把长文本切成多行 (CJK 宽字符按 2 列计)。

        确认卡片里的命令正文往往很长 —— 若只做单行截断, 用户看不到命令尾部
        (而那恰恰可能是 `rm -rf /` 之类的关键部分)。这里改为折行铺满卡片宽度,
        保证命令完整可读。
        """
        if width <= 0:
            return [text]
        out: List[str] = []
        cur = ""
        cw = 0
        for ch in text:
            try:
                w = max(0, _wcswidth(ch))
            except Exception:  # noqa: BLE001 - 极端字符宽度探测失败按 1 列
                w = 1
            if cw + w > width and cur:
                out.append(cur)
                cur = ""
                cw = 0
            cur += ch
            cw += w
        out.append(cur)
        return out or [""]

    def _render_confirm_card(self) -> List[Tuple[str, str]]:
        """Kimi 风格命令确认卡片 (与信任卡片同排版)。

        取代旧的 run_in_terminal 方案: 旧方案把提示 print 到输入框所在光标位置,
        长命令直接撑破输入框边框, 且"确认"在语义上变成了输入框内容 —— 既不美观
        也不该出现在那儿。现在卡片渲染在对话区底部, 输入框只负责收 y/n。
        """
        pending = self._confirm_pending or {}
        width = self._box_width()
        inner = max(1, width - 2)
        pad = "  "
        clip_dw = self._clip_dw

        def row(segs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            return self._box_row(segs, inner, pad)

        out: List[Tuple[str, str]] = [("class:primary", "╭" + "─" * (width - 2) + "╮\n")]
        out += row([("class:warning", t("tui.confirm_title"))])
        out.append(("", "\n"))
        # 命令正文逐行铺开; 超宽行折行而非截断, 保证命令尾部可见
        for ln in str(pending.get("prompt", "")).split("\n"):
            for seg in self._wrap_dw(ln, max(1, inner - 4)):
                out += row([("class:text", seg)])
                out.append(("", "\n"))
        expected = pending.get("expected")
        if expected is not None:
            out += row([("class:boxsub", t("tui.confirm_code_hint", code=expected))])
            out.append(("", "\n"))
        out += row([("class:success", t("tui.confirm_opt"))])
        out.append(("", "\n"))
        out.append(("class:primary", "╰" + "─" * (width - 2) + "╯\n"))
        out.append(("", "\n"))
        out.append(("class:textdim", "  " + clip_dw(t("tui.confirm_prompt"), max(1, inner - 2)) + "\n"))
        return out

    def _show_welcome(self) -> None:
        """就绪后展示欢迎盒 (吉祥物/模型/项目目录)。

        盒子逐行作为事件 (分段列表) 追加, 由 _render_conversation 按行渲染,
        保证 CJK/绘图形字符下右边框仍对齐。
        """
        cwd = os.path.abspath(self.workspace)
        session = getattr(self, "_session_id", "") or "new-session"
        model = self._model_label or "default"
        info_pairs = [
            (f"{t('banner.directory')}: ", cwd),
            (f"{t('banner.session')}:   ", session),
            (f"{t('banner.model')}:     ", model),
            (f"{t('banner.version')}:   ", VERSION),
        ]
        for row in self._kimi_box(
            title=t("tui.welcome_title"),
            subtitle=t("tui.welcome_subtitle"),
            info_pairs=info_pairs,
        ):
            self._events.append(row)
