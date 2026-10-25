"""DeepSeek Harness 适配器。

调用方式: `dsh --prompt "<prompt>"` (DeepSeek Harness 是当前的编码代理运行环境)。
输出: 文本流 (stdout); 有 subagent / workflow 能力, 适合复杂编排。
"""
from __future__ import annotations

from ..base import AgentAdapter, TaskRequest


class DeepSeekHarnessAdapter(AgentAdapter):
    id = "deepseek-harness"
    display_name = "DeepSeek Harness"
    description = "DeepSeek Harness; 复杂编排与 subagent 调度"
    command = ("dsh", "deepseek-harness")
    # 打分权重: 无界 (boundless) 模式最契合, 因 DSH 有完整 workflow/subagent
    weights = {"chat": 3, "collaboration": 3, "lingma": 4, "gantong": 3, "boundless": 5}

    async def build_command(self, task: TaskRequest) -> list:
        # --prompt: 非交互模式, 一次性执行; --no-tui 禁用 TUI
        return ["dsh", "--prompt", task.prompt]
