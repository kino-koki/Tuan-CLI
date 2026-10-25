"""CodeX 适配器。

调用方式: `codex exec "<prompt>"` (OpenAI 官方 CodeX CLI 的 exec 子命令)。
输出: 文本流 (stdout)。
"""
from __future__ import annotations

from ..base import AgentAdapter, TaskRequest


class CodeXAdapter(AgentAdapter):
    id = "codex"
    display_name = "Codex"
    description = "OpenAI 官方 CodeX CLI; 代码生成与执行"
    command = ("codex",)
    verify = "codex"  # --version 输出如 "codex-cli 0.44.0" 含此标识
    # 打分权重: lingma (灵码) 模式最契合
    weights = {"chat": 2, "collaboration": 3, "lingma": 5, "gantong": 1, "boundless": 2}

    async def build_command(self, task: TaskRequest) -> list:
        return ["codex", "exec", task.prompt]
