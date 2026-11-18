"""青小团 TUI —— 单一 Application (启动加载屏 + 对话界面)。

以 Codex CLI 风格加载屏为基底, 扩展出对话模块:
  - 启动期: 内嵌加载屏 (粒子风格 TUAN 徽记 + braille 转圈 + 进度条 + Ctrl-C 退出)
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
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..ui.slogans import mapping
from ..ui.theme import BRAND_PRIMARY
from .runtime_slogans import RuntimeSloganEngine
from .state import StateMixin
from .render import RenderMixin
from .layout import LayoutMixin
from .interact import InteractMixin
from .slashmenu import SlashMenuMixin
from .panels import PanelsMixin
from .slogan import SloganMixin
from .lifecycle import LifecycleMixin

from .common import _wcswidth, _display_width  # 宽度真值单一来源 (4096 有界缓存)

from ..i18n import t
from ..core.prompt_tier import PROVIDER_CONTEXT_WINDOWS

import logging
log = logging.getLogger(__name__)

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
    from prompt_toolkit.layout.processors import (Processor,
                                                   Transformation,
                                                   TransformationInput)
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
    Keys = _MissingKeys()      # type: ignore[misc, assignment]

    class Completer:  # type: ignore[no-redef]
        """占位基类: prompt_toolkit 缺失时仅为让下面的类定义通过。"""

    class Window:  # type: ignore[no-redef]
        """占位基类: prompt_toolkit 缺失时仅为让 `class _MeasuredWindow(Window)` 通过。

        只保证**导入**成功 (模块级基类解析); 真正实例化 _MeasuredWindow 仍需
        prompt_toolkit, 此时会在 TUI 启动处给出清晰错误, 而不是在 import 时 NameError。
        """

    def Completion(*args: Any, **kwargs: Any) -> None:  # type: ignore[no-redef]
        """占位构造器: prompt_toolkit 缺失时给出可读错误, 而不是 NameError。"""
        raise RuntimeError(
            "prompt_toolkit 未安装, 无法使用 TUI 输入补全; 安装 prompt_toolkit 或改用 CLI 模式"
        )


class _PlaceholderProcessor:
    """占位处理器: prompt_toolkit 缺失时仅让模块级 `input_processors` 构造可通过。

    真正实例化时 (TUI 启动) 会因缺少 pt 而在别处报清晰错误, 这里只是占位基类。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "prompt_toolkit 未安装, 无法渲染输入框 placeholder; 安装 prompt_toolkit"
        )


if _HAS_PT:

    class _PlaceholderProcessor(Processor):  # type: ignore[no-redef]
        """Codex 同款输入框 placeholder (空输入时显示 dim 灰提示文本)。

        prompt_toolkit 3.0.53 的 ``TextArea`` 尚无 ``placeholder`` 参数 (那是
        更新版才加的), 因此用自定义 ``Processor`` 在**空文档**时把提示文本注入
        fragments 末尾 (``BeforeInput`` 已把 "› " 前缀注入 fragments 头部)。

        空文档时 document.text 为空、光标恒在 0, 恒等映射 source_to_display /
        display_to_source 即可 (0→0), placeholder 仅是视觉提示层, 不参与光标
        定位; 一旦用户键入任意字符, document.text 非空, 本处理器立即透传原
        fragments, placeholder 消失。对齐 codex-rs/tui 输入框 placeholder 行为。
        """

        def __init__(self, text: str = "Ask Codex to do anything",
                     style: str = "class:textdim") -> None:
            self._text = text
            self._style = style

        def apply_transformation(
            self, ti: TransformationInput,
        ) -> Transformation:
            doc = ti.document
            # 仅在空文档 (无输入) 且无选区时显示 placeholder; 否则透传。
            if doc.text == "" and not doc.selection:
                fragments = ti.fragments + [(self._style, self._text)]
                # 文本长度与 document.text 不一致 (placeholder 是视觉提示),
                # 但空文档下光标恒在 0, 恒等映射是精确的。
                return Transformation(fragments, (lambda i: i), (lambda i: i))
            return Transformation(ti.fragments)


# ---- 配色: Codex CLI 深色视觉语言 (chatgpt-blue 200 #63A8F8 主强调) ----
# TUI 整体观感对齐开源 Codex CLI (openai/codex, codex-rs/tui/src/style.rs):
#   UI_ACCENT = CHATGPT_BLUE_200 (99,168,248) 为选中/强调主色,
#   语义色 status_style: success→green / failure→red / attention→yellow,
#   secondary_text_style: 前景与背景 0.6 blend 的弱化文字。
# 法定署名见仓库根 NOTICE。
_PRIMARY = BRAND_PRIMARY      # Codex 主强调蓝 (CHATGPT_BLUE_200): 选中/强调/输入提示符
_BLUE_DIM = BRAND_PRIMARY     # 次级蓝: 与主强调同源 (Codex accent 不加粗时弱化)

# 通用界面 (对话 / 输入 / 底栏) 的深色字号层次
_TEXT = "#E0E0E0"
_TEXT_STRONG = "#F5F5F5"
_DIM = "#888888"
_MUTED = "#6B6B6B"
_BORDER = "#4A4A4A"       # 弱化边框: 暗灰, 与面板背景区分但不抢眼 (OpenCode 克制边框)
_ACCENT = BRAND_PRIMARY   # 辅助强调统一为 Codex 蓝
_BG_PANEL = "#1E2836"     # 面板背景色 (补全菜单用，与 _BORDER 同色系)
_SUCCESS = "#4EC87E"
_WARNING = "#E8A838"
_ERROR = "#E85454"
_ROLEUSER = BRAND_PRIMARY  # 用户消息前缀强调改为 Codex accent (原暖金 #FFCB6B 移除)
_SHELL = "#BD93F9"

try:
    from .. import __version__  # pyproject.toml 的真实版本
    VERSION = f"v{__version__}"
except Exception:  # noqa: BLE001
    VERSION = "v?.?.?"  # import 失败兜底, 避免硬编码版本漂移

#: TUI 启动时写入的终端窗口/标签标题 (Windows Terminal 标签页 / ConHost 标题栏)。
#: 环境变量 TUAN_TERMINAL_TITLE 可覆盖 (留空则不修改标题)。
TERMINAL_TITLE = os.environ.get("TUAN_TERMINAL_TITLE", "").strip() or "Tuan-CLI"

# 加载屏转圈帧
_SPLASH_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# 思考态粒子转圈帧 (每帧 90ms, 8 相走完一圈约 0.72s, 观感更流畅稳定)
# 用粒子点簇代替具象月亮, 与粒子 Logo 同语言。
_MOON_FRAMES = ["◐", "◓", "◑", "◒", "●", "◒", "◑", "◓"]
_MOON_INTERVAL = 0.09

# ---- 输出溢出防护 (规范化: 单条/流式缓冲/思考全文都有界, 防止巨文本拖垮渲染) ----
_MAX_LOG_LEN = 2000      # 单条日志/审计行最大字符, 超出截断并标注
_MAX_STREAM_BUF = 20000  # 流式缓冲上限, 超出将前段固化为日志
_MAX_REASON_LEN = 30000  # 思考全文上限, 超出截断并标注

# ---- "/" 命令面板 (Claude Code 同款 slash menu) ----
_SLASH_MAX_VISIBLE = 9   # 面板最大可见行数 (超出滚动, 与 Claude Code 观感一致)


# ---- C-3 补全元数据: 命令 -> 子命令 -> 标志 (多级补全数据源) ----
# 来源: 只读审计 tuan_cli/cli/ 注册处 —— cmd_slash.py 的 _handle_slash 各分支
# 与 _HELP 文案、cmd_safe.py 用法 (status/list/allow/deny/.../bench/report)、
# modes/registry.py 的模式注册表。仅做补全提示, 不改动 cli/ 执行逻辑;
# 模式名只用 感通/灵码/闲聊/无界/协同。
_SLASH_SUBCMDS: Dict[str, List[Tuple[str, str]]] = {
    "/safe": [
        ("bench", "安全基准测试 (可追加 --quick 快速模式)"),
        ("allow", "把命令加入本地白名单 (tuan safe allow <命令>)"),
        ("report", "导出安全审计报告"),
    ],
    "/mcp": [
        ("list", "列出已接入的 MCP 服务器"),
        ("tools", "查看 MCP 工具清单"),
        ("audit", "审计 MCP 配置"),
        ("security", "MCP 安全检查"),
    ],
    "/checkpoint": [
        ("save", "保存当前会话检查点"),
        ("restore", "回滚到指定快照"),
        ("list", "列出全部检查点"),
    ],
    "/rewind": [
        ("list", "列出时间线快照"),
        ("to <N>", "回退到第 N 步"),
    ],
    "/personality": [
        ("list", "列出可用人设"),
        ("show", "查看当前人设"),
        ("set <人设名>", "切换人设"),
        ("auto", "按上下文自动匹配人设"),
    ],
    "/effort": [
        ("low", "低推理投入 (快, 省 token)"),
        ("medium", "中推理投入"),
        ("high", "高推理投入 (深思)"),
    ],
    "/plan": [
        ("on", "开启只读规划模式"),
        ("off", "关闭规划模式"),
    ],
    "/mode": [
        ("list", "列出全部运行模式"),
        ("show", "查看当前模式详情"),
        ("gantong", "感通: L3 高成本/不可逆操作二次确认"),
        ("lingma", "灵码: L3 代码开发, Shell + 审计 + 沙箱"),
        ("chat", "闲聊: L0 受限陪伴, 仅对话与记忆"),
        ("boundless", "无界: L4 全能力, 桌面白名单"),
        ("collaboration", "协同: L2 工作区读写 + 审计, Shell 禁用"),
    ],
    "/provider": [
        ("set <ENV>", "设置供应商 API Key (provider set <ENV> <KEY>)"),
        ("clear [ENV]", "清除已保存的供应商 Key"),
    ],
    "/commands": [
        ("list", "列出热插拔命令"),
        ("reload", "热重载命令表"),
        ("enable <名>", "启用指定命令"),
        ("disable <名>", "停用指定命令"),
    ],
    "/worktree": [
        ("create", "新建 git worktree"),
        ("list", "列出 worktree"),
        ("remove", "删除 worktree"),
        ("switch", "切换到指定 worktree"),
    ],
    "/image": [
        ("generate <描述>", "按描述 AI 生成图片"),
        ("list", "列出当前待发送图片"),
    ],
    "/web": [
        ("search <关键词>", "快捷联网搜索"),
    ],
    "/language": [
        ("list", "列出可用界面语言"),
        ("en", "切换为英语"),
        ("zh-CN", "切换为简体中文"),
        ("zh-TW", "切换为繁体中文"),
    ],
    "/superagent": [
        ("start", "启动 Super-Agent 引擎 (Watchdog + 恢复)"),
        ("stop", "停止 Super-Agent 引擎"),
        ("status", "状态摘要 (Router/Worker/Watchdog/面板)"),
        ("panel", "渲染「现在有什么需要我」面板"),
        ("mode <off|observe|auto>", "切换接单模式"),
        ("ingest <来源> <内容>", "注入一条外部事件 (自动启动引擎)"),
        ("speculate <提示> [标题]", "投机执行 (后台提前尝试)"),
        ("source [name]", "注册外部事件源"),
        ("rule <匹配> [allow|drop]", "添加程序层过滤规则"),
        ("recover", "手动恢复未完成工单"),
        ("accept <ticket_id>", "验收工单 (待审阅 → 完成)"),
        ("retry <ticket_id>", "重试工单 (失败/受阻 → 重新分派)"),
        ("reply <ticket_id> <内容>", "回答待回答工单"),
        ("list", "列出面板条目"),
        ("summary", "一行摘要 (状态栏用)"),
    ],
}

# 第三级: 子命令后的标志补全 (键 = "/命令 子命令", 值 = [(标志, 帮助)])
_SLASH_FLAGS: Dict[str, List[Tuple[str, str]]] = {
    "/safe bench": [
        ("--quick", "快速基准: 跳过 10k 全量用例, 只跑快速集"),
    ],
}


def _fuzzy_rank(name: str, query: str) -> int:
    """命令补全匹配等级 (C-3.1 模糊匹配)。

    返回: 0=前缀命中 (如 /mo→/model, /mode); 1=子串命中 (如 /od→/mode);
    2=子序列命中 (可跳字符, 如 /md→/mode); -1=不命中。空 query 视为命中。
    """
    if not query:
        return 0
    if name.startswith(query):
        return 0
    if query in name:
        return 1
    # 子序列: query 的字符按顺序在 name 中出现 (允许中间跳字符)
    it = iter(name)
    if all(ch in it for ch in query):
        return 2
    return -1

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
    "roleuser": _ROLEUSER,    # 用户消息前缀: Codex accent 蓝 (原暖金 #FFCB6B 已移除)
    # OpenCode 风格角色徽章: 后台自主任务 (@agent) 用青绿, 与用户蓝/助手灰区分。
    # OpenCode 的 agent 角色徽章常用绿色系; 在 Codex 深蓝主体上取柔和青绿,
    # 让「后台任务」这一类别在对话区一眼可辨。
    "roleagent": "#5FD3B3",
    "border": _BORDER,        # 输入框边框: 灰
    "shellmode": _SHELL,
    # Codex CollaborationModeIndicator::Plan 用 magenta (footer.rs:164)。
    # 深底上取亮洋红, 与蓝 accent 区分。
    "plan": "#E879F9",
    # ---- "/" 命令面板 (Claude Code 同款: 高亮选择 + 描述) ----
    "slashbg": "bg:#16202C",          # 面板背景 (深色终端下与对话区区分)
    "slashsel": "bg:#234163 #E0E0E0",      # 选中行: 柔和强调蓝底 (去纯白粗体反显, OpenCode 克制高亮)
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

# 对话区符号约定 (Codex CLI 风格)
# Codex 用户消息无 emoji 前缀, 采用左对齐浅灰半透明底 (history_prompt_style);
# 这里保留一个前缀标记用于区分用户行, 但用 Codex 同款 "›" 而非 emoji。
USER_MESSAGE_BULLET = "› "      # Codex 输入区同款前缀符号
USER_MESSAGE_BG = "#333B47"     # history_prompt_style 深底 (255,255,255)@0.16 近似
STATUS_BULLET = "• "             # Codex 助手消息前缀 (U+2022, dim) —— 非 ● (U+25CF)

SUCCESS_MARK = "✓"
FAILURE_MARK = "✗"


_disp_width = _display_width  # 同一宽度真值 (B3 回归: 视口行高与单行裁剪不得再用两套算法)


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
        except Exception as exc:  # noqa: BLE001 - 测量失败不影响渲染
            log.warning("_MeasuredWindow.write_to_screen(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            log.warning("_TuiLogHandler.emit(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


class _SlashCompleter(Completer):
    """TUI 输入框的命令补全: 同时支持 `/cmd` 与 Kimi 同款 `+/cmd`。

    只对以 `/` 或 `+/` 开头的输入弹出命令提示; 选择补全项时会把 `+` 前缀
    一并写回, 使 `+/help` 这类命令能直接被回车执行。

    传入 ``tiers`` (命令 -> "core"|"expert"|"hidden") 后: 空输入 `/` 时
    仅返回核心层命令 (≤ 20 项, 防止 55 项菜单压垮屏幕); 输入具体前缀时
    保留全量补全 (专家层命令按前缀可达)。

    C-3 增强 (增量):
    - 模糊匹配: 前缀/子串/子序列三级命中, /mo→/mode;
    - 多级补全: 命令 → 子命令 (如 /safe bench) → 标志 (如 --quick);
    - 参数预览: 每项 display_meta 带帮助文本;
    - 历史优先: ``history`` 传入 MRU 命令表时, 命中项排在前面 (最多 10 条)。
    """

    def __init__(
        self,
        words: List[str],
        metas: Optional[Dict[str, str]] = None,
        tiers: Optional[Dict[str, str]] = None,
        history: Optional[List[str]] = None,
    ) -> None:
        self._words = list(words)
        self._metas = dict(metas or {})
        self._tiers: Dict[str, str] = dict(tiers or {})
        # C-3.5 历史优先: MRU 命令名表 (含前导 "/"), 最近使用排前面
        self._history: List[str] = list(history or [])

    def get_completions(self, document: Any, complete_event: Any) -> Any:  # noqa: C901
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

        # ---- C-3.2 多级补全: 命令已定 + 空格 + 参数片段 ----
        if " " in rest:
            head, _, tail = rest.partition(" ")
            cmd = "/" + head.lstrip("+/").lower()
            tail_tokens = tail.split(" ", 1)
            # 第三级: 子命令已选、正在输 --flag (如 /safe bench --q)
            if len(tail_tokens) == 2 and tail_tokens[1].startswith("--"):
                flag_partial = tail_tokens[1].lower()
                for fl, helptext in _SLASH_FLAGS.get(f"{cmd} {tail_tokens[0]}", []):
                    if not flag_partial or fl.startswith(flag_partial):
                        yield Completion(
                            fl,
                            start_position=-len(flag_partial),
                            display=fl,
                            display_meta=helptext,
                        )
                return
            # 第二级: 子命令候选 (如 /safe → bench/allow/report), 带参数帮助预览
            sub_partial = tail_tokens[0].lower()
            for sub, helptext in _SLASH_SUBCMDS.get(cmd, []):
                sub_name = sub.split(" ")[0]
                if sub_partial and _fuzzy_rank(sub_name, sub_partial) < 0:
                    continue
                yield Completion(
                    " " + sub,
                    start_position=-len(tail),
                    display=sub,
                    display_meta=helptext,
                )
            return  # 无已知子命令表: 不补参数级 (与既有行为一致)

        # ---- 命令级: 模糊匹配 (C-3.1) + 历史优先 (C-3.5) ----
        low = rest.lower().strip()
        ranked: List[Tuple[int, int, int, str]] = []
        for idx, w in enumerate(self._words):
            name = w[1:]  # 去掉前导 "/"
            rank = _fuzzy_rank(name.lower(), low)
            if rank < 0:
                continue
            # 有 tiers 配置时使用传入的 tiers; 无 tiers 时用模块级 slash_command_tier
            if self._tiers:
                tier = self._tiers.get("/" + name, "core")
            else:
                tier = slash_command_tier("/" + name)
            # 隐藏层命令永不进入补全菜单 (仅 /help 全量列出)
            if tier == "hidden":
                continue
            # 空输入时仅补全核心层 (有 tiers 配置且未输入前缀才启用过滤)
            if not low and self._tiers and tier != "core":
                continue
            # 历史命中的排前: 越近越优先 (history 序即 MRU 序); 未命中排末尾
            hist_pos = self._history.index(w) if w in self._history else 1 << 30
            ranked.append((rank, hist_pos, idx, w))
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        for _rank, _h, _i, w in ranked:
            name = w[1:]
            yield Completion(
                plus + w,
                start_position=-cut - len(low),  # 替换光标前的命令前缀+已输入部分
                display=w,
                display_meta=self._metas.get("/" + name, t("tui.cmd_meta")),
            )


class QxtTUI(StateMixin, RenderMixin, LayoutMixin, InteractMixin,
             SlashMenuMixin, PanelsMixin, SloganMixin, LifecycleMixin):
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
        # C-3.3: 面板条目与描述平行表 (_slash_items 第 i 项的帮助文本),
        # 命令级缺省回退 command_meta, 子命令/参数级用 _SLASH_SUBCMDS 帮助。
        self._slash_metas: List[str] = []
        # C-3.5: slash 命令最近使用历史 (MRU, 最近 10 条; 仅会话内存态, 不落盘)
        self._slash_history: List[str] = []
        # C-5.2: 离线检测结果缓存 (footer 高频重绘, 30s 内不重复探测网络)
        self._offline_cache: Optional[bool] = None
        self._offline_ts: float = 0.0

        # 状态
        self._events: List[Any] = []
        # 性能: 历史 screen 缓存。`_scrolled_lines` 每帧都要把 `_events` 全量渲染成
        # 逻辑行并逐行算换行高度 (`_line_heights`), 流式期间每帧全量重算导致卡顿。
        # 只有 `_events` 真的变化 (append/trim) 时才重建缓存, 否则复用。
        self._history_dirty = True
        self._history_screen: Optional[List[List[Tuple[str, str]]]] = None
        self._history_heights: Optional[List[int]] = None
        self._history_width: int = 0
        # 行高缓存: `_line_heights` 按 ``(width, text)`` 缓存每个逻辑行的换行高度,
        # 历史 screen 复用期间每帧只做 dict 查找 (2000+ 行历史原本每帧数万次 C 调用)。
        self._height_cache: Dict[Tuple[int, str], int] = {}
        self._closed = False
        self._busy = False
        self._cancel_requested = threading.Event()
        # 回合开始单调时钟 (codex 状态行 "Working (Ns · esc to interrupt)" 的 elapsed 来源)
        self._turn_started = 0.0
        self._last_streamed_ts = 0.0  # 流式最后更新时间, 驱动 idle 检测

        # ---- slogans 运行时 (B3 续轮 X) ----
        self._slogans: RuntimeSloganEngine = RuntimeSloganEngine()
        self._lang: str = "en"                 # set_lang() 更新
        self._slogan_owner: str = uuid.uuid4().hex[:12]
        # _slogan_log: list of (event, context, reason, origin, entry_id,
        # owner, at_ms) 元组, 上限 64; 测试用 row[0] 取事件。锁保护并发追加。
        self._slogan_log: List[Tuple] = []
        self._slogan_errors: List[Tuple[int, str, str]] = []
        self._slogan_lock = threading.Lock()
        self._slogan_sealed: Tuple[Dict[str, Any], ...] = ()  # close() 封存快照
        self._phase: str = "idle"
        self._phase_since: float = time.monotonic()
        self._last_event_ms: int = 0
        self._tool_throttle_ms = 250
        self._tool_last_ms: int = 0

        # 模式: 标准五模式 ID (set_mode 统一解析; standard 别名 → collaboration)
        self._mode = "collaboration"
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

        # 启动引导 (loading) 状态: 旧实现用粒子徽记加载屏 (与 Codex 脱节), 已删除。
        # 现在启动即渲染对话界面 (会话头 + 空输入区, 对齐 codex startup_draft),
        # 内核在后台构建, 就绪后 set_ready 填充会话头。_boot_error 仅在启动失败时
        # 显示简短错误行。同一 Application / 事件循环, 杜绝双屏切换崩溃。
        self._booting = False
        self._boot_progress = 100
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
        # 复制文本: 记录最后助手回复全文 / 最后用户输入 (F6 / Ctrl+Shift+C 复制)。
        self._last_assistant_text = ""
        self._last_user_text = ""
        self._toast = ""          # 状态行临时提示 (复制成功等), 2 秒后消失
        self._toast_until = 0.0
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

        # Kimi 移植面板状态 (Ctrl+R 会话选择器 / Ctrl+T 任务浏览器 / F2 MCP):
        # 必须在此初始化, 否则 `_handle_enter`/键位路由在面板未打开时访问
        # `self._sp_panel` 会抛 AttributeError (测试在无 app 下直接调 _handle_enter)。
        self._sp_panel: Optional[Dict[str, Any]] = None    # 会话选择器面板
        self._tb_panel: Optional[Dict[str, Any]] = None    # 任务浏览器面板
        self._mcp_visible = False                          # MCP 状态面板开关
        self._mcp_servers: List[Any] = []                  # MCP 服务器缓存
        # Codex 同款 "?" 快捷键帮助浮层 (bottom_pane/shortcut_overlay.rs):
        # 空输入时按 "?" 打开三栏 Compose/Session/Transcript, "?" / esc 关闭。
        self._help_open = False

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
        # Codex CLI 风格输入区: 无边框, 左 "›" 前缀 (bold primary, 2 列),
        # 空输入时显示 dim 灰 placeholder "Ask Codex to do anything"。
        # prompt_toolkit 3.0.53 无 placeholder 参数, 用 _PlaceholderProcessor 注入。
        self._input = TextArea(
            prompt=FormattedText([("class:primary", "› ")]),
            multiline=False,
            # 单行输入必须横向滚动: 若 wrap_lines=True 且 height=1, 中文/宽字符贴到
            # 右边界触发裁剪式软换行 → 最后列宽核算错一位, 高亮重绘(思考动画)把错位
            # 残影卷进输入栏, 表现为 IME 打字/粘贴/英文全变乱码。
            wrap_lines=False,
            scrollbar=False,
            height=1,
            history=InMemoryHistory(),
            # 空输入时显示 Codex 同款 placeholder "Ask Codex to do anything"。
            input_processors=[_PlaceholderProcessor()],  # type: ignore[list-item]
            # "/" 命令面板由 QxtTUI 自绘 (见 _render_slash_menu): 输入 "/" 即弹出,
            # ↑↓ 选择 · Enter/Tab 确认 · Esc 关闭。不走 prompt_toolkit 补全器 ——
            # 其下拉菜单位于输入框下方, 而本布局输入框贴屏幕底部, 菜单会被裁掉。
            completer=None,
            complete_while_typing=False,
        )
        # 输入文本变化 → 命令面板开合/过滤 (Claude Code 同款体验)
        try:
            self._input.buffer.on_text_changed += self._on_input_changed
        except Exception as exc:  # noqa: BLE001 - 测试桩/旧版 pt 无该事件时静默降级
            log.warning("QxtTUI.__init__(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass

        # 输入区: Codex 风格无边框 (仅 "› " 前缀 + 底部状态条), 直接占满底部。
        # 移除早期三层 ╭─╮ 细边框 —— Codex 输入区与消息区之间无绘制边框,
        # 仅靠 "›" 前缀与 placeholder 区分, 与开源 codex-rs/tui 视觉一致。
        self._input_frame = self._input

        # 对话区占满剩余空间: 自绘虚拟视口 (自己切片内容 + 自己算滚动), 不用
        # ScrollablePane (后者在 Windows/conpty 下碎滚动) 也不用伪造光标定位。
        # 用 _MeasuredWindow 记录真实高度, 供 _viewport_rows() 精确切片。
        self._log_window = _MeasuredWindow(
            self._log_control,
            wrap_lines=True,
            height=Dimension(min=1, weight=1),
        )
        conversation = self._log_window
        # 审计面板 (kimi 折叠思考): 默认隐藏, Ctrl+O 展开; 展开约占 45% 高度。
        # 复用同一区域显示 Kimi 移植面板 (Ctrl+R 会话 / Ctrl+T 任务 / F2 MCP)。
        self._audit_control = FormattedTextControl(self._render_audit)
        audit_wrap = ConditionalContainer(
            HSplit([
                Window(char="─" * 1, height=1, style="class:border"),
                Window(self._audit_control, wrap_lines=True, height=Dimension(min=3, weight=2)),
            ]),
            filter=Condition(lambda: (
                self._audit_visible
                or bool(getattr(self, "_sp_panel", None))
                or bool(getattr(self, "_tb_panel", None))
                or bool(getattr(self, "_mcp_visible", False))
            )),
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
        # Codex 同款 "?" 快捷键帮助浮层: 覆盖输入区上方, 三栏 Compose/Session/
        # Transcript + 底部 "/keymap customize" 提示 (对齐 shortcut_overlay.rs)。
        self._help_control = FormattedTextControl(
            self._render_help_overlay, show_cursor=False, focusable=False,
        )
        help_overlay = ConditionalContainer(
            Window(
                self._help_control,
                height=self._help_overlay_rows,
                style="class:slashbg",
                wrap_lines=False,
            ),
            filter=Condition(lambda: self._help_open),
        )
        bottom = ConditionalContainer(
            HSplit([
                help_overlay,
                slash_menu,
                self._input_frame,
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
        except Exception as exc:
            log.warning("QxtTUI.__init__(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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

    

    

    

    

    

    

    # ---- Diff 实时面板 ----

    

    

    

    

    

    # ============================================================ Kimi 移植模块
    # 会话选择器 (Ctrl+R) / 后台任务浏览器 (Ctrl+T) / MCP 状态面板 (F2)。
    # 数据与渲染逻辑在 tuan_cli/tui/kimi_modules.py (直接移植自 Kimi Code
    # ui/shell/{session_picker,task_browser,mcp_status}.py 并适配 tuan_cli 后端),
    # 这里只负责: 状态持有、键位派发、与主布局 (对话区+底栏) 的渲染合流。

    

    

    

    

    

    

    

    

    # ---- 任务浏览器 ----

    

    

    

    

    

    

    

    # ---- MCP 状态面板 ----

    

    

    # ---- 对话区滚动 (自定义光标定位, Windows/conpty 下可靠) ----

    

    

    

    

    

    

    

    

    

    

    

    

       # 具体值在渲染时按 max_top 解析

    

    

    

    

    # ============================================================ 鼠标滚轮

    #: 一次滚轮 notch 翻多少终端行。终端无法上报 notch 数量, 统一按 3 行 ——
    #: 与浏览器/Claude Code 的手感接近, 又不至于一格就翻出屏幕。
    _MOUSE_WHEEL_LINES = 3

    

    

    # ============================================================ "/" 命令面板

    

    

    

    

    

    

    

    

    

    

    # ============================================================ "?" 快捷键帮助浮层
    # 移植自 codex-rs/tui/src/bottom_pane/shortcut_overlay.rs: 标题 "Keyboard shortcuts",
    # 三栏 Compose / Session / Transcript (open first), 底部 "/keymap customize" 提示,
    # 关闭提示 "? / esc close"。快捷键标签按 Windows 平台规范 (ctrl+t / pgup / pgdn / enter)。

    _HELP_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
        ("Compose", [
            ("/", "Commands"),
            ("@", "Mention files"),
            ("!", "Shell command"),
            ("shift+enter", "New line"),
            ("ctrl+v", "Paste image"),
            ("ctrl+g", "External editor"),
            ("ctrl+r", "Search history"),
            ("esc", "Edit last message"),
        ]),
        ("Session", [
            ("tab", "Send message"),
            ("alt+shift+tab", "Change mode"),
            ("alt+,", "Less reasoning"),
            ("alt+.", "More reasoning"),
            ("alt+left / alt+right", "Subagents (empty prompt)"),
            ("f4", "Inspect activity"),
            ("ctrl+c", "Quit"),
        ]),
        ("Transcript (open first)", [
            ("ctrl+t", "Open transcript"),
            ("f3", "Find text"),
            ("pgup / pgdn", "Scroll"),
            ("ctrl+space", "Start selection"),
            ("ctrl+home / ctrl+end", "Top / latest"),
            ("alt+shift+, / alt+shift+.", "Top / latest"),
        ]),
    ]

      # 标题/空行 + 尾部空行 + close 提示

    

    

    

    

    

    # ============================================================ 启动引导 (加载屏)

    

    

    

    # ============================================================ Super-Agent 绑定
    

    

    # ==================================================== slogans 运行时接入

    

    

    

    

    

    

    

    

    

    

    

    

    

    # ============================================================ 流式 / 工具

    

    

    

    

    

    

    

    

    

    

    

    

    

    

    

    # 供应商级默认上下文窗口表已上移到 core.prompt_tier.PROVIDER_CONTEXT_WINDOWS
    # (单一真相源: 同一份规则同时驱动底栏分母与提示词分层定档)。本类不再维护副本,
    # 避免两处数字漂移。
    _PROVIDER_CONTEXT: Dict[str, int] = PROVIDER_CONTEXT_WINDOWS

    

    

    

    

    

    

    

    

    

    

    

    

    

    # ============================================================ 模型提问 (ask_user)

    

    

    

    

    # ============================================================ 运行

    

    

    

    

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

    

    

    

    

    

    

    

    

    

    

    

    

    

    

    

    # ============================================================ 信任确认对话框
    # 首次访问未知目录时由 cmd_chat._boot 调用 prompt_trust(): 挂起确认卡片并
    # 等待用户输入 y/n, 结果经 on_confirm 回调写回 workspace_trust.json 后才 set_ready。
    # 此方法曾在一次 TUI 重写中被误删, 导致 cmd_chat 的 hasattr(tui, "prompt_trust")
    # 恒为 False、确认对话框"又没了" —— 现恢复并加回归测试 (tests/test_tui_fixes.py)。
    

    

    

    

    

    

    

    

    

    

    

    

    

    
