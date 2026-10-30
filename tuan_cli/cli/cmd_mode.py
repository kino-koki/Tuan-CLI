"""`tuan mode` —— 五模式切换命令 (感通/灵码/闲聊/无界/协同).

用法:
    tuan mode list             列出所有 5 个模式 (等级 + 风险)
    tuan mode current          显示当前模式
    tuan mode show [mode_id]   显示模式详情 + 能力矩阵 (默认当前模式)
    tuan mode switch <mode_id> 切换模式 (--force 跳过 R2/R3 二次确认)

底层依赖 tuan_cli.modes (唯一事实来源):
    registry.MODE_REGISTRY  五模式元数据 (ID / 等级 / 风险 / 能力)
    switcher.check_transition  R1–R7 切换规则 (纯函数)
    switcher.switch_mode       校验 + 持久化 + 事件 + 审计
    policy.ModePolicy          能力矩阵 (含平台特化, boundless 非桌面禁用)

历史三档别名 (standard / yolo / plan) 全部保留为别名, 通过 resolve_mode_id 解析。
"""

from __future__ import annotations

import sys
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console

from ..modes.policy import get_mode_policy
from ..modes.registry import (
    MODE_ALIASES,
    MODE_IDS,
    get_mode_meta,
    resolve_mode_id,
)
from ..modes.switcher import current_mode, switch_mode


# ---------------------------------------------------------------------------
# 展示辅助
# ---------------------------------------------------------------------------

# 能力矩阵标签顺序 + policy 属性名 (与 §5 能力矩阵一致)
_CAP_ROWS: Tuple[Tuple[str, str], ...] = (
    ("Shell 执行", "shell"),
    ("MCP 调用", "mcp"),
    ("网络访问", "network"),
    ("文件写入", "file_write"),
    ("记忆写入", "memory_write"),
    ("TTS 输出", "tts"),
)

# 各模式能力的补充说明 (仅在能力"允许"时追加括注)
_QUALIFIERS: Dict[str, Dict[str, str]] = {
    "chat": {
        "memory_write": "沙箱",
        "tts": "不限",
    },
    "collaboration": {
        "mcp": "办公白名单",
        "network": "按需确认",
        "memory_write": "沙箱",
    },
    "gantong": {
        "shell": "受限白名单",
        "mcp": "认证",
        "network": "按需确认",
        "memory_write": "沙箱",
    },
    "lingma": {
        "mcp": "代码白名单",
        "network": "按需确认",
        "memory_write": "沙箱",
    },
    "boundless": {
        "shell": "二次确认",
        "file_write": "二次确认",
        "network": "二次确认",
    },
}

_LABEL_WIDTH = 14  # 能力标签 (含冒号) 的对齐宽度

_USAGE = """\
用法: tuan mode <subcommand>

五模式切换 (感通/灵码/闲聊/无界/协同)

子命令:
  list              列出所有模式 (等级 + 风险)
  current           显示当前模式
  show [mode_id]    显示模式详情与能力矩阵 (默认当前模式)
  switch <mode_id>  切换模式 (--force 跳过 R2/R3 二次确认)

模式 ID: gantong / lingma / chat / boundless / collaboration
别名:   standard→collaboration / yolo→boundless / plan→chat
"""


def _disp_len(s: str) -> int:
    """字符串显示宽度 (CJK 全角字符按 2 列计)。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    """按显示宽度左对齐填充空格。"""
    return s + " " * max(0, width - _disp_len(s))


def _platform() -> str:
    """当前平台标识 (供 R6 桌面白名单判定使用)。"""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("darwin"):
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform or "desktop"


def _read_current() -> str:
    """读取当前模式 ID; 失败时抛出异常由调用方处理。"""
    return current_mode()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def cmd_mode(args: Any) -> int:
    """五模式切换命令入口。

    参数:
        args: argparse 解析结果 (含 mode_cmd / mode_id / force)。

    返回:
        退出码 (0=成功, 1=业务失败/拒绝, 2=用法错误)。
    """
    cmd = getattr(args, "mode_cmd", None)

    if cmd == "list":
        return _mode_list()
    if cmd == "current":
        return _mode_current()
    if cmd == "show":
        return _mode_show(getattr(args, "mode_id", None))
    if cmd == "switch":
        return _mode_switch(
            getattr(args, "mode_id", None),
            force=bool(getattr(args, "force", False)),
        )

    Console().print(_USAGE, highlight=False)
    return 2


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def _mode_list() -> int:
    """列出所有 5 个模式 (含等级与风险), 标注当前模式。"""
    console = Console()
    current = None
    try:
        current = _read_current()
    except Exception:  # noqa: BLE001
        current = None

    console.print(
        "[bold]五模式一览[/bold]  [dim]切换: tuan mode switch <mode_id>[/dim]"
    )
    console.print()

    for mode_id in MODE_IDS:
        meta = get_mode_meta(mode_id)
        marker = "  [bold cyan]← 当前[/bold cyan]" if current == meta["id"] else ""
        console.print(
            _pad(meta["name"], 12)
            + f" ({_pad(meta['id'], 14)}) "
            + f"{meta['level']}  [bold]风险:[/bold] {meta['risk']}{marker}"
        )

    console.print()
    console.print(
        "[dim]别名: "
        + " / ".join(f"{k}→{v}" for k, v in MODE_ALIASES.items())
        + "[/dim]"
    )
    return 0


# ---------------------------------------------------------------------------
# current
# ---------------------------------------------------------------------------

def _mode_current() -> int:
    """显示当前模式。"""
    console = Console()
    try:
        mode_id = _read_current()
    except ValueError as exc:
        console.print(f"[red][错误] {exc}[/red]")
        return 1
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red][错误] 读取当前模式失败: {exc}[/red]")
        return 1

    meta = get_mode_meta(mode_id)
    console.print(f"当前模式: [bold]{meta['name']}[/bold] ({meta['id']})")
    return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def _mode_show(mode_id: Optional[str]) -> int:
    """显示模式详情与能力矩阵 (省略 mode_id 时显示当前模式)。"""
    console = Console()
    try:
        resolved = resolve_mode_id(mode_id) if mode_id else _read_current()
    except ValueError as exc:
        console.print(f"[red][错误] {exc}[/red]")
        return 1
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red][错误] 读取当前模式失败: {exc}[/red]")
        return 1

    meta = get_mode_meta(resolved)
    platform = _platform()
    policy = get_mode_policy(resolved, platform=platform)

    console.print(f"模式: [bold]{meta['name']}[/bold] ({meta['id']})")
    console.print(f"权限: [bold]{meta['level']}[/bold]")
    console.print(f"风险: {meta['risk']}")
    console.print(f"描述: {meta['description']}")
    console.print()
    console.print("[bold]能力矩阵:[/bold]")

    for label, cap in _CAP_ROWS:
        allowed = getattr(policy, f"{cap}_allowed")()
        console.print(
            f"  {_pad(label + ':', _LABEL_WIDTH)}{_cap_text(meta['id'], cap, allowed)}"
        )

    tools = policy.tool_allowlist()
    console.print(
        f"  {_pad('工具白名单:', _LABEL_WIDTH)}{len(tools)} 个工具"
    )

    if meta["id"] == "boundless":
        console.print(f"  [dim]平台: {platform} (Android/iOS/Web 物理禁用)[/dim]")

    return 0


def _cap_text(mode_id: str, cap: str, allowed: bool) -> str:
    """渲染单个能力的文本 (允许/禁用 + 括注)。"""
    if not allowed:
        note = "禁用 (平台策略)" if mode_id == "boundless" else "禁用"
        return f"[red]{note}[/red]"
    qualifier = _QUALIFIERS.get(mode_id, {}).get(cap)
    if qualifier:
        return f"[green]允许[/green] ({qualifier})"
    return "[green]允许[/green]"


# ---------------------------------------------------------------------------
# switch
# ---------------------------------------------------------------------------

def _mode_switch(target: Optional[str], *, force: bool = False) -> int:
    """切换模式 (含 R1–R7 校验 + 持久化 + 事件 + 审计)。"""
    console = Console()

    if not target:
        console.print("[red][错误] 用法: tuan mode switch <mode_id>[/red]")
        console.print(f"[dim]可选: {'/'.join(MODE_IDS)}[/dim]")
        return 2

    try:
        resolve_mode_id(target)
    except ValueError as exc:
        console.print(f"[red][拒绝] 原因: {exc}[/red]")
        return 1

    # 内核仅用于事件发射 + 审计 (best-effort, 缺失不阻塞切换)
    kernel: Any = None
    try:
        from ..app import build_kernel

        kernel = build_kernel()
    except Exception:  # noqa: BLE001
        kernel = None

    try:
        ok, reason = switch_mode(
            target, force=force, platform=_platform(), kernel=kernel
        )
    except ValueError as exc:
        console.print(f"[red][拒绝] 原因: {exc}[/red]")
        return 1
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red][错误] 切换失败: {exc}[/red]")
        return 1

    meta = get_mode_meta(resolve_mode_id(target))
    if ok:
        console.print(
            f"[green][成功] 已切换到: {meta['name']} ({meta['id']})[/green]"
        )
        console.print(f"[cyan][原因] {reason}[/cyan]")
        return 0

    console.print(f"[red][拒绝] 原因: {reason}[/red]")
    return 1
