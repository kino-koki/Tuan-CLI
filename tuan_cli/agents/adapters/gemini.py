"""Gemini CLI 适配器。

调用方式: `gemini -p "<prompt>"` (Google Gemini CLI 非交互 prompt 模式)。
输出: 文本流 (stdout)。部分版本用 `--prompt`; 这里统一用 `-p` (与 claude 一致)。
如用户机器命令名不同, 可通过环境变量 TUAN_GEMINI_CMD 覆盖。
"""
from __future__ import annotations

import os

from ..base import AgentAdapter, TaskRequest


class GeminiAdapter(AgentAdapter):
    id = "gemini"
    display_name = "Gemini CLI"
    description = "Google Gemini CLI; 多模态代码与推理"
    command = ("gemini",)
    verify = "gemini"
    # 打分权重: boundless (无界) 创意/多模态最契合, chat/通用次之
    weights = {"chat": 4, "collaboration": 3, "lingma": 2, "gantong": 4, "boundless": 5}

    async def build_command(self, task: TaskRequest) -> list:
        cmd = os.environ.get("TUAN_GEMINI_CMD") or "gemini"
        return [cmd, "-p", task.prompt]
