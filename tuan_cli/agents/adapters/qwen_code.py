"""Qwen Code 适配器。

调用方式: `qwen -p "<prompt>"` (Alibaba 通义千问代码 CLI, gemini-cli fork)。
输出: 文本流 (stdout)。命令名兼容 `qwen` / `qwen-code`;
如不同, 可通过环境变量 TUAN_QWEN_CMD 覆盖。
"""
from __future__ import annotations

import os

from ..base import AgentAdapter, TaskRequest


class QwenCodeAdapter(AgentAdapter):
    id = "qwen-code"
    display_name = "Qwen Code"
    description = "阿里通义千问代码 CLI; 中文代码助手"
    command = ("qwen", "qwen-code")
    verify = "qwen"
    # 打分权重: lingma (中文代码) 与 gantong (中文创意) 兼顾
    weights = {"chat": 4, "collaboration": 3, "lingma": 4, "gantong": 4, "boundless": 3}

    async def build_command(self, task: TaskRequest) -> list:
        cmd = os.environ.get("TUAN_QWEN_CMD") or "qwen"
        return [cmd, "-p", task.prompt]
