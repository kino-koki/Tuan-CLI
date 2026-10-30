"""tuan project —— Project 层: 项目级记忆/配置/工作区隔离。

每个工作目录一个独立 `.tuan/` (config.yaml/goal.json/memory.db/sessions.json/snapshots/):

    tuan project init [--force]    在当前目录初始化 .tuan 项目结构 (幂等)
    tuan project info               显示当前项目信息
    tuan project list               列出已知项目

与 :mod:`tuan_cli.core.project_layer` 同一实现; 本模块轻量, 不导入 app 链。
"""

from __future__ import annotations
from ..paths import default_workspace

import os
from typing import Any

from ..config import Config
from ..ui.plain_console import console


def cmd_project(args: Any) -> int:
    """Project 层: 项目级记忆/配置/工作区隔离。"""
    from ..core.project_layer import ProjectLayer

    workspace = getattr(args, "workspace", None) or default_workspace()
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))
    layer = ProjectLayer(workspace, config)
    sub = getattr(args, "project_cmd", None) or "info"

    if sub == "init":
        info = layer.init(force=bool(getattr(args, "force", False)))
        console.print(f"已初始化项目: {info.project_id} @ {info.path}")
        console.print(f"  .tuan 结构: config.yaml / goal.json / memory.db / "
                      f"sessions.json / snapshots / subagents / worktrees")
        return 0

    if sub == "info":
        info = layer.info()
        console.print(f"项目 ID: {info.project_id}")
        console.print(f"路径:    {info.path}")
        console.print(f"会话数:  {info.session_count}")
        console.print(f"记忆数:  {info.memory_count}")
        if info.goal:
            console.print(f"目标:    {info.goal}")
        if not info.initialized:
            console.print("提示: 尚未初始化, 用 `tuan project init` 初始化。")
        return 0

    if sub == "list":
        rows = layer.list_projects()
        if not rows:
            console.print("(尚未登记任何项目; 用 `tuan project init` 初始化第一个)")
            return 0
        console.print(f"已知项目 {len(rows)} 个:")
        for r in rows:
            console.print(f"  {r.get('project_id','?'):<24} {r.get('path','?')}")
        return 0

    console.print("用法:")
    console.print("  tuan project init [--force]")
    console.print("  tuan project info")
    console.print("  tuan project list")
    return 2


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_project", ".cmd_project")
