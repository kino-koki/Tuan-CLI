"""委派工具插件 —— 让青小团直接调用 Claude Code / Hermes 干活。

「使用对方生态积累」的第二条腿: 除了把对方的资产**导入** qxt, 还可以把任务**委派**
给对方 —— 对方以自己完整的环境 (配置、记忆、技能、MCP server) 执行, 结果回传。

- ``claude_code_run``: 调 ``claude -p --output-format text "<task>"`` (headless);
- ``hermes_run``:     调 ``hermes chat -q "<task>"``。

安全口径:
- 只有对应 CLI 在 PATH 里才注册工具 (否则工具不可见, 不产生幽灵命令);
- 子进程带超时与输出上限; 工具标记 dangerous, 触发 qxt 的确认流程;
- 拒绝把用户密钥拼进命令 (任务文本原样传给对方进程, 不经过 shell)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.kernel import Kernel, Plugin
from ..tools.base import Tool, ToolContext, string_prop

# 输出/超时上限: 防对方 Agent 海量输出或无限挂起。
MAX_DELEGATE_OUTPUT = 6000
DEFAULT_DELEGATE_TIMEOUT = 240


def _run_headless(cmd: List[str], task: str, timeout: int) -> str:
    """以参数数组方式执行外部 Agent (不经 shell, 防注入), 返回输出文本。"""
    try:
        proc = subprocess.run(
            [*cmd, task],
            capture_output=True, text=True,
            timeout=max(10, min(int(timeout), 600)),
        )
    except subprocess.TimeoutExpired:
        return f"[超时] {cmd[0]} 执行超过 {timeout}s, 已终止。"
    except OSError as exc:
        return f"[错误] 无法启动 {cmd[0]}: {exc}"
    out = (proc.stdout or "").strip()
    if not out and proc.stderr:
        out = proc.stderr.strip()
    status = f"\n[退出码 {proc.returncode}]" if proc.returncode else ""
    return (out[:MAX_DELEGATE_OUTPUT] + status) if out else f"(无输出, 退出码 {proc.returncode})"


def _claude_cmd() -> Optional[List[str]]:
    exe = shutil.which("claude")
    if not exe:
        return None
    return [exe, "-p", "--output-format", "text"]


def _hermes_cmd() -> Optional[List[str]]:
    exe = shutil.which("hermes")
    if not exe:
        return None
    return [exe, "chat", "-q"]


def claude_code_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _claude_cmd()
    if cmd is None:
        return "[不可用] 未检测到 claude CLI (不在 PATH)。可用 `qxt ecosystem scan` 检查。"
    return _run_headless(cmd, task, timeout)


def hermes_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _hermes_cmd()
    if cmd is None:
        return "[不可用] 未检测到 hermes CLI (不在 PATH)。可用 `qxt ecosystem scan` 检查。"
    return _run_headless(cmd, task, timeout)


class EcosystemPlugin(Plugin):
    """生态插件: 注册委派工具 (claude_code_run / hermes_run)。

    仅在对应 CLI 存在时注册, 避免在无该生态的机器上制造不可用工具。
    """

    name = "ecosystem.invoke"
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        if _claude_cmd() is not None:
            registry.register(Tool(
                name="claude_code_run",
                description="把任务委派给 Claude Code (headless claude -p) 执行并返回结果。"
                            "Claude Code 以其自身配置/记忆/技能/MCP server 完整环境运行。",
                parameters={
                    "type": "object",
                    "properties": {
                        "task": string_prop("要交给 Claude Code 执行的任务描述"),
                        "timeout": string_prop("超时秒数 (默认 240)", ),
                    },
                    "required": ["task"],
                },
                handler=claude_code_run, group="ecosystem", dangerous=True,
            ))
        if _hermes_cmd() is not None:
            registry.register(Tool(
                name="hermes_run",
                description="把任务委派给 Hermes Agent (headless hermes chat -q) 执行并返回结果。"
                            "Hermes 以其自身记忆/技能/cron 环境运行。",
                parameters={
                    "type": "object",
                    "properties": {
                        "task": string_prop("要交给 Hermes 执行的任务描述"),
                        "timeout": string_prop("超时秒数 (默认 240)", ),
                    },
                    "required": ["task"],
                },
                handler=hermes_run, group="ecosystem", dangerous=True,
            ))


__all__ = ["EcosystemPlugin", "claude_code_run", "hermes_run"]
