"""豆包 (Doubao) 适配器。

调用方式: `doubao -p "<prompt>"` (字节跳动豆包 CLI; doubao-cli 式多模态识图)。
输出: 文本流 (stdout)。命令名兼容 `doubao` / `doubao-cli`;
如不同, 可通过环境变量 TUAN_DOUBAO_CMD 覆盖。
"""
from __future__ import annotations

import os

from ..base import AgentAdapter, TaskRequest


class DoubaoAdapter(AgentAdapter):
    id = "doubao"
    display_name = "Doubao"
    description = "字节豆包 CLI; 多模态识图与中文对话"
    command = ("doubao", "doubao-cli")
    verify = "doubao"
    # 打分权重: gantong (中文创意/识图) 与 chat 兼顾
    weights = {"chat": 4, "collaboration": 3, "lingma": 3, "gantong": 5, "boundless": 3}

    async def build_command(self, task: TaskRequest) -> list:
        cmd = os.environ.get("TUAN_DOUBAO_CMD") or "doubao"
        return [cmd, "-p", task.prompt]
