"""与 Codex ``tui/src/terminal_visualization_instructions.rs`` 对齐。

上游常量（逐条语义，英文原文见模块内 ``TERMINAL_VISUALIZATION_INSTRUCTIONS_EN``）：
  1. 终端场景需要视觉表达时，用紧凑 ASCII 图 / 树 / 时间线 / 表格；
  2. 精确映射或对比用**表格**，不要把已知映射压成散文；
  3. 层级/一对多用**树**，顺序/变化/跨记录状态转移用**图或时间线**；
  4. 视觉内容**只用 ASCII 字符**。

上游 ``with_terminal_visualization_instructions(config, control_instructions)``：
  - feature gate 关闭 -> 原样返回 ``control_instructions``（可能是 None）；
  - 开启时，取 ``control_instructions`` 或回退 ``config.developer_instructions``；
  - 已有内容非空 -> ``existing + "\\n\\n" + 常量``；
  - 否则只返回常量。

本地化修改（如实列出）：
  - 提供**中文版**常量作为默认（这就是「有自己本地化」），英文原文
    保留在 ``..._EN`` 供核销；两种语言都**保留 ASCII-only 约束**；
  - ``config`` 用 duck-typing 的对象而非 Rust ``Config``；
  - 新增 ``active_text(lang)`` 可观测接口；
  - 本地化增强：拼接前对已有指令做长度上限检查，避免提示词被无限
    撑大（上游无此限制，属于更严格）。

许可：Apache-2.0（NOTICE 第 11 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from typing import Any, Optional

TERMINAL_VISUALIZATION_INSTRUCTIONS_EN = (
    "- This surface is a terminal. When the formatting rules require a visual, "
    "include one in the final answer using compact ASCII diagrams, trees, "
    "timelines, or tables.\n"
    "- Use tables for exact mappings or comparisons rather than collapsing "
    "known mappings into prose.\n"
    "- Use trees for hierarchy or one-to-many relationships, and diagrams or "
    "timelines for sequence, change, or state transferred between records "
    "across event order.\n"
    "- Use only ASCII characters in visuals."
)

# 本地化：中文表述，但四条约束（表格/树/时间线/ASCII-only）逐条保留
TERMINAL_VISUALIZATION_INSTRUCTIONS = (
    "- 当前界面是终端。当格式规则需要图示时，在最终回答中用紧凑的 ASCII "
    "示意图、树、时间线或表格呈现。\n"
    "- 精确映射或对比用表格，不要把已知映射压缩成散文。\n"
    "- 层级或一对多关系用树；顺序、变化，或跨记录随事件顺序转移的状态，"
    "用示意图或时间线。\n"
    "- 图示中只使用 ASCII 字符。"
)

MAX_EXISTING_CHARS = 64 * 1024  # 本地化增强的长度上限


def active_text(lang: str = "zh-CN") -> str:
    """返回指定语言的指令常量（默认中文，本地化落点）。"""
    if str(lang).lower().startswith("en"):
        return TERMINAL_VISUALIZATION_INSTRUCTIONS_EN
    return TERMINAL_VISUALIZATION_INSTRUCTIONS


def with_terminal_visualization_instructions(
    config: Any,
    control_instructions: Optional[str] = None,
    *,
    lang: str = "zh-CN",
) -> Optional[str]:
    """对齐上游入口；返回拼好的指令串或原样返回的 ``None``。"""
    features = getattr(config, "features", None)
    enabled = False
    if features is not None:
        if hasattr(features, "enabled"):
            try:
                enabled = bool(features.enabled("TerminalVisualizationInstructions"))
            except Exception:  # noqa: BLE001
                enabled = False
        elif isinstance(features, (set, frozenset, list, tuple)):
            enabled = "TerminalVisualizationInstructions" in features
        elif isinstance(features, dict):
            enabled = bool(features.get("TerminalVisualizationInstructions", False))
    if not enabled:
        return control_instructions

    existing = control_instructions
    if not existing:
        existing = getattr(config, "developer_instructions", None)
    instructions = active_text(lang)
    if isinstance(existing, str) and existing.strip():
        if len(existing) > MAX_EXISTING_CHARS:
            existing = existing[:MAX_EXISTING_CHARS]
        return f"{existing}\n\n{instructions}"
    return instructions
