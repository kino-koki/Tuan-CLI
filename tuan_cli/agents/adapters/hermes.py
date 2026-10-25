"""hermes 适配器。

调用方式: `hermes run "<prompt>"` (通用本地代理; 具体子命令以用户机器实际安装为准)。
输出: 文本流 (stdout)。

注: hermes 未公开标准化 CLI 接口, 本适配器按通用约定调用;
如用户机器上的 hermes 命令不同, 可通过环境变量 TUAN_HERMES_CMD 覆盖。
"""
from __future__ import annotations

import os

from ..base import AgentAdapter, TaskRequest


class HermesAdapter(AgentAdapter):
    id = "hermes"
    display_name = "Hermes"
    description = "本地通用代理; 任务执行与编排"
    command = ("hermes",)
    # 打分权重: gantong (感通, 创意工坊) 模式最契合; 通用任务也可用
    weights = {"chat": 3, "collaboration": 2, "lingma": 2, "gantong": 5, "boundless": 3}

    async def build_command(self, task: TaskRequest) -> list:
        # 允许用户通过环境变量覆盖命令名 (如 hermes-agent / my-hermes)
        cmd = os.environ.get("TUAN_HERMES_CMD") or "hermes"
        return [cmd, "run", task.prompt]
