"""技能插件 —— 注册技能管理器服务。"""

from __future__ import annotations

from pathlib import Path

from ..core.kernel import Kernel, Plugin
from .manager import SkillManager


class SkillPlugin(Plugin):
    name = "skills"
    provides = ["skill_manager"]
    requires = ["config", "memory_store"]

    def activate(self, kernel: Kernel) -> None:
        import os

        config = kernel.require("config")
        if not config.get("skills.enabled", True):
            # 即使关闭技能注入, 也提供 manager 保证工具可用
            pass
        # 项目级技能目录: 以当前工作目录为 workspace, 读取 .qxt/skills 与 .agents/skills
        workspace = Path(os.getcwd())
        manager = SkillManager(
            config.home,
            memory_store=kernel.require("memory_store"),
            workspace=workspace,
            config=config,
        )
        kernel.provide("skill_manager", manager, owner=self.name)
