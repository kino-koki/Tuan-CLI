"""hermes 适配器。

调用方式: `hermes chat -q "<prompt>"` (Hermes Agent 的单次查询/非交互模式)。
输出: 文本流 (stdout)。

实测口径 (hermes v0.17.0): 顶层 `-z PROMPT` 与 `hermes chat -q QUERY` 等价,
取后者——子命令形式语义最明确 ("Single query (non-interactive mode)")。
如用户机器上的 hermes 命令名不同, 可通过环境变量 TUAN_HERMES_CMD 覆盖;
需要完整绕过工具审批时可追加 --yolo (本适配器不加, 交由调用方策略)。
"""
from __future__ import annotations

import os

from ..base import AgentAdapter, TaskRequest


class HermesAdapter(AgentAdapter):
    id = "hermes"
    display_name = "Hermes"
    description = "本地通用代理; 任务执行与编排"
    command = ("hermes",)
    verify = "hermes"
    # 打分权重: gantong (感通, 创意工坊) 模式最契合; 通用任务也可用
    weights = {"chat": 3, "collaboration": 2, "lingma": 2, "gantong": 5, "boundless": 3}

    async def build_command(self, task: TaskRequest) -> list:
        # 允许用户通过环境变量覆盖命令名 (如 hermes-agent / my-hermes)
        cmd = os.environ.get("TUAN_HERMES_CMD") or "hermes"
        return [cmd, "chat", "-q", task.prompt]
