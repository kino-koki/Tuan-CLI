"""Aider 适配器。

调用方式: `aider --message "<prompt>" --yes-always --no-pretty` (AI 结对编程 CLI)。
输出: 文本流 (stdout)。Aider 默认交互式, 这里用 --message 跑单轮, --yes-always
自动接受 git 提交等确认, --no-pretty 关掉 ANSI 美化便于解析。
如命令名不同, 可通过环境变量 TUAN_AIDER_CMD 覆盖。
"""
from __future__ import annotations

import os

from ..base import AgentAdapter, TaskRequest


class AiderAdapter(AgentAdapter):
    id = "aider"
    display_name = "Aider"
    description = "AI 结对编程; 仓库内精准代码编辑"
    command = ("aider",)
    verify = "aider"
    # 打分权重: lingma (灵码, 代码编辑) 最契合; collaboration 次之
    weights = {"chat": 3, "collaboration": 4, "lingma": 5, "gantong": 2, "boundless": 2}

    async def build_command(self, task: TaskRequest) -> list:
        cmd = os.environ.get("TUAN_AIDER_CMD") or "aider"
        return [cmd, "--message", task.prompt, "--yes-always", "--no-pretty"]
