"""Tuan TUI 输入/终端能力对齐层（第 11 轮）。

逐模块对齐 OpenAI Codex ``codex-rs/tui/src`` 的 ``input_keymap`` 组，
用纯 Python 独立实现，零 Rust 源码复制。每个模块的 docstring 都列出
上游契约与本地化修改点；许可见 ``NOTICE`` 第 11 条、
``THIRD_PARTY_LICENSES/Codex-NOTICE.txt``（ratatui MIT）。

| 上游模块 | 本包模块 | 对齐要点 |
|---|---|---|
| ``vim_search.rs`` | ``vim_search`` | 字面匹配、完整 grapheme、方向反转 |
| ``activation_key_guard.rs`` | ``activation_key_guard`` | 1s 双窗口、Repeat/Release 状态机 |
| ``copy_input_guard.rs`` | ``copy_input_guard`` | RAII/Drop 释放、异常路径也释放 |
| ``custom_terminal.rs`` | ``custom_terminal`` | 双缓冲 diff、ClearToEnd、OSC8、同步帧 |
| ``terminal_program_status.rs`` | ``terminal_program_status`` | OSC 7501/21337、去重缓存、注入转义 |
| ``terminal_hyperlinks.rs`` | ``terminal_hyperlinks`` | 工作区逃逸校验、OSC8 不影响几何 |
| ``terminal_visualization_instructions.rs`` | ``terminal_visualization_instructions`` | feature gate、指令拼接 |

本地化边界：渲染后端（crossterm/ratatui -> 可注入 Python 协议）、
文案（中文）、CJK 宽度、安全增强（scheme 白名单、OSC 注入防护、
fail-closed 祖先检查）。**键位、常量数值、状态机分支、契约语义不改**，
它们是「与 Codex 完全相同」的锚点。
"""
from __future__ import annotations

from . import (
    activation_key_guard,
    copy_input_guard,
    custom_terminal,
    terminal_hyperlinks,
    terminal_program_status,
    terminal_visualization_instructions,
    vim_search,
)

__all__ = [
    "activation_key_guard", "copy_input_guard", "custom_terminal",
    "terminal_hyperlinks", "terminal_program_status",
    "terminal_visualization_instructions", "vim_search",
    "inputkit_report", "inputkit_validate",
]


def inputkit_report() -> dict:
    """可观测入口：被 ``tuan tui parity`` 消费。"""
    return {
        "modules": 7,
        "upstream_group": "input_keymap",
        "constants": {
            "INITIAL_GUARD_SECONDS": activation_key_guard.INITIAL_GUARD_SECONDS,
            "LEGACY_REPEAT_GUARD_SECONDS":
                activation_key_guard.LEGACY_REPEAT_GUARD_SECONDS,
            "MIN_VTE_VERSION_WITH_SAFE_OSC":
                terminal_program_status.MIN_VTE_VERSION_WITH_SAFE_OSC,
            "MAX_HYPERLINK_DESTINATION_BYTES":
                terminal_hyperlinks.MAX_HYPERLINK_DESTINATION_BYTES,
            "SAFE_WORKSPACE_EXTENSIONS":
                list(terminal_hyperlinks.SAFE_WORKSPACE_EXTENSIONS),
            "MAX_POPUP_ROWS": 8,
        },
        "statuses": [s.value for s in terminal_program_status.ProgramStatusKind],
        "visualization_lang_default": "zh-CN",
    }


def inputkit_validate() -> list[str]:
    """自检：常量、状态机、超链接安全契约是否自洽。"""
    problems: list[str] = []
    if activation_key_guard.INITIAL_GUARD_SECONDS != 1.0:
        problems.append("INITIAL_GUARD 不等于上游 1s")
    if terminal_program_status.MIN_VTE_VERSION_WITH_SAFE_OSC != 5400:
        problems.append("VTE 版本阈值不等于 5400")
    if terminal_hyperlinks.MAX_HYPERLINK_DESTINATION_BYTES != 8192:
        problems.append("超链接目的地上限不等于 8192")
    if len(terminal_hyperlinks.SAFE_WORKSPACE_EXTENSIONS) != 17:
        # 逐值核销：rs/go/c/cc/cpp/h/hpp/java/kt/swift/toml/json/
        # yaml/yml/md/txt/css 共 17 项
        problems.append("工作区扩展名白名单数量异常")
    if terminal_program_status.ProgramStatus.working().iterm_label() != "Working":
        problems.append("Working 的 iTerm label 不对")
    if terminal_program_status.ProgramStatus.blocked(
            terminal_program_status.ProgramStatusKind.PERMISSION
    ).iterm_indicator() != "#5f87ff":
        problems.append("Blocked 的 iTerm indicator 不对")
    # 安全契约：javascript: 必须被拒
    if terminal_hyperlinks.TerminalHyperlink.web(
            range(0, 4), "javascript:alert(1)") is not None:
        problems.append("web() 未拦截非 http(s) scheme")
    return problems
