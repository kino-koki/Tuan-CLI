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


def _display_width(s: str) -> int:
    """整串的终端显示宽度 —— 宽度计算的热路径, 必须走一次 C 调用而不是逐字 Python 循环。

    渲染每一帧都要给全部历史行算宽度 (见 `_line_heights`)。逐字符调用
    ``_wcswidth`` 是 Python 层循环, 2000 行历史每帧要多跑几万次函数调用
    (实测约 30ms/帧), 而流式输出时每帧都要重算, 直接表现为卡顿。
    ``wcwidth.wcswidth`` 内部是 C 实现且自带组合字符/东亚宽字符处理, 整串调用
    结果与逐字累加一致。

    例外: 串里含**控制字符**时 ``wcswidth`` 返回 -1 (表示"无法计算"), 此时回退
    逐字累加, 保持与旧实现一致的行为, 不能让 -1 变成 0 宽度而算错行高。
    """
    if not s:
        return 0
    if _wcswidth_impl is not None:
        w = _wcswidth_impl(s)
        if w >= 0:
            return w
    return sum(max(0, _wcswidth(ch)) for ch in s)

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
    from prompt_toolkit.keys import Keys
    _HAS_PT = True
except Exception:
    # prompt_toolkit 是可选依赖, 缺失时本模块仍必须可导入 —— cli/cmd_chat.py 会
    # import 本文件取配色/常量, 若在 `class _SlashCompleter(Completer)` 处 NameError,
    # 整个 CLI 会连带炸掉。这里补占位符号: 类定义能通过, 真正用到补全时才报清晰错误。
    _HAS_PT = False


# prompt_toolkit 缺失时的占位符: 键位绑定只在 _HAS_PT 为真时构建, 这里只是让
# 模块级名字 `Keys` 可解析。
class _MissingKeys:
    def __getattr__(self, _name: str) -> str:
        return f"<missing:{_name}>"


if not _HAS_PT:  # pragma: no cover - 仅在无 prompt_toolkit 环境
    Keys = _MissingKeys()      # type: ignore[assignment]

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
_BG_PANEL = "#1E2836"     # 面板背景色 (补全菜单用，与 _BORDER 同色系)
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
    # ---- Diff 实时面板 (Ctrl+D) ----
    # 用 git 通用配色: 新增=绿, 删除=红。这是 diff 的全球共识, 不按地区习惯翻转 ——
    # 与「涨跌红绿」的行情配色无关, 这里按开发者肌肉记忆走。
    "diffadd": "#7ED492",             # + 行: 绿
    "diffdel": "#F08A8A",             # - 行: 红
    # ---- 补全菜单 ("/" 命令提示)：对齐主色板 ----
    "completion-menu":                         f"bg:{_BG_PANEL} {_TEXT}",
    "completion-menu.completion":              f"bg:{_BG_PANEL} {_TEXT}",
    "completion-menu.completion.current":      f"bg:{_PRIMARY} {_TEXT}",
    "completion-menu.meta.completion":         f"bg:{_BG_PANEL} {_DIM}",
    "completion-menu.meta.completion.current": f"bg:{_PRIMARY} {_MUTED}",
    "completion-menu.multi-column-meta":       f"bg:{_BG_PANEL} {_DIM}",
    "completion-menu.border":                  _BORDER,
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


def _env_flag(name: str) -> bool:
    """读布尔环境变量: 1/true/yes/on 为真, 0/false/no/off/空 为假。

    用于给 TUI 行为开关提供"不改代码就能关"的逃生通道 (如 TUAN_NO_MOUSE
    关闭滚轮上报以恢复鼠标选中文本)。
    """
    v = str(os.environ.get(name, "") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


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


def _ask_user_plain(question: str, options: List[str]) -> str:
    """无界面时 (headless / 应用未启动) 的纯文本提问兜底。

    **绝不能**在全屏 TUI 里调用 —— print/input 会直接写进 prompt_toolkit 掌管的
    屏幕。调用方 (QxtTUI.ask_user) 已先用 is_running 判定过。
    """
    if not options:
        try:
            return input(f"? {question}\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
    print(f"\n? {question}")
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if not raw:
        return options[0]
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw


class _MeasuredWindow(Window):
    """对话区窗口: 在渲染时记录**实际**分配到的宽度与高度。

    对话区高度取决于终端行数、审计面板 (Ctrl+O) 是否展开、`/` 命令面板占几行,
    布局算式很容易和实际差 1~2 行 —— 而虚拟视口要按"正好一屏"切片, 差一行
    就会露白/截断。宽度同理: 对话区宽度会被右侧 diff 面板 (Ctrl+D) 吃掉一块,
    估算值 (`列数-2`) 与真实值不一致时, 长消息的折行数算错, 切片随之错位。

    prompt_toolkit 在 `write_to_screen` 时把真实尺寸放在 `WritePosition` 上,
    这里记下来供 `_viewport_rows()` / `_log_width()` 使用 (首帧无记录, 退化为
    按终端尺寸估算, 第二帧起即为精确值)。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.measured_height = 0
        self.measured_width = 0
        super().__init__(*args, **kwargs)

    def write_to_screen(self, screen: Any, mouse_handlers: Any,
                        write_position: Any, parent_style: str,
                        erase_bg: bool, z_index: Optional[int] = None) -> None:
        try:
            h = int(getattr(write_position, "height", 0) or 0)
            if h > 0:
                self.measured_height = h
            w = int(getattr(write_position, "width", 0) or 0)
            if w > 0:
                self.measured_width = w
        except Exception:  # noqa: BLE001 - 测量失败不影响渲染
            pass
        super().write_to_screen(screen, mouse_handlers, write_position,
                                parent_style, erase_bg, z_index)


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

    传入 ``tiers`` (命令 -> "core"|"expert"|"hidden") 后: 空输入 `/` 时
    仅返回核心层命令 (≤ 20 项, 防止 55 项菜单压垮屏幕); 输入具体前缀时
    保留全量补全 (专家层命令按前缀可达)。
    """

    def __init__(
        self,
        words: List[str],
        metas: Optional[Dict[str, str]] = None,
        tiers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._words = list(words)
        self._metas = dict(metas or {})
        self._tiers: Dict[str, str] = dict(tiers or {})

    def get_completions(self, document, complete_event):  # noqa: C901
        from ..cli.slash_tier import slash_command_tier

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
            # 有 tiers 配置时使用传入的 tiers; 无 tiers 时用模块级 slash_command_tier
            if self._tiers:
                tier = self._tiers.get("/" + name, "core")
            else:
                from ..cli.slash_tier import slash_command_tier
                tier = slash_command_tier("/" + name)
            # 隐藏层命令永不进入补全菜单 (仅 /help 全量列出)
            if tier == "hidden":
                continue
            # 空输入时仅补全核心层 (有 tiers 配置且未输入前缀才启用过滤)
            if not rest and self._tiers and tier != "core":
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
        command_tiers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.on_command = on_command
        self.title = title
        self.workspace = workspace
        # Kimi 同款 `+/命令` 补全词表: 传入则启用补全, 缺省 (兼容旧调用) 则不启用。
        self._commands: List[str] = list(commands or [])
        self._command_meta: Dict[str, str] = dict(command_meta or {})
        # 命令层级表 (命令 -> "core"|"expert"|"hidden"): 空前缀时仅展开核心层,
        # 前缀匹配时全量展开 (专家层命令按首字母可达)。缺省 None 保持旧行为。
        self._command_tiers: Dict[str, str] = dict(command_tiers or {})
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
        # 模型向用户提问态 (ask_user 工具): 与 confirm 同构 —— 工具线程阻塞在
        # Event 上, 卡片渲染在对话区底部, 用户 ↑↓ 选高亮 / Enter 确认 (也可直接
        # 敲编号或自由作答) 后由 _resolve_ask() 唤醒。
        # 此前 TUI 未实现该钩子, ask_user 直接 print()+input() 打到 stdout ——
        # 在全屏 TUI 里既冲垮布局 (溢出) 又无法正常输入 (选不了)。
        self._ask_pending: Optional[Dict[str, Any]] = None
        self._ask_index: int = 0       # 选项高亮项 (自由作答时为 -1 之外的语义, 见 _ask_move)
        self._ask_free: bool = False   # 用户是否已进入"自由作答"模式 (输入非编号文本)
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

        # Diff 实时面板 (对标 Claude Code 的 /diff 并排实时面板): Ctrl+D 开合。
        # 面板在渲染时同步取一次工作区 diff, 但按 _diff_fetched_at 节流 (默认 1.5s),
        # 避免模型连续改文件时每个重绘帧都 fork 一个 git 进程。
        self._diff_visible = False
        self._diff_cache: List[Tuple[str, str]] = []   # 已渲染的 (cls, text) 行
        self._diff_summary = ""                        # 顶部统计行 (N files +A -B)
        self._diff_error = ""                          # 非 git 仓库 / git 缺失等
        self._diff_fetched_at = 0.0
        self._diff_width = 0                           # 0 = 运行时按终端宽度计算

        # 对话区滚动: **虚拟视口** (见 _render_conversation / _scroll_log)。
        # `_follow` 为 True 时视口钉在最新内容底部 (新内容自动跟随); 手动上翻后
        # 为 False, `_view_top` 记录视口顶端对应的终端行号, 新内容不再把视图拽走。
        # (早期实现用 FormattedTextControl.get_cursor_position 伪造"光标行"来驱动
        #  Window 滚动 —— prompt_toolkit 只会**最小幅度**滚动到该点可见, PgUp 根本
        #  翻不动一屏, 且逻辑行/终端行错位后中段内容永远够不到, 故改为真视口切片。)
        self._follow = True
        self._view_top = 0        # 视口顶端对应的终端行号 (整段内容里的偏移)
        # 工具调用折叠 (Claude/TraeWork 风格 "see"): 本轮工具完成记录先折叠成
        # 一行摘要, Ctrl+O 展开查看每步细节 (同时镜像进审计面板)。
        self._turn_tool_lines: List[str] = []
        self._tool_detail = False

        # prompt_toolkit
        self._app: Optional[Any] = None
        # 对话区内容由 `_render_conversation` 自行按视口切片 (只返回当前可见的那些
        # 终端行), 因此**不注册** get_cursor_position —— 让它保持默认 Point(0,0):
        # 切片高度恰好等于窗口高度, Window 无需再自行滚动, 二者互不干扰。
        # (早期靠伪造 get_cursor_position 驱动 Window 滚动, 见 _follow 处注释。)
        self._log_control = FormattedTextControl(
            self._render_conversation,
            show_cursor=False,
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

        # 对话区占满剩余空间: 自绘虚拟视口 (自己切片内容 + 自己算滚动), 不用
        # ScrollablePane (后者在 Windows/conpty 下碎滚动) 也不用伪造光标定位。
        # 用 _MeasuredWindow 记录真实高度, 供 _viewport_rows() 精确切片。
        self._log_window = _MeasuredWindow(
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
                # 主体 (对话区 + 审计面板) 与右侧 diff 面板并排 (Claude Code /diff 同款)。
                # VSplit 而非手工拼字符: 让 prompt_toolkit 自己分配宽度, 避免在窄终端
                # 下把对话区压成一条缝。
                VSplit([
                    HSplit([
                        conversation,
                        # 审计面板: 仅当展开时占空间
                        audit_wrap,
                    ]),
                    ConditionalContainer(
                        HSplit([
                            Window(width=1, char="│", style="class:border"),
                            Window(
                                FormattedTextControl(
                                    self._render_diff_panel, show_cursor=False,
                                    focusable=False,
                                ),
                                width=lambda: self._diff_panel_width(),
                                wrap_lines=False,
                                style="class:slashbg",
                            ),
                        ]),
                        filter=Condition(
                            lambda: self._diff_visible and self._diff_panel_available()
                        ),
                    ),
                ]),
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

        # 鼠标滚轮回看历史 (Claude Code 同款)。开启后终端把滚轮上报为转义序列,
        # 代价是**鼠标左键拖选复制被终端截走**(选不中文字)。可用
        # TUAN_NO_MOUSE=1 临时关掉滚轮、恢复文本选择。
        mouse = not _env_flag("TUAN_NO_MOUSE")

        try:
            self._app = Application(
                layout=layout,
                key_bindings=self._build_keys(),
                style=STYLE,
                full_screen=True,
                mouse_support=mouse,
                output=output,
            )
        except Exception as exc:
            if type(exc).__name__ != "NoConsoleScreenBufferError":
                raise
            # DummyOutput 不上报鼠标, 但键位绑定仍保留滚轮处理 ——
            # 部分终端 (conpty 的部分模式) 由应用层注入 MouseEvent。
            self._app = Application(
                layout=layout,
                key_bindings=self._build_keys(),
                style=STYLE,
                full_screen=True,
                mouse_support=mouse,
                output=DummyOutput(),
            )

    # ============================================================ 键位

    def _request_exit(self, event) -> None:
        """Ctrl-C / Ctrl-Q 退出: 先解冻挂起的确认 (按"拒绝"处理) 再退出应用。

        否则工具线程会一直阻塞在确认 Event 上 —— 线程的等待循环虽有应用退出
        兜底, 但显式解冻能让"用户取消"这一结果被正常回传与记录, 语义更干净。
        """
        self.cancel_confirm()
        self.cancel_ask()
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

        # ---- 对话区回卷 (Claude Code 同款): 整屏翻页 / 逐行 / 到顶到底 ----
        # (不用 Ctrl+U/Ctrl+D: 会被输入框的编辑键抢占, 见 TextArea buffer 绑定)
        @kb.add("pageup")
        def _(event):
            self._scroll_log(-self._viewport_rows())
            event.app.invalidate()

        @kb.add("pagedown")
        def _(event):
            self._scroll_log(self._viewport_rows())
            event.app.invalidate()

        # Shift+PgUp/PgDn: 逐行微调 (整屏翻页有时太粗, 尤其快到顶/底时)
        @kb.add("s-pageup")
        def _(event):
            self._scroll_log(-1)
            event.app.invalidate()

        @kb.add("s-pagedown")
        def _(event):
            self._scroll_log(1)
            event.app.invalidate()

        # Ctrl+↑/↓: 同样逐行翻 (终端不总把 Shift+PgUp 传对时的等价键)
        @kb.add("c-up")
        def _(event):
            self._scroll_log(-1)
            event.app.invalidate()

        @kb.add("c-down")
        def _(event):
            self._scroll_log(1)
            event.app.invalidate()

        @kb.add("home")
        def _(event):
            self._scroll_to_top()
            event.app.invalidate()

        @kb.add("end")
        def _(event):
            self._scroll_to_bottom()
            event.app.invalidate()

        # ---- 鼠标滚轮: 回看对话历史 (Claude Code 同款) ----
        # prompt_toolkit 把鼠标事件送进按键系统, 分两条通道 (见
        # prompt_toolkit/key_binding/bindings/mouse.py):
        #   - `Keys.Vt100MouseEvent`: VT100/xterm/SGR 序列 (终端上报
        #     `ESC [ < 64 ; col ; row M` 等), conpty 走这条;
        #   - `Keys.WindowsMouseEvent`: Windows 原生控制台鼠标事件。
        # 两条都要接, 且**只能靠 event.data 的 event_type 区分滚轮与点击** ——
        # 滚轮不是独立键名 (`<scroll-up>` 在本版本 pt 里解析不出来)。
        # Shift+方向键也一并接: 部分终端把滚轮降级报成它。
        @kb.add(Keys.Vt100MouseEvent)
        @kb.add(Keys.WindowsMouseEvent)
        def _(event):
            data = getattr(event, "data", None)
            etype = getattr(data, "event_type", None)
            name = getattr(etype, "name", "") or str(etype)
            if name == "SCROLL_UP":
                self._mouse_wheel(event, up=True)
                return
            if name == "SCROLL_DOWN":
                self._mouse_wheel(event, up=False)
                return
            # 点击/移动: 不消费, 交回默认 (终端自己做选中复制)

        @kb.add("s-up")
        def _(event):
            self._mouse_wheel(event, up=True)

        @kb.add("s-down")
        def _(event):
            self._mouse_wheel(event, up=False)

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
            if self._ask_pending:
                self._ask_move(1)
                event.app.invalidate()
                return
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
            if self._ask_pending:
                self._ask_move(-1)
                event.app.invalidate()
                return
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

        @kb.add("c-d")
        def _(event):
            """Ctrl+D 开合右侧 diff 实时面板 (Claude Code 同款)。"""
            self.toggle_diff()
            event.app.invalidate()

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

    # ---- Diff 实时面板 ----

    def _diff_panel_width(self) -> int:
        """面板宽度: 取终端宽度的 40%, 钳制在 [32, 64] 列。

        低于 ~90 列时不显示面板 (见 `_diff_panel_available`), 因为左右各留一半后
        对话区会被压到不可读。
        """
        if self._diff_width:
            return self._diff_width
        total = self._terminal_cols()
        w = int(total * 0.4)
        return max(32, min(64, w))

    def _diff_panel_available(self) -> bool:
        """终端太窄时不开面板, 避免把对话区压成一条缝。"""
        return self._terminal_cols() >= 90

    def toggle_diff(self) -> None:
        """Ctrl+D 开合 diff 面板。"""
        if not self._diff_visible and not self._diff_panel_available():
            self._audit_log.append((
                "class:textdim",
                t("tui.diff_too_narrow", width=self._terminal_cols()),
            ))
            if self._app and self._app.is_running:
                self._app.invalidate()
            return
        self._diff_visible = not self._diff_visible
        if self._diff_visible:
            self._diff_fetched_at = 0.0        # 立刻刷新一次
        if self._app and self._app.is_running:
            self._app.invalidate()

    def _fetch_diff(self) -> None:
        """同步取一次工作区 diff 并切好颜色。

        只在面板可见时调用; 由 `_render_diff_panel` 按 1.5s 节流触发, 所以这里的
        开销最多是"每秒不到一次 fork git"。
        """
        import os
        import subprocess

        self._diff_fetched_at = time.monotonic()
        try:
            ws = getattr(self, "_workspace", None) or os.getcwd()
            proc = subprocess.run(  # noqa: S603 - 固定参数, 无用户输入拼接
                ["git", "diff", "--no-color"], cwd=ws,
                capture_output=True, text=True, timeout=10, errors="replace",
            )
        except FileNotFoundError:
            self._diff_error = t("tui.diff_no_git")
            self._diff_cache = []
            self._diff_summary = ""
            return
        except subprocess.TimeoutExpired:
            self._diff_error = t("tui.diff_timeout")
            self._diff_cache = []
            self._diff_summary = ""
            return
        except Exception as exc:  # noqa: BLE001 - 面板失败不能影响主界面
            self._diff_error = t("tui.diff_failed", error=exc)
            self._diff_cache = []
            self._diff_summary = ""
            return

        if proc.returncode != 0 and not proc.stdout:
            self._diff_error = (proc.stderr or "").strip()[:200] or t("tui.diff_not_repo")
            self._diff_cache = []
            self._diff_summary = ""
            return

        self._diff_error = ""
        files = added = removed = 0
        rows: List[Tuple[str, str]] = []
        width = self._diff_panel_width()

        def cut(raw: str) -> str:
            """按**显示宽度**截断到面板宽度。

            旧实现用 `raw[:width]` 按字符数截断, 对中文/emoji 完全失效 ——
            一个汉字占 2 列, 一行 60 字的中文注释实际要120 列, 而面板
            `wrap_lines=False`, 超宽内容会直接顶破布局 (右侧面板压到终端右边界
            之外, 表现为"溢出/错位")。
            """
            return self._clip_dw(raw, max(1, width))

        for raw in (proc.stdout or "").splitlines():
            if raw.startswith("diff --git"):
                files += 1
                rows.append(("class:primary", cut(raw)))
                continue
            if raw.startswith(("+++", "---")):
                rows.append(("class:textdim", cut(raw)))
                continue
            if raw.startswith("@@"):
                rows.append(("class:accent", cut(raw)))
                continue
            if raw.startswith("+"):
                added += 1
                rows.append(("class:diffadd", cut(raw)))
                continue
            if raw.startswith("-"):
                removed += 1
                rows.append(("class:diffdel", cut(raw)))
                continue
            if raw.startswith(("index ", "new file", "deleted file", "similarity ")):
                rows.append(("class:textdim", cut(raw)))
                continue
            rows.append(("class:text", cut(raw)))

        self._diff_summary = (
            t("tui.diff_summary", files=files, added=added, removed=removed)
            if files else t("tui.diff_clean")
        )
        self._diff_cache = rows

    def _render_diff_panel(self):
        """右侧 diff 面板内容 (对标 Claude Code /diff 的并排实时面板)。

        该面板的 Window 是 `wrap_lines=False` (diff 需要保持原始行、不折行),
        因此**每一行都必须在渲染出口按显示宽度硬裁** —— 与对话区不同, 这里
        一旦超宽就是真的顶破布局 (面板溢出终端右边界 / 把整屏挤错位)。
        """
        if not self._diff_visible:
            return []
        # 节流刷新: 面板开着时模型连续改文件, 每个重绘帧都 fork git 会拖慢 TUI。
        if time.monotonic() - self._diff_fetched_at > 1.5:
            self._fetch_diff()

        width = max(1, self._diff_panel_width())

        def row(cls: str, text: str) -> Tuple[str, str]:
            return (cls, self._clip_dw(text, width))

        out: List[Tuple[str, str]] = []
        out.append(row("class:primary", t("tui.diff_title")))
        if self._diff_error:
            out.append(("", "\n"))
            out.append(row("class:textdim", self._diff_error))
            return out

        out.append(row("class:textdim", f" {self._diff_summary}"))
        out.append(("", "\n"))
        out.append(row("class:textdim", "  " + t("tui.diff_hint")))
        out.append(("", "\n"))
        if not self._diff_cache:
            out.append(row("class:textdim", "  " + t("tui.diff_clean")))
            return out

        for i, (cls, seg) in enumerate(self._diff_cache):
            if i:
                out.append(("", "\n"))
            # 双重保险: _fetch_diff 已按显示宽度裁过, 这里再裁一次以覆盖
            # 外部直接写入 _diff_cache 的路径 (测试/未来功能)。
            out.append(row(cls, seg))
        return out

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

    def _terminal_cols(self) -> int:
        """终端总列宽 (面板宽度/可用性判定用)。"""
        try:
            cols = self._app.output.get_size().columns if self._app else 0
        except Exception:
            cols = 0
        if cols <= 0:
            try:
                cols = shutil.get_terminal_size((80, 24)).columns
            except Exception:
                cols = 80
        return int(cols)

    def _log_width(self) -> int:
        """对话区可视列宽 (供软换行高度估算)。

        优先用 `_MeasuredWindow` 实测的宽度 —— 对话区实际宽度会被右侧 diff 面板
        (Ctrl+D) 吃掉一块, 用"终端列数-2"估算会偏大, 长消息折行数算少, 虚拟
        视口切片随之错位 (表现为回卷时露白/跳行)。首帧尚无实测值时退化为估算。
        """
        try:
            m = int(getattr(self._log_window, "measured_width", 0) or 0)
        except Exception:
            m = 0
        if m > 0:
            return m
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

    def _visible_log_rows(self) -> int:
        """对话区**理论上限**可视行数: 按当前布局从终端总行数里逐项扣减。

        为什么需要它: `_viewport_rows()` 信任 `_MeasuredWindow.measured_height`,
        而那个值是**上一帧** write_to_screen 时记下的。布局刚变化的帧 (Ctrl+O 展开
        审计面板 / 打开 "/" 命令面板 / 输入框长到多行 / 切换 diff 面板 / 终端改大小),
        实测值还是旧的"大高度", 于是 `_viewport_slice` 会切出比窗口**能显示的更多行**。
        多出来的行会让 prompt_toolkit 的 Window 触发它自己的内部滚动 —— 于是"我们的
        视口"和"Window 的滚动"两套机制打架, 表现就是上翻后内容被顶掉、翻不动。

        这里算出当前布局下的**上界**, 供 `_viewport_rows()` 做钳制。
        """
        try:
            rows = self._app.output.get_size().rows if self._app else 0
        except Exception:
            rows = 0
        if rows <= 0:
            try:
                rows = shutil.get_terminal_size((80, 24)).lines
            except Exception:
                rows = 24
        # 输入框边框 3 行 + 底栏 1 行
        budget = rows - 4
        # "/" 命令面板: 最多 _SLASH_MAX_VISIBLE 行 + 1 行边框
        if getattr(self, "_slash_open", False) and getattr(self, "_slash_items", None):
            try:
                budget -= int(self._slash_menu_rows()) + 1
            except Exception:
                budget -= _SLASH_MAX_VISIBLE + 1
        # 审计面板: 展开时约占 45% 高度 (与 _MeasuredWindow 里的说明一致)
        if getattr(self, "_audit_visible", False):
            budget = int(budget * 0.55)
        # 命令确认卡片 / 提问卡片按需占据底部若干行
        for attr in ("_confirm_pending", "_ask_pending"):
            if getattr(self, attr, None):
                budget -= 12
                break
        return max(3, budget)

    def _viewport_rows(self) -> int:
        """对话区视口高度 (终端行数) —— 实测值优先, 但**必须按当前布局钳制上界**。

        早期实现无条件相信实测高度, 布局变化的帧里它会过期, 导致切片超过窗口高度,
        进而触发 Window 的内部滚动, 把我们的视口顶掉 (见 `_visible_log_rows`)。
        """
        try:
            m = int(getattr(self._log_window, "measured_height", 0) or 0)
        except Exception:
            m = 0
        ceiling = self._visible_log_rows()
        if m > 0:
            # 实测值可能来自上一帧的旧布局; 取与当前布局上界的较小者。
            return max(3, min(m, ceiling))
        return ceiling

    def _line_heights(self, lines: List[List[Tuple[str, str]]]) -> List[int]:
        """每个逻辑行在 wrap_lines 下占的终端行数 (宽字符感知)。

        与 prompt_toolkit 的换行规则对齐: 按显示宽度断行; 空行/零宽占 1 行。
        视口偏移与切片都按**终端行**计量, 避免长消息 (无换行大段) 使逻辑行与
        终端行错位 → 中间内容永远够不到。
        """
        width = self._log_width()
        heights: List[int] = []
        for line in lines:
            text = "".join(seg for _, seg in line)
            if not text:
                heights.append(1)
                continue
            disp = _display_width(text)
            heights.append(max(1, math.ceil(disp / width)))
        return heights

    def _line_starts(self, heights: List[int]) -> List[int]:
        """每个逻辑行的起始终端行号 (前缀和) —— 视口切片的定位依据。"""
        starts: List[int] = []
        acc = 0
        for h in heights:
            starts.append(acc)
            acc += h
        return starts

    def _scroll_bounds(self, lines: List[List[Tuple[str, str]]]) -> Tuple[int, int, int]:
        """返回 (内容总终端行数, 视口高度, 视口顶端最大合法值)。"""
        total = sum(self._line_heights(lines))
        vp = self._viewport_rows()
        return total, vp, max(0, total - vp)

    def _resolve_view_top(self, max_top: int) -> int:
        """把 `_view_top` 钳到合法范围; follow 时钉在底部。"""
        if self._follow:
            self._view_top = max_top
        else:
            self._view_top = max(0, min(self._view_top, max_top))
        return self._view_top

    def _clip_line_rows(self, line: List[Tuple[str, str]], r0: int,
                        r1: int, width: int) -> List[Tuple[str, str]]:
        """取一个逻辑行里**显示行 [r0, r1)** 的部分 (视口顶/底切到半行时用)。

        按累计显示宽度判定每个字符落在哪个显示行 (`col // width`); 宽字符按其
        起始列归属, 与终端实际折行一致。整行命中时原样返回 (免拷贝)。
        """
        out: List[Tuple[str, str]] = []
        col = 0
        for cls, text in line:
            if not text:
                continue
            buf: List[str] = []
            for ch in text:
                if r0 <= (col // width) < r1:
                    buf.append(ch)
                col += max(0, _wcswidth(ch))
            if buf:
                out.append((cls, "".join(buf)))
        return out

    def _scroll_log(self, delta: int) -> None:
        """按 delta 终端行上/下滚动对话区 (正数向下)。

        单位是**终端行** (软换行后的可视行), 所以 PgUp/PgDn 正好一屏、
        Ctrl+↑/↓ 正好一行, 且能一路翻到最早的历史。滚到底自动恢复 follow
        (新内容继续跟随); 滚上去则停止跟随, 新内容不再把视图拽走。
        """
        try:
            lines = self._scrolled_lines(logic_only=True)
        except Exception:
            return
        if not lines:
            return
        _, _, max_top = self._scroll_bounds(lines)
        if self._follow:
            # 首次上翻: 先落到当前底部, 再叠加本次增量
            self._view_top = max_top
            self._follow = False
        self._view_top = max(0, min(self._view_top + delta, max_top))
        if self._view_top >= max_top:
            self._follow = True
            self._view_top = max_top

    def _scroll_to_top(self) -> None:
        """跳到最早的历史 (停止跟随)。"""
        self._view_top = 0
        self._follow = False

    def _scroll_to_bottom(self) -> None:
        """跳回最新内容并恢复跟随。"""
        self._follow = True
        self._view_top = 0   # 具体值在渲染时按 max_top 解析

    def _scroll_state(self) -> Tuple[bool, int, int, int]:
        """(是否已上翻, 视口顶端, 内容总行, 视口高) —— 供底栏显示位置指示。"""
        try:
            lines = self._scrolled_lines(logic_only=True)
        except Exception:
            return (False, 0, 0, self._viewport_rows())
        total, vp, max_top = self._scroll_bounds(lines)
        top = self._resolve_view_top(max_top)
        return (not self._follow, top, total, vp)

    def _current_line_count(self) -> int:
        """当前渲染内容的段落行数 (供滚动钳位)。"""
        try:
            lines = self._scrolled_lines(logic_only=True)
            return len(lines)
        except Exception:
            return 0

    def _render_audit(self):
        """审计面板内容: 顶部标题 + 思考全文 + 审计日志 (kimi 折叠思考)。

        面板是 `wrap_lines=True`, 正文长文本会软换行 (正常)。但标题与
        "Ctrl+O 收起" 提示拼在同一行, i18n 变长 (德/俄语) 或窄终端下会超宽,
        这里按显示宽度裁剪以免首行被折成两行、标题与正文错位。
        """
        width = max(8, self._log_width())
        head = self._clip_dw(t("tui.audit_title"), width)
        if not self._audit_visible:
            return [("class:primary", head)]
        hint = self._clip_dw("Ctrl+O", width - _disp_width(head) - 2)
        line: List[Tuple[str, str]] = [("class:primary", head)]
        if hint:
            line.append(("class:textdim", "  " + hint))
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

    # ============================================================ 鼠标滚轮

    #: 一次滚轮 notch 翻多少终端行。终端无法上报 notch 数量, 统一按 3 行 ——
    #: 与浏览器/Claude Code 的手感接近, 又不至于一格就翻出屏幕。
    _MOUSE_WHEEL_LINES = 3

    def _wheel_owner(self) -> bool:
        """当前是否有交互卡片占用"上下"语义 —— 有则滚轮让位给卡片。

        模型提问 (ask_user)、首次信任确认、"/" 命令面板这三种状态下,
        ↑↓ 是"在选项之间移动", 不是"翻历史"。若滚轮此时也拿去翻页,
        用户会看到选项列表却在滚动一个静止的画面 —— 表现为"能看不能选"。
        """
        return bool(self._ask_pending or self._trust_pending
                    or self._confirm_pending
                    or (self._slash_open and self._slash_items))

    def _mouse_wheel(self, event, up: bool) -> None:
        """滚轮事件入口: 按终端行上下平移对话区视口。

        `up=True` 向历史方向 (内容下移), `up=False` 回到最新。
        """
        if self._wheel_owner():
            # 卡片态: 滚轮与 ↑↓ 键同义 —— 在选项之间移动高亮。
            delta = -1 if up else 1
            if self._ask_pending:
                self._ask_move(delta)
            elif self._trust_pending:
                # 信任卡是两项 radiolist (0=信任 / 1=只读); 与 ↑↓ 键行为一致:
                # up 直接回 0、down 直接到 1 (而不是循环切换)。
                self._trust_index = 0 if up else 1
            elif self._slash_open and self._slash_items:
                self._slash_move(delta)
            try:
                event.app.invalidate()
            except Exception:  # noqa: BLE001 - 无 app 时忽略
                pass
            return
        # 一格滚轮 = _MOUSE_WHEEL_LINES 终端行, 快速滑动才能翻整屏
        self._scroll_log(-self._MOUSE_WHEEL_LINES if up else self._MOUSE_WHEEL_LINES)
        try:
            event.app.invalidate()
        except Exception:  # noqa: BLE001 - 无 app 时忽略
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
        # 有空输入 (仅 "/" 或 "+/") 且配置了层级: 仅展开核心层 (≤ 20 项)
        # 输入具体前缀时保留全量匹配 (专家层命令按首字母可达)
        from ..cli.slash_tier import slash_command_tier as _tier_fn
        if not low:
            items = [c for c in self._commands if _tier_fn(c) == "core"]
        else:
            items = [c for c in self._commands
                     if c[1:].lower().startswith(low) and _tier_fn(c) != "hidden"]
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
            # 该面板 wrap_lines=False, 故**整行**必须 ≤ width: 命令名、分隔空格、
            # 描述三者按顺序瓜分预算。旧实现只裁描述、且分隔符恒为2 列,
            # 在12~16 列的极窄终端下 "  /provider  " 这类行仍会算出 13 列。
            head = self._clip_dw(f"{mark}{cmd}", width)
            gap_room = max(0, width - _disp_width(head))
            gap = " " * min(2, gap_room)
            rest = gap_room - _disp_width(gap)
            desc = self._clip_dw(desc, rest) if rest > 0 else ""
            sel_cls = "class:slashsel" if sel else ""
            rows.append([
                (sel_cls or "class:slashcmd", head),
                (sel_cls, gap),
                (sel_cls or "class:slashdesc", desc),
            ])
        if len(items) > _SLASH_MAX_VISIBLE:
            hidden = len(items) - visible
            hint = t("tui.slash_more", n=hidden, pos=f"{self._slash_index + 1}/{len(items)}")
            rows.append([("class:slashhint", self._clip_dw(hint, width))])
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
        # 模型提问态优先级最高: 模型在等用户拍板, 输入框此刻就是选项答复通道
        # (↑↓ 已由键位路由到 _ask_move; Enter 取高亮项 / 编号 / 自由文本)。
        # 必须排在 slash 面板与 trust 之前, 否则提问会被当成普通输入吞掉。
        if self._ask_pending:
            self._resolve_ask(self._input.text)
            self._input.buffer.reset()
            event.app.invalidate()
            return
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
        self._view_top = 0

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

        **两次调用都必须显式传 `leave_alternate_screen=False`** (修"输入框失去渲染"):
        `Renderer.reset()` 的默认值是 `leave_alternate_screen=True` —— 一旦漏传,
        它会执行 `output.quit_alternate_screen()` 把这个**全屏 TUI 踢出备用屏缓冲**,
        终端随即回退到进入 TUI 之前的主屏内容, 而 TUI 仍以为自己全屏绘制,
        于是输入框 (以及整幅界面) "失去渲染" —— 在 Windows conpty / Windows
        Terminal 上尤其明显。`erase()` 内部虽已用 `leave_alternate_screen=False`
        调过一次 `reset()`, 但紧跟着的裸 `reset()` 会用默认值再退出一次备用屏,
        这正是此前"输入框渲染丢失"的真凶。

        **线程安全** (同源问题): `set_ready`/`boot_error` 由 `_boot` **后台线程**
        调用 (见 cmd_chat), 而渲染循环跑在主线程。直接在后台线程操作 renderer
        会与主线程渲染竞争光标位置 / 输出写入, 造成同样的画面错乱。故把重置
        **投递到主事件循环** (`call_soon_threadsafe`) 执行; 应用尚未进入运行态
        (无 loop) 时退化为同步调用。
        """
        app = self._app
        if app is None:
            return

        def _do_reset() -> None:
            try:
                r = getattr(app, "renderer", None)
                if r is None:
                    return
                try:
                    r.erase(leave_alternate_screen=False)
                except Exception:
                    pass
                if hasattr(r, "reset"):
                    try:
                        # 关键: 显式留在备用屏内, 避免 quit_alternate_screen()
                        r.reset(leave_alternate_screen=False)
                    except TypeError:  # 老版 pt 无该关键字
                        r.reset()
            except Exception:
                pass

        try:
            loop = getattr(app, "loop", None)
            if loop is not None and getattr(app, "is_running", False):
                loop.call_soon_threadsafe(_do_reset)
                return
        except Exception:
            pass
        _do_reset()

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
        width, inner = self._box_budget()    # 真实 App 列宽, 全宽
        pad = "  "
        pad_w = _disp_width(pad)
        logo_w = max(_disp_width(r) for r in KIMI_LOGO)
        gap_w = 2
        # 窄屏 (放不下 logo + 至少 4 列文字) 时把文字挪到 logo 下方另起 ——
        # 旧实现用 max(4, ...) 强行保底 4 列文字, 在 16 列终端下整行算成
        # 2+logo+2+4+2 远大于 inner, 右边框被顶到下一行 (观感即"文字溢出")。
        stacked = (inner - pad_w - gap_w) < (logo_w + 4)
        info_w = max(1, inner - pad_w)
        if stacked:
            head_text_w = info_w
        else:
            head_text_w = max(4, inner - pad_w - logo_w - gap_w)

        def clip_dw(s: str, n: int) -> str:
            if _disp_width(s) > n:
                res = ""
                for ch in s:
                    if _disp_width(res) + _disp_width(ch) > n:
                        break
                    res += ch
                return res
            return s + " " * (n - _disp_width(s))

        # 头部两行: 吉祥物 + 右侧文字并排 (row0 蓝标题 / row1 蓝次级);
        # 窄屏则 logo 独占两行, 文字在其后另起, 保证每行 ≤ inner。
        head: List[List[Tuple[str, str]]] = []
        rights = [clip_dw(title, head_text_w), clip_dw(subtitle, head_text_w)]
        for i, lg in enumerate(KIMI_LOGO):
            seg: List[Tuple[str, str]] = []
            seg.append(("class:primary", "│"))
            seg.append(("", pad))
            if stacked:
                seg.append(("class:title", lg.ljust(max(1, logo_w))))
                seg.append(("", " " * max(0, inner - pad_w - logo_w)))
            else:
                seg.append(("class:title", lg.ljust(max(1, logo_w))))
                seg.append(("", "  "))
                r = rights[i]
                seg.append(("class:title" if i == 0 else "class:boxsub", r))
                rp = max(0, (inner - pad_w - logo_w - gap_w) - _disp_width(r))
                seg.append(("", " " * rp))
            seg.append(("class:primary", "│"))
            head.append(seg)
        if stacked:
            for i, r in enumerate(rights):
                if not r.strip():
                    continue
                seg = [("class:primary", "│"), ("", pad),
                       ("class:title" if i == 0 else "class:boxsub", r),
                       ("", " " * max(0, info_w - _disp_width(r))),
                       ("class:primary", "│")]
                head.append(seg)

        # 信息行: 标签(蓝次级) + 值(浅色)
        info_rows: List[List[Tuple[str, str]]] = []
        for label, value in info_pairs:
            # 极窄终端下标签本身就放不下 (如"Directory: " 12 列而可用仅 8 列),
            # 旧实现只裁 value、label 全宽输出 → 整行超宽, 右边框被顶飞。
            # 这里把标签和值放进同一个预算里按顺序分配。
            label = self._clip_dw(str(label), info_w)
            value = str(value)
            v_room = max(0, info_w - _disp_width(label))
            value = clip_dw(value, v_room) if v_room > 0 else ""
            seg: List[Tuple[str, str]] = [("class:primary", "│")]
            seg.append(("", pad))
            seg.append(("class:boxsub", label))
            seg.append(("class:text", value))
            seg.append(("", " " * max(0, info_w - _disp_width(label) - _disp_width(value))))
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
        # 启动态的几行文本也按宽度裁剪: 状态串 (含 i18n 与错误详情) 与提示行
        # 在窄终端下会超宽 → 软换行把加载屏顶乱。
        budget = max(4, self._box_width() - 2)

        def emit(cls: str, text: str) -> None:
            out.append((cls, self._clip_dw(text, budget) + "\n"))

        if self._boot_error:
            emit("class:error", f"  ✗ {self._boot_error}")
            emit("class:textdim", f"  {t('tui.exit_ctrl_c')}")
        elif self._boot_progress >= 100:
            emit("class:success", f"  {SUCCESS_MARK} {t('fs.ready')}")
        else:
            emit("class:text", f"  {frame} {self._boot_status}")
        # 进度条按终端宽度自适应: 固定 30 格 = 37 列, 窄终端 (<40 列) 下
        # 整行超宽 → 软换行把加载屏顶成两行, 观感即"溢出/错位"。
        # 这里把可用宽度扣掉缩进、方括号、百分比和空格后作为条长。
        bar_len = max(3, min(30, budget - 6))
        filled = int(self._boot_progress / 100 * bar_len)
        filled = max(0, min(bar_len, filled))
        bar = "█" * filled + "░" * (bar_len - filled)
        emit("class:dim", f"  [{bar}] {self._boot_progress}%")
        out.append(("", "\n"))
        emit("class:dim", f"  {t('tui.exit_ctrl_c')}")
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

    # ============================================================ 模型提问 (ask_user)

    def ask_user(self, question: str, options: Optional[List[str]] = None) -> str:
        """模型提问 (ask_user 工具入口): 渲染可选择卡片, 阻塞到用户作答。

        供 `TuiUI.ask_user` 调用。取代工具里的 `print()+input()` —— 在全屏 TUI
        下那会把文本直接写进 prompt_toolkit 掌管的屏幕, 布局被冲垮 (用户报告的
        "溢出"), 且 `input()` 在备用屏/ raw 模式下拿不到按键 ("选不了")。

        交互: ↑↓ 移动高亮, Enter 确认; 也可直接敲编号 (1..N) 或任意文字
        (自由作答)。options 为空时退化为纯自由作答。
        """
        q = str(question or "").strip()
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]

        app = self._app
        running = app is not None and getattr(app, "is_running", False)
        if not running:
            # headless / 应用未启动: 没有界面可挂卡片, 退回纯文本询问
            return _ask_user_plain(q, opts)

        done = threading.Event()
        pending: Dict[str, Any] = {
            "question": q,
            "options": opts,
            "event": done,
            "result": None,     # None = 未作答 (被取消)
        }
        self._ask_pending = pending
        self._ask_index = 0
        self._ask_free = False
        self._follow = True      # 提问卡片必须可见: 强制回到底部
        try:
            app.invalidate()
        except Exception:  # noqa: BLE001
            pass

        # 阻塞等待。0.5s 心跳轮询防死锁: 卡片被取消或应用退出时不能永远挂着。
        while not done.wait(timeout=0.5):
            if self._ask_pending is not pending:
                break
            if not getattr(app, "is_running", True):
                pending["result"] = None
                break
        return str(pending.get("result") or "")

    def _ask_move(self, delta: int) -> None:
        """↑↓ 移动选项高亮 (无选项时忽略)。"""
        pending = self._ask_pending
        if not pending:
            return
        opts = pending.get("options") or []
        if not opts:
            return
        n = len(opts)
        self._ask_free = False
        self._ask_index = max(0, min(n - 1, self._ask_index + delta))

    def _resolve_ask(self, text: str) -> None:
        """提交提问答案并唤醒等待中的工具线程。

        - 纯 ↑↓+Enter (输入框为空) → 取当前高亮项;
        - 敲了编号 (1..N) → 取对应项;
        - 其它任意文本 → 自由作答。
        """
        pending = self._ask_pending
        if not pending:
            return
        opts: List[str] = pending.get("options") or []
        raw = (text or "").strip()
        if not raw:
            # 空回车 = 确认当前高亮项 (无选项则视为跳过)
            ans = opts[self._ask_index] if opts else ""
        elif raw.isdigit() and opts and 1 <= int(raw) <= len(opts):
            ans = opts[int(raw) - 1]
        else:
            ans = raw
        pending["result"] = ans
        self._ask_pending = None
        self._ask_free = False
        try:
            self.append_log(f"{SUCCESS_MARK} {t('tui.ask_answer', answer=ans or t('tui.ask_skipped'))}",
                            cls="class:success")
        except Exception:  # noqa: BLE001
            pass
        ev = pending.get("event")
        if ev is not None:
            ev.set()

    def cancel_ask(self) -> None:
        """取消挂起中的提问 (退出/Ctrl-C 兜底), 按"未作答"解冻工具线程。"""
        pending = self._ask_pending
        if not pending:
            return
        self._ask_pending = None
        pending["result"] = None
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
                        # 内联模式是崩溃兜底路径, 鼠标上报在这里最可能加剧
                        # 不稳定 —— 保守关掉, 滚轮不可用但键盘 PgUp/PgDn 照常。
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
            elif indent and segs[0][1]:
                # 空行不加缩进: 否则每行空行都带两个尾随空格, 既在终端里看不见,
                # 又会被选中复制出去, 还让 diff 里凭空多出空白字符。
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
                # 代码块后补一行空行做视觉分隔; 但若后面没有内容 (收尾的代码块),
                # 或已经是空行, 就别再补 —— 否则空行会与块分隔叠加成两行。
                if i < n and not (i < n and not lines[i].strip()):
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
        """构建对话区**完整**内容 (段落行列表) —— 不做视口裁剪。

        裁剪由 `_viewport_slice` 负责 (本方法始终返回全量历史, 滚动位置
        `_view_top` 单独记录)。`logic_only` 参数为兼容旧调用保留, 已无差别。

        - 工具完成记录默认折叠为一行 "see N tool calls", Ctrl+O 展开逐条;
        - 返回的 list 每项是一行 (list[ (cls,text) ])。
        """
        # 信任确认态优先: 未知目录首次访问时整屏显示确认卡片 (不显示对话区)
        if self._trust_pending:
            return _split_flat_lines(self._render_trust_confirm())

        if self._booting or self._boot_error:
            return _split_flat_lines(self._render_boot())

        screen: List[List[Tuple[str, str]]] = []
        prev_role = ""
        for ev in self._events:
            if isinstance(ev, tuple):
                screen.extend(self._colored_lines(ev[0], ev[1]))
            elif isinstance(ev, list):
                screen.append(ev)
            else:
                role = "user" if ev.startswith(USER_MESSAGE_BULLET) else "log"
                # 块间空行分隔, 但**对标 Claude Code 的紧凑排版**做两处收敛:
                # 1. 提问与其回答之间不空行 —— 一次问答是一个整体, 空行会把它拆成
                #    两个视觉区块, 是"行距偏松"的最大来源;
                # 2. 连续空行去重 —— 代码块尾部已补过空行, 块分隔再补一次就变成
                #    两行空白, 累积起来把对话撑得又长又散。
                if screen and screen[-1] and not (prev_role == "user" and role == "log"):
                    screen.append([])
                screen.extend(self._msg_to_lines(role, ev))
                prev_role = role

        # 本轮工具调用: 折叠成一行摘要 (see N), 展开时逐条; 始终镜像进审计面板
        if self._turn_tool_lines:
            if self._tool_detail:
                for ln in self._turn_tool_lines:
                    screen.append([("class:textdim", self._fit(ln))])
            else:
                n = len(self._turn_tool_lines)
                screen.append([("class:primary", self._fit(
                    f"▸ see {n} tool calls (Ctrl+O)"))])

        # 流式
        if self._streaming and self._stream_buf:
            screen.append([("class:text", self._fit(
                STATUS_BULLET + self._stream_buf.lstrip(chr(10))))])
        elif self._busy and not self._running and not self._streaming and not self._moon_suppressed:
            moon = _MOON_FRAMES[self._moon_frame % len(_MOON_FRAMES)]
            screen.append([("class:primary", f"{moon} {t('tui.thinking')}")])
        # 在途工具
        for name in self._running:
            elapsed = self._tool_start_times.get(name)
            elapsed_str = f" ({time.monotonic() - elapsed:.1f}s)" if elapsed else ""
            screen.append([("class:textdim", self._fit(
                t("tui.tool_run", name=name, time=elapsed_str)))])

        if not screen:
            screen.append([("class:textdim", t("tui.ready_empty"))])

        # 命令确认卡片: 追加在对话区底部 (输入框上方)。放在这里而不是输入框里,
        # 是修复"确认框撑破输入框边框"的关键 —— 它现在是内容, 不是输入提示。
        if self._confirm_pending:
            screen.extend(_split_flat_lines(self._render_confirm_card()))
        # 模型提问卡片: 同样追加在对话区底部 (输入框上方), 跟随虚拟视口切片。
        # 优先级高于确认卡 —— 提问是模型在等用户拍板, 必须先于一切被看见。
        if self._ask_pending:
            screen.extend(_split_flat_lines(self._render_ask_card()))

        return screen

    def _viewport_slice(self, screen: List[List[Tuple[str, str]]]) -> List[List[Tuple[str, str]]]:
        """把整段对话按当前视口切成**正好一屏**的行 (Claude Code 式虚拟滚动)。

        只返回终端行区间 [view_top, view_top+vp) 覆盖到的逻辑行; 首/尾逻辑行
        被切到半行时按显示行裁剪 (`_clip_line_rows`), 因此返回内容的实际高度
        恒等于视口高度 —— Window 无需再自行滚动, 上翻/下翻都是精确整屏位移。
        """
        if not screen:
            return screen
        total, vp, max_top = self._scroll_bounds(screen)
        top = self._resolve_view_top(max_top)
        if total <= vp:
            return screen                      # 内容不足一屏: 全部显示 (顶部对齐)
        width = self._log_width()
        heights = self._line_heights(screen)
        starts = self._line_starts(heights)
        bottom = top + vp
        out: List[List[Tuple[str, str]]] = []
        used = 0
        for i, line in enumerate(screen):
            s = starts[i]
            e = s + heights[i]
            if e <= top or s >= bottom:
                continue
            r0 = max(0, top - s)
            r1 = min(heights[i], bottom - s)
            # 防御: 估算高度与真实折行略有出入时, 宁可少给一行也不要超出视口
            if used + (r1 - r0) > vp:
                break
            out.append(line if (r0 == 0 and r1 >= heights[i])
                       else self._clip_line_rows(line, r0, r1, width))
            used += r1 - r0
        return out or screen[-1:]

    def _render_conversation(self):
        """扁平化**当前视口**的对话内容供 FormattedTextControl 渲染 (行间加 \\n)。

        这里返回的不是整段历史, 而是按 `_view_top` 切好的一屏 —— 这正是"能真正
        回看上面记录"的关键: 内容再长也只渲染可见的那几行, 翻页即改切片起点。
        """
        screen = self._viewport_slice(self._scrolled_lines())
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
            return self._clip_parts(parts)
        if self._ask_pending:
            parts.append(("class:warning", f"? {t('tui.ask_title')}"))
            return self._clip_parts(parts)
        if self._confirm_pending:
            parts.append(("class:warning", f"? {t('tui.confirm_title')}"))
            return self._clip_parts(parts)
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
        # header 也是 height=1 的单行控件: 长模型名 (provider/model 很长) 会顶破
        # 顶部一行, 必须按显示宽度硬裁。
        return self._clip_parts(parts)

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
        # 模型提问期: 底栏让位给选项提示 (↑↓ 选择 · Enter 确认)
        if self._ask_pending:
            opts = (self._ask_pending or {}).get("options") or []
            hint = t("tui.ask_opt_hint") if opts else t("tui.ask_free_hint")
            return self._clip_parts([("class:warning", " " + hint)])
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

        # 回卷位置指示: 一旦用户上翻离开底部就高亮提示 (Claude Code 同款),
        # 否则"看不到最新回复"会让人误以为界面卡住。回到底部自动消失。
        parts.extend(self._scroll_indicator())

        # 注: 此处曾显示 "context: X% (est/budget)" 上下文占用条, 已移除 ——
        # 预算靠模型名猜 (所有模型都退化成 131.1k), 用量是字符数估算而非真实 token,
        # 数字既不准确又占版面。需要真实用量请用 /context 或 Web 工作台的上下文面板。
        # 收尾: 单行控件 (Window height=1 无软换行) 必须按显示宽度裁剪,
        # 否则 no_key 长提示/长模型名/长目录名会把底栏顶出屏幕 (文字溢出)。
        return self._clip_parts(parts)

    def _scroll_indicator(self) -> List[Tuple[str, str]]:
        """底栏回卷指示片段 (未上翻时返回空)。

        上翻后显示 `↑ 已上翻 42/411 行 · End 回底` —— 让用户明确知道自己不在
        底部, 以及怎么回去 (否则"看不到最新回复"很像界面卡死)。
        """
        try:
            scrolled, top, total, vp = self._scroll_state()
        except Exception:  # noqa: BLE001 - 指示器绝不阻断底栏渲染
            return []
        if not scrolled or total <= vp:
            return []
        return [("class:warning", f"  ↑ {top + 1}/{total}"),
                ("class:textdim", f" {t('tui.scroll_back_hint')}")]

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

    def _fit(self, s: str) -> str:
        """把一行文本裁到对话区可视宽度 (供流式/工具行等超长单行使用)。

        对话区是 `wrap_lines=True`, 长文本软换行本身没问题; 但流式缓冲、
        工具耗时行这类"本应是一行"的元素被折成多行会让人误以为内容重复或
        界面卡住, 故在构造时就裁到一屏宽。
        """
        return self._clip_dw(s, max(8, self._log_width()))

    def _clip_dw(self, s: str, n: int) -> str:
        if n <= 0:
            return ""
        if _disp_width(s) <= n:
            return s
        if n == 1:
            return "…"
        res = ""
        for ch in s:
            if _disp_width(res) + _disp_width(ch) > n - 1:  # 留 1 列给 "…"
                break
            res += ch
        return res + "…"

    def _box_row(self, segs: List[Tuple[str, str]], inner: int,
                 pad: str = "  ") -> List[Tuple[str, str]]:
        """把一段 (cls, text) 拼成带左右边框的一行, 右侧对齐竖线。

        内容总宽超过可用宽度时从第一段起按显示宽度截断 (补省略号),
        防止窄屏下长标题/说明/选项行撑破右边框。供信任确认卡片、命令
        确认卡片与模型提问卡片共用, 保证几类卡片排版完全一致。

        可用宽度按 `pad` 的**实际**显示宽度推导 (旧实现硬编码 `-2`, 一旦
        调用方传不同 pad 就会算错; 且 `inner` 很小时结果为负, 补空格数
        变正数后整行仍超宽)。
        """
        pad_w = _disp_width(pad)
        avail = max(0, inner - pad_w)      # 左右边框各占 1 列, 已由 inner 排除
        body_w = sum(_disp_width(s) for _, s in segs)
        if body_w > avail:
            clipped: List[Tuple[str, str]] = []
            rest = avail
            for cls, s in segs:
                w = _disp_width(s)
                if w <= rest:
                    clipped.append((cls, s))
                    rest -= w
                    continue
                if rest > 0:
                    clipped.append((cls, self._clip_dw(s, rest)))
                rest = 0
                break
            segs = clipped
            body_w = sum(_disp_width(s) for _, s in segs)
        line: List[Tuple[str, str]] = [("class:primary", "│")]
        line.append(("", pad))
        line.extend(segs)
        line.append(("", " " * max(0, avail - body_w)))
        line.append(("class:primary", "│"))
        return line

    def _box_budget(self) -> Tuple[int, int]:
        """卡片盒子宽度预算 = (总宽, 边框内侧宽度)。

        终端窄到连 3 列都不到时 (Windows conpty 窗口被拖到极窄会出现),
        直接返回 (4, 2) 之类的安全下限: 边框算式 `width-2` 为负会让
        `"─" * (width-2)` 变成空串、上下边框退化成 `╭╮`, 排版整体垮掉。
        """
        width = max(4, self._box_width())
        return width, max(2, width - 2)

    def _render_trust_confirm(self) -> List[Tuple[str, str]]:
        """Kimi/Claude Code 风格信任确认卡片 (全宽盒子, 复用欢迎盒排版)。"""
        pending = self._trust_pending or {}
        ws = str(pending.get("workspace", ""))
        width, inner = self._box_budget()   # 边框内侧显示列数
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
        width, inner = self._box_budget()
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

    def _render_ask_card(self) -> List[Tuple[str, str]]:
        """模型提问卡片 (Claude Code 同款): 问题 + 可选列表 + 高亮项。

        渲染在对话区底部 (与确认卡片同位), 因此天然进入虚拟视口切片 —— 长问题
        自动折行、超长选项按显示宽度裁剪, 不会再把输入框/边框顶破。
        """
        pending = self._ask_pending or {}
        width, inner = self._box_budget()
        pad = "  "
        clip_dw = self._clip_dw
        opts: List[str] = list(pending.get("options") or [])
        sel = max(0, min(len(opts) - 1, self._ask_index)) if opts else -1

        def row(segs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            return self._box_row(segs, inner, pad)

        out: List[Tuple[str, str]] = [("class:primary", "╭" + "─" * (width - 2) + "╮\n")]
        out += row([("class:warning", "? " + clip_dw(t("tui.ask_title"), max(1, inner - 2)))])
        out.append(("", "\n"))
        # 问题正文: 逐行折行铺开, 保证长问题不溢出卡片
        for ln in str(pending.get("question", "")).split("\n"):
            for seg in self._wrap_dw(ln, max(1, inner - 4)):
                out += row([("class:text", seg)])
                out.append(("", "\n"))
        # 选项: 高亮项加 ▸ 前缀 + 反显, 未选项缩进对齐
        if opts:
            out.append(("", "\n"))
            for i, o in enumerate(opts):
                marker = "▸ " if i == sel else "  "
                cls = "class:success" if i == sel else "class:text"
                out += row([(cls, marker + clip_dw(f"{i + 1}. {o}", max(1, inner - 4)))])
                out.append(("", "\n"))
            out += row([("class:textdim",
                         clip_dw(t("tui.ask_opt_hint"), max(1, inner - 2)))])
            out.append(("", "\n"))
        else:
            out += row([("class:textdim",
                         clip_dw(t("tui.ask_free_hint"), max(1, inner - 2)))])
            out.append(("", "\n"))
        out.append(("class:primary", "╰" + "─" * (width - 2) + "╯\n"))
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
