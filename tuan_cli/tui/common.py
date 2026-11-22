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
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

from tuan_cli.ui.theme import BRAND_PRIMARY

log = logging.getLogger(__name__)

_wcswidth_impl: Optional[Callable[..., int]] = None
try:
    from wcwidth import wcswidth as _wcswidth_fn  # 终端显示宽度 (prompt_toolkit 同源依赖)
    _wcswidth_impl = _wcswidth_fn
except Exception as exc:  # noqa: BLE001
    log.warning("模块顶层: 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
    pass


def _wcswidth(s: str) -> int:
    """兼容包装: 有 wcwidth 用 wcwidth, 否则退化为逐字符估算。"""
    if _wcswidth_impl is not None:
        return int(_wcswidth_impl(s))
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


@lru_cache(maxsize=4096)
def _display_width(s: str) -> int:
    """整串的终端显示宽度 —— 全仓**唯一**的宽度真值来源。

    渲染每一帧都要给全部历史行算宽度 (见 `_line_heights`)。逐字符调用
    ``_wcswidth`` 是 Python 层循环, 2000 行历史每帧要多跑几万次函数调用
    (实测约 30ms/帧), 而流式输出时每帧都要重算, 直接表现为卡顿。
    ``wcwidth.wcswidth`` 内部是 C 实现且自带组合字符/东亚宽字符处理, 整串调用
    结果与逐字累加一致。

    例外: 串里含**控制字符**时 ``wcswidth`` 返回 -1 (表示"无法计算"), 此时回退
    逐字累加, 保持与旧实现一致的行为, 不能让 -1 变成 0 宽度而算错行高。

    有界缓存 (4096) 是第二层保险: `_line_heights` 本身按 ``(width, text)``
    缓存高度, 但其它调用点 (裁剪/对齐) 仍会高频重复计算同一批片段。
    """
    if not s:
        return 0
    if _wcswidth_impl is not None:
        w = _wcswidth_impl(s)
        if w >= 0:
            return int(w)
    return sum(max(0, _wcswidth(ch)) for ch in s)

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
    # 占位实例替代 Keys 枚举: 两个分支运行期互斥, 但类型检查器无法表达
    # "同名符号既是枚举类又是降级实例" —— 与下方占位类同属可选依赖降级。
    # 用 globals() 绑定而非同名赋值: 避免对已导入符号的静态重定义报错。
    globals()["Keys"] = _MissingKeys()

    class Completer:  # type: ignore[no-redef]
        """占位基类: prompt_toolkit 缺失时仅为让下面的类定义通过。"""

    class Window:  # type: ignore[no-redef]
        """占位基类: prompt_toolkit 缺失时仅为让 `class _MeasuredWindow(Window)` 通过。

        只保证**导入**成功 (模块级基类解析); 真正实例化 _MeasuredWindow 仍需
        prompt_toolkit, 此时会在 TUI 启动处给出清晰错误, 而不是在 import 时 NameError。
        """

    def _completion_placeholder(*args: Any, **kwargs: Any) -> None:
        """占位构造器: prompt_toolkit 缺失时给出可读错误, 而不是 NameError。"""
        raise RuntimeError(
            "prompt_toolkit 未安装, 无法使用 TUI 输入补全; 安装 prompt_toolkit 或改用 CLI 模式"
        )
    globals()["Completion"] = _completion_placeholder


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
    "/approvals": [
        ("read-only", "只读: 修改类工具拦截 (Plan 只读)"),
        ("auto", "标准: 按风险分级确认 (默认)"),
        ("full-access", "全自动批准 (YOLO; 红线工具仍强制确认)"),
    ],
    "/watch": [
        ("transcript", "只看字幕/转写, 不抽帧"),
        ("swift", "快速档: 约 24 帧封顶"),
        ("balanced", "均衡档: 约 48 帧 (默认)"),
        ("deep", "深度档: 约 96 帧封顶"),
    ],
    "/reach": [
        ("doctor", "全频道健康自检"),
        ("channels", "列出频道与后端回退链"),
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

# ---- 桥接命令的第二级子命令补全: 从 CLI parser 动态派生 (不手工复制) ----
# /obs→cost/status/cache 等全部桥接命令的子命令直接来自 build_parser() 的
# subparser choices, 与 CLI 保持单一权威来源; 描述回退到 slash_command_meta。
# 解析器构建失败时静默跳过, 不阻断 TUI 加载 (只少二级补全, 不影响执行)。
try:  # pragma: no cover - 仅 import 期副作用
    from ..cli.cmd_slash_bridge import _BRIDGE_TABLE as _BRIDGE, _known_subcommands
    from ..cli.cmd_slash import slash_command_meta as _bridge_meta
    _bm = _bridge_meta()
    for _head in _BRIDGE:
        if _head in _SLASH_SUBCMDS:
            continue  # 已有手写补全的命令 (如 /mcp) 优先保留手写版
        _subs = _known_subcommands(_head)
        if _subs:
            _SLASH_SUBCMDS[_head] = [(s, _bm.get(_head, "")) for s in sorted(_subs)]
except Exception as exc:  # noqa: BLE001 - 派生失败不影响其余补全
    log.warning("模块顶层: 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
    pass


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


#: 旧调用点沿用的别名: 视口切片/单行裁剪/欢迎盒对齐必须共用**同一套**宽度
#: 算法。历史上这里是 prompt_toolkit 逐字 ``get_cwidth`` 求和, 与
#: ``_display_width`` 的整串 ``wcswidth`` 对 emoji/组合字符会给出不同答案,
#: 导致同一行在行高计算与裁剪两处宽度不一致 (B3)。
_disp_width = _display_width


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


# 拆分后: 上述全部模块级名字 (常量/配色/工具/小类) 统一由此导出,
# 供 tui.py 与 layout/render/state 三个 mixin 模块 `import *` 共享。
#
# 必须写成**字面量列表**, 不能用 `[n for n in globals() ...]` 推导:
# 推导出来的 __all__ 对 mypy 是不透明表达式, 它会把下游的
# `from .common import *` 当成"什么都没导入", 于是 tui/render/state/layout
# 里所有依赖这些名字的注解与调用都报 name-defined —— 而运行时完全正常
# (星号导入按模块 globals 真实展开)。CI 的 `python -m mypy tuan_cli` 门禁
# 就卡在这里。新增模块级名字时请同步补进本列表。
__all__ = [
    "Any", "Application", "Callable", "Completer", "Completion",
    "Condition", "ConditionalContainer", "Dict", "Dimension", "DummyOutput",
    "FAILURE_MARK", "FormattedText", "FormattedTextControl", "HSplit", "InMemoryHistory",
    "KeyBindings", "Keys", "Layout", "List", "Optional",
    "PROVIDER_CONTEXT_WINDOWS", "Point", "Processor", "STATUS_BULLET", "STYLE",
    "SUCCESS_MARK", "Style", "TERMINAL_TITLE", "TextArea", "Transformation",
    "TransformationInput", "Tuple", "USER_MESSAGE_BG", "USER_MESSAGE_BULLET", "VERSION",
    "VSplit", "Window", "_ACCENT", "_BG_PANEL", "_BLUE_DIM",
    "_BORDER", "_BRIDGE", "_DIM", "_ERROR", "_HAS_PT",
    "_MAX_LOG_LEN", "_MAX_REASON_LEN", "_MAX_STREAM_BUF", "_MOON_FRAMES", "_MOON_INTERVAL",
    "_MUTED", "_MeasuredWindow", "_MissingKeys", "_PRIMARY", "_PlaceholderProcessor",
    "_ROLEUSER", "_SHELL", "_SLASH_FLAGS", "_SLASH_MAX_VISIBLE", "_SLASH_SUBCMDS",
    "_SPLASH_FRAMES", "_STYLE_DICT", "_SUCCESS", "_SlashCompleter", "_TEXT",
    "_TEXT_STRONG", "_TuiLogHandler", "_WARNING", "_ask_user_plain", "_bm",
    "_bridge_meta", "_disp_width", "_display_width", "_env_flag", "_fuzzy_rank",
    "_head", "_known_subcommands", "_split_flat_lines", "_subs", "_wcswidth",
    "_wcswidth_impl", "annotations", "logging", "lru_cache", "math",
    "os", "re", "shutil", "sys", "t",
    "threading", "time", "to_filter",
]
