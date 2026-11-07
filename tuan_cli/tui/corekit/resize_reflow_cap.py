"""与 Codex ``tui/src/resize_reflow_cap.rs`` 对齐的重排行上限。

上游模块头（契约原文）：

    "Terminal-specific row caps for resize reflow. The auto cap mirrors
    documented scrollback defaults for terminals we can identify. ...
    These caps are deliberately conservative: Codex is rebuilding normal
    terminal scrollback, not an internal virtual transcript. Replaying more
    rows than the terminal retains wastes work and can make interactive
    resize feel worse without giving the user more usable history."

逐值常量（**一个都不能改**）：
  - ``VSCODE_RESIZE_REFLOW_MAX_ROWS = 1_000``
  - ``WINDOWS_TERMINAL_RESIZE_REFLOW_MAX_ROWS = 9_001``
  - ``WEZTERM_RESIZE_REFLOW_MAX_ROWS = 3_500``
  - ``ALACRITTY_RESIZE_REFLOW_MAX_ROWS = 10_000``
  - 其余终端（AppleTerminal / Ghostty / Rex / Iterm2 / Warp / Kitty /
    Konsole / GnomeTerminal / Vte / Dumb / Unknown）走
    ``DEFAULT_TERMINAL_RESIZE_REFLOW_FALLBACK_MAX_ROWS``。

三态 ``max_rows``：
  - ``Auto`` -> 按终端探测结果返回一个上限；
  - ``Disabled`` -> **返回 None**，含义是「用户显式禁用行数限制，保留全部行」；
  - ``Limit(n)`` -> 直接返回 n，**覆盖自动探测**。

另一个关键分支：**VS Code 环境探测优先于终端名**
（``running_in_vscode_terminal=True`` 时即使终端名是 WindowsTerminal
也返回 1000）。上游注释解释了原因：VS Code 里 shell 的终端名元数据
常指向宿主 shell 而非 VS Code 本身。

本地化修改（如实列出）：
  - Rust enum / ``TerminalInfo`` -> Python ``Enum`` + 可注入探测函数；
  - fallback 常量值需从本仓库配置取；上游来自
    ``codex_config::types``，这里给出**明确默认值 1000** 并在
    ``configure_fallback()`` 允许注入，文档如实标注来源差异；
  - ``Limit(n)`` 做上下界校验（0 视为 Disabled，负数/超大拒绝），
    本地化 fail-closed 增强；
  - 新增 ``cap_for()`` 可观测入口，返回 ``(值, 原因)`` 便于审计。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, Optional, Tuple

VSCODE_RESIZE_REFLOW_MAX_ROWS = 1_000
WINDOWS_TERMINAL_RESIZE_REFLOW_MAX_ROWS = 9_001
WEZTERM_RESIZE_REFLOW_MAX_ROWS = 3_500
ALACRITTY_RESIZE_REFLOW_MAX_ROWS = 10_000

# 上游来自 codex_config::types；本地化：给明确默认并允许注入
DEFAULT_TERMINAL_RESIZE_REFLOW_FALLBACK_MAX_ROWS = 1_000
MAX_CONFIGURABLE_ROWS = 100_000

_fallback_rows = DEFAULT_TERMINAL_RESIZE_REFLOW_FALLBACK_MAX_ROWS


class TerminalName(str, Enum):
    """逐名对齐上游 TerminalName 枚举。"""

    VS_CODE = "VsCode"
    WINDOWS_TERMINAL = "WindowsTerminal"
    WEZTERM = "WezTerm"
    ALACRITTY = "Alacritty"
    APPLE_TERMINAL = "AppleTerminal"
    GHOSTTY = "Ghostty"
    REX = "Rex"
    ITERM2 = "Iterm2"
    WARP_TERMINAL = "WarpTerminal"
    KITTY = "Kitty"
    KONSOLE = "Konsole"
    GNOME_TERMINAL = "GnomeTerminal"
    VTE = "Vte"
    DUMB = "Dumb"
    UNKNOWN = "Unknown"


class MaxRowsMode(str, Enum):
    """对齐 ``TerminalResizeReflowMaxRows`` 三态。"""

    AUTO = "Auto"
    DISABLED = "Disabled"
    LIMIT = "Limit"


class TerminalResizeReflowConfig:
    """对齐上游配置结构。"""

    def __init__(self, mode: MaxRowsMode = MaxRowsMode.AUTO,
                 limit: int = 0):
        self.mode = mode
        self.limit = limit

    @classmethod
    def auto(cls) -> "TerminalResizeReflowConfig":
        return cls(MaxRowsMode.AUTO)

    @classmethod
    def disabled(cls) -> "TerminalResizeReflowConfig":
        return cls(MaxRowsMode.DISABLED)

    @classmethod
    def limit(cls, n: int) -> "TerminalResizeReflowConfig":
        return cls(MaxRowsMode.LIMIT, n)


def configure_fallback(rows: int) -> None:
    """本地化：允许按本仓库配置覆盖 fallback（默认 1000）。"""
    global _fallback_rows
    if not (0 < rows <= MAX_CONFIGURABLE_ROWS):
        raise ValueError("fallback 行数必须为正且不超过上限")
    _fallback_rows = rows


def fallback_rows() -> int:
    return _fallback_rows


def auto_resize_reflow_max_rows(
    terminal_name: TerminalName,
    running_in_vscode_terminal: bool = False,
) -> int:
    """逐分支对齐上游；VS Code probe **优先于**终端名。"""
    if running_in_vscode_terminal:
        return VSCODE_RESIZE_REFLOW_MAX_ROWS
    return {
        TerminalName.VS_CODE: VSCODE_RESIZE_REFLOW_MAX_ROWS,
        TerminalName.WINDOWS_TERMINAL: WINDOWS_TERMINAL_RESIZE_REFLOW_MAX_ROWS,
        TerminalName.WEZTERM: WEZTERM_RESIZE_REFLOW_MAX_ROWS,
        TerminalName.ALACRITTY: ALACRITTY_RESIZE_REFLOW_MAX_ROWS,
    }.get(terminal_name, _fallback_rows)


def resize_reflow_max_rows_for(
    config: TerminalResizeReflowConfig,
    terminal_name: TerminalName,
    running_in_vscode_terminal: bool = False,
) -> Optional[int]:
    """对齐上游三态入口；返回 ``None`` = 显式禁用、保留全部行。"""
    if config.mode is MaxRowsMode.DISABLED:
        return None
    if config.mode is MaxRowsMode.LIMIT:
        n = config.limit
        if n < 0 or n > MAX_CONFIGURABLE_ROWS:
            # 本地化 fail-closed：非法上限退回保守 fallback，绝不无限重放
            return _fallback_rows
        if n == 0:
            return None
        return n
    return auto_resize_reflow_max_rows(terminal_name,
                                       running_in_vscode_terminal)


def resize_reflow_max_rows(
    config: TerminalResizeReflowConfig,
    terminal_probe: Optional[Callable[[], TerminalName]] = None,
    vscode_probe: Optional[Callable[[], bool]] = None,
) -> Optional[int]:
    """对齐上游顶层入口（探测可注入，便于确定性测试）。"""
    name = terminal_probe() if terminal_probe else TerminalName.UNKNOWN
    vscode = vscode_probe() if vscode_probe else False
    return resize_reflow_max_rows_for(config, name, vscode)


def cap_for(config: TerminalResizeReflowConfig,
            terminal_name: TerminalName,
            running_in_vscode_terminal: bool = False
            ) -> Tuple[Optional[int], str]:
    """本地化增强：返回 (上限, 原因)，便于审计为何截断。"""
    if config.mode is MaxRowsMode.DISABLED:
        return None, "用户显式禁用行数限制，保留全部行"
    if config.mode is MaxRowsMode.LIMIT:
        if config.limit == 0:
            return None, "Limit(0) 视为 Disabled"
        if config.limit < 0 or config.limit > MAX_CONFIGURABLE_ROWS:
            return _fallback_rows, "非法上限，fail-closed 回退 fallback"
        return config.limit, "显式配置覆盖自动探测"
    if running_in_vscode_terminal:
        return VSCODE_RESIZE_REFLOW_MAX_ROWS, "VS Code 环境探测优先"
    if terminal_name in (TerminalName.VS_CODE, TerminalName.WINDOWS_TERMINAL,
                         TerminalName.WEZTERM, TerminalName.ALACRITTY):
        return auto_resize_reflow_max_rows(terminal_name), "按终端文档默认值"
    return _fallback_rows, "未知/其他终端走保守 fallback"


def constants() -> Dict[str, int]:
    """可观测：逐值常量，供 parity 自检核销。"""
    return {
        "vscode": VSCODE_RESIZE_REFLOW_MAX_ROWS,
        "windows_terminal": WINDOWS_TERMINAL_RESIZE_REFLOW_MAX_ROWS,
        "wezterm": WEZTERM_RESIZE_REFLOW_MAX_ROWS,
        "alacritty": ALACRITTY_RESIZE_REFLOW_MAX_ROWS,
        "fallback": _fallback_rows,
        "terminal_names": len(TerminalName),
    }
