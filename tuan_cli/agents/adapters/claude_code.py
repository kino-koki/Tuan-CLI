"""Claude Code 适配器。

调用方式: `claude -p "<prompt>"` (print 模式, 非交互, 一次性输出)。
Claude Code 是 Anthropic 官方 CLI, 用于代码编辑与对话。

输出: 纯文本流 (stdout 每行一个片段)。
"""
from __future__ import annotations

from ..base import AgentAdapter, TaskRequest


class ClaudeCodeAdapter(AgentAdapter):
    id = "claude-code"
    display_name = "Claude Code"
    description = "Anthropic 官方 CLI; 代码编辑与对话"
    command = ("claude", "claude-code")
    # 打分权重: chat 模式最强, 其他模式也可用
    weights = {"chat": 5, "collaboration": 4, "lingma": 3, "gantong": 2, "boundless": 2}

    async def build_command(self, task: TaskRequest) -> list:
        # -p / --print: 一次性输出, 不进入交互 REPL
        return ["claude", "-p", task.prompt]
