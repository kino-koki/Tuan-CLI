"""qxt project —— Project 层 (项目级持久化上下文 / 工作区隔离)。

用法:
  qxt project init        在当前目录初始化 .qxt 项目结构 (幂等, 自动识别已有项目)
  qxt project info        显示当前项目信息
  qxt project list        列出已知项目 (~/.qingxiaotuan/projects.json)
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from ..core.project_layer import ProjectLayer
from ._ui_singleton import ui


def cmd_project(args) -> int:
    sub = getattr(args, "project_cmd", None) or "info"
    workspace = getattr(args, "workspace", None) or os.getcwd()
    layer = ProjectLayer(workspace)

    if sub == "init":
        info = layer.init(force=bool(getattr(args, "force", False)))
        ui.success(f"项目已就绪: {info.project_id}  ({info.path})")
        ui.info(f"  记忆库: .qxt/memory.db · 快照: .qxt/snapshots/ · QXT.md 模板已生成")
        return 0

    if sub == "list":
        items = layer.list_projects()
        if not items:
            ui.info("(还没有任何已登记项目; 在某个目录跑 `qxt project init`)")
            return 0
        ui.info(f"已知项目 {len(items)} 个:")
        for p in items:
            mark = "✓" if p.get("exists") else "✗(已移动)"
            ts = datetime.fromtimestamp(p.get("created_at", 0)).strftime("%Y-%m-%d")
            ui.info(f"  {mark} {p.get('project_id','?')[:18]:<18} {ts}  {p.get('path','')}")
        return 0

    # info (默认)
    info = layer.info()
    if not info.initialized:
        ui.info(f"当前目录还不是 qxt 项目: {layer.workspace}")
        ui.info("  运行 `qxt project init` 初始化 (独立记忆/配置/快照)")
        return 0
    ui.info(f"  项目 ID:   {info.project_id}")
    ui.info(f"  路径:      {info.path}")
    ui.info(f"  创建时间:  {datetime.fromtimestamp(info.created_at).strftime('%Y-%m-%d %H:%M')}")
    ui.info(f"  会话数:    {info.session_count}")
    ui.info(f"  记忆条数:  {info.memory_count}")
    ui.info(f"  隔离模式:  {'开启' if layer.isolation_enabled else '关闭'} "
            f"(project.isolation_enabled)")
    if info.goal:
        ui.info(f"  当前目标:  {info.goal[:80]}")
    return 0
