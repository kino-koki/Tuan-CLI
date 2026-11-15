"""委派工具插件 —— 让青小团把任务委派给本机已装的外部 CLI Agent 干活。

「使用对方生态积累」的第二条腿: 除了把对方的资产**导入** tuan, 还可以把任务**委派**
给对方 —— 对方以自己完整的环境 (配置、记忆、技能、MCP server) 执行, 结果回传。

覆盖 9 家 CLI Agent (与 agents/discovery.py 对齐):

=====  =================  =========================================
工具名               CLI 命令           headless 调用形式
=====  =================  =========================================
claude_code_run     claude             claude -p --output-format text "<t>"
codex_run           codex              codex exec "<t>"
hermes_run          hermes             hermes chat -q "<t>"
deepseek_run        dsh                dsh --prompt "<t>"
kimi_code_run       kimi-code          kimi-code --prompt "<t>"
gemini_run          gemini             gemini -p "<t>"
aider_run           aider              aider --message "<t>" --yes-always --no-pretty
qwen_code_run       qwen               qwen -p "<t>"
doubao_run          doubao             doubao -p "<t>"
=====  =================  =========================================

安全口径:
- 只有对应 CLI 在 PATH 里才注册工具 (否则工具不可见, 不产生幽灵命令);
- 子进程带超时与输出上限; 工具标记 dangerous, 触发 tuan 的确认流程;
- 拒绝把用户密钥拼进命令 (任务文本原样传给对方进程, 不经过 shell);
- 环境变量 TUAN_<AGENT>_CMD 可覆盖命令名 (与各 Adapter 对齐)。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from ..core.kernel import Kernel, Plugin
from ..tools.base import Tool, ToolContext, string_prop

# 输出/超时上限: 防对方 Agent 海量输出或无限挂起。
MAX_DELEGATE_OUTPUT = 6000
DEFAULT_DELEGATE_TIMEOUT = 240


def _run_headless(cmd: List[str], task: str, timeout: int) -> str:
    """以参数数组方式执行外部 Agent (不经 shell, 防注入), 返回输出文本。

    task 始终作为**最后一个参数**追加 —— 所有 9 家 CLI 的 headless 模式
    都把 prompt 放在末位（或用 --message/--prompt 标记后紧跟）。
    """
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


# ============================================================ 命令探测器
# 每家返回 List[str] (完整 argv 前缀, 不含 prompt) 或 None (未安装)。
# 环境变量覆盖: TUAN_<NAME>_CMD 让用户改命令名/路径（与 Adapter 对齐）。


def _env_cmd(env_key: str, *candidates: str) -> Optional[List[str]]:
    """按优先级探测候选命令，支持环境变量覆盖。"""
    override = os.environ.get(env_key)
    if override:
        path = shutil.which(override)
        return [path] if path else None
    for name in candidates:
        path = shutil.which(name)
        if path:
            return [path]
    return None


def _claude_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_CLAUDE_CMD", "claude")
    return [*base, "-p", "--output-format", "text"] if base else None


def _codex_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_CODEX_CMD", "codex")
    return [*base, "exec"] if base else None


def _hermes_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_HERMES_CMD", "hermes")
    return [*base, "chat", "-q"] if base else None


def _deepseek_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_DEEPSEEK_CMD", "dsh", "deepseek-harness")
    return [*base, "--prompt"] if base else None


def _kimi_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_KIMI_CMD", "kimi-code", "kimi")
    return [*base, "--prompt"] if base else None


def _gemini_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_GEMINI_CMD", "gemini")
    return [*base, "-p"] if base else None


def _aider_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_AIDER_CMD", "aider")
    return [*base, "--message"] if base else None


def _qwen_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_QWEN_CMD", "qwen", "qwen-code")
    return [*base, "-p"] if base else None


def _doubao_cmd() -> Optional[List[str]]:
    base = _env_cmd("TUAN_DOUBAO_CMD", "doubao", "doubao-cli")
    return [*base, "-p"] if base else None


# aider 需要额外参数 (--yes-always --no-pretty)；用 wrapper 处理
def _aider_full_cmd() -> Optional[List[str]]:
    base = _aider_cmd()
    return [*base, "--yes-always", "--no-pretty"] if base else None


# ============================================================ 工具处理函数


def claude_code_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _claude_cmd()
    if cmd is None:
        return "[不可用] 未检测到 claude CLI (不在 PATH)。可用 `tuan ecosystem scan` 检查。"
    return _run_headless(cmd, task, timeout)


def codex_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _codex_cmd()
    if cmd is None:
        return "[不可用] 未检测到 codex CLI (不在 PATH)。"
    return _run_headless(cmd, task, timeout)


def hermes_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _hermes_cmd()
    if cmd is None:
        return "[不可用] 未检测到 hermes CLI (不在 PATH)。可用 `tuan ecosystem scan` 检查。"
    return _run_headless(cmd, task, timeout)


def deepseek_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _deepseek_cmd()
    if cmd is None:
        return "[不可用] 未检测到 dsh / deepseek-harness CLI (不在 PATH)。"
    return _run_headless(cmd, task, timeout)


def kimi_code_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _kimi_cmd()
    if cmd is None:
        return "[不可用] 未检测到 kimi-code CLI (不在 PATH)。"
    return _run_headless(cmd, task, timeout)


def gemini_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _gemini_cmd()
    if cmd is None:
        return "[不可用] 未检测到 gemini CLI (不在 PATH)。"
    return _run_headless(cmd, task, timeout)


def aider_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _aider_full_cmd()
    if cmd is None:
        return "[不可用] 未检测到 aider CLI (不在 PATH)。"
    return _run_headless(cmd, task, timeout)


def qwen_code_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _qwen_cmd()
    if cmd is None:
        return "[不可用] 未检测到 qwen CLI (不在 PATH)。"
    return _run_headless(cmd, task, timeout)


def doubao_run(ctx: ToolContext, task: str, timeout: int = DEFAULT_DELEGATE_TIMEOUT) -> str:
    cmd = _doubao_cmd()
    if cmd is None:
        return "[不可用] 未检测到 doubao CLI (不在 PATH)。"
    return _run_headless(cmd, task, timeout)


# ============================================================ 工具规格表
# (工具名, 处理函数, 命令探测器, 中文描述)


_TOOLS: List[Tuple[str, Any, Any, str]] = [
    ("claude_code_run", claude_code_run, _claude_cmd,
     "把任务委派给 Claude Code (headless claude -p) 执行并返回结果。"
     "Claude Code 以其自身配置/记忆/技能/MCP server 完整环境运行。"),
    ("codex_run", codex_run, _codex_cmd,
     "把任务委派给 OpenAI Codex CLI (headless codex exec) 执行并返回结果。"),
    ("hermes_run", hermes_run, _hermes_cmd,
     "把任务委派给 Hermes Agent (headless hermes chat -q) 执行并返回结果。"
     "Hermes 以其自身记忆/技能/cron 环境运行。"),
    ("deepseek_run", deepseek_run, _deepseek_cmd,
     "把任务委派给 DeepSeek Harness (headless dsh --prompt) 执行并返回结果。"
     "DSH 具备 subagent / workflow 编排能力。"),
    ("kimi_code_run", kimi_code_run, _kimi_cmd,
     "把任务委派给 Kimi Code (headless kimi-code --prompt) 执行并返回结果。"),
    ("gemini_run", gemini_run, _gemini_cmd,
     "把任务委派给 Google Gemini CLI (headless gemini -p) 执行并返回结果。"
     "多模态代码与推理。"),
    ("aider_run", aider_run, _aider_cmd,
     "把任务委派给 Aider (headless aider --message --yes-always --no-pretty) "
     "在当前仓库执行精准代码编辑并返回结果。"),
    ("qwen_code_run", qwen_code_run, _qwen_cmd,
     "把任务委派给通义千问代码 CLI (headless qwen -p) 执行并返回结果。"
     "中文代码助手。"),
    ("doubao_run", doubao_run, _doubao_cmd,
     "把任务委派给字节豆包 CLI (headless doubao -p) 执行并返回结果。"
     "多模态识图与中文对话。"),
]


class EcosystemPlugin(Plugin):
    """生态插件: 按需注册 9 家 CLI Agent 委派工具。

    仅在对应 CLI 存在于 PATH 时注册, 避免在无该生态的机器上制造不可用工具。
    Agent-of-Agents 契约: 这些工具让模型直接调用本机已装的其他 Agent ——
    不经 SubAgent, 而是把子进程交给对方完整环境。
    """

    name = "ecosystem.invoke"
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        for tool_name, handler, probe, desc in _TOOLS:
            if probe() is not None:
                registry.register(Tool(
                    name=tool_name,
                    description=desc,
                    parameters={
                        "type": "object",
                        "properties": {
                            "task": string_prop("要交给对方 Agent 执行的任务描述"),
                            "timeout": string_prop("超时秒数 (默认 240)"),
                        },
                        "required": ["task"],
                    },
                    handler=handler, group="ecosystem", dangerous=True,
                ))


__all__ = [
    "EcosystemPlugin",
    "claude_code_run", "codex_run", "hermes_run",
    "deepseek_run", "kimi_code_run", "gemini_run",
    "aider_run", "qwen_code_run", "doubao_run",
]
