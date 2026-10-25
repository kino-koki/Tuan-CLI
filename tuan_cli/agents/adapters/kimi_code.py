"""Kimi Code 适配器。

调用方式: `kimi-code --prompt "<prompt>"` (Moonshot AI 官方 CLI)。
输出: 文本流 (stdout)。
"""
from __future__ import annotations

from ..base import AgentAdapter, TaskRequest


class KimiCodeAdapter(AgentAdapter):
    id = "kimi-code"
    display_name = "Kimi Code"
    description = "Moonshot AI 官方 CLI; 代码生成与对话"
    command = ("kimi-code", "kimi")
    # 打分权重: lingma (灵码) 模式次优先 (codex 第一)
    weights = {"chat": 3, "collaboration": 3, "lingma": 4, "gantong": 2, "boundless": 2}

    async def build_command(self, task: TaskRequest) -> list:
        return ["kimi-code", "--prompt", task.prompt]
