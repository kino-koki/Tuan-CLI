"""qxt worktree —— Worktree 层 (git worktree 并行实验)。

用法:
  qxt worktree create <name>    创建 .qxt/worktrees/<name> (新分支)
  qxt worktree list             列出所有 worktree
  qxt worktree remove <name>    删除 worktree
  qxt worktree switch <name>    打印 worktree 路径 (提示如何切换)
"""

from __future__ import annotations

import os
from typing import Any

from ..core.worktree_layer import WorktreeError, WorktreeLayer
from ._ui_singleton import ui


def cmd_worktree(args) -> int:
    sub = getattr(args, "worktree_cmd", None) or "list"
    workspace = getattr(args, "workspace", None) or os.getcwd()
    layer = WorktreeLayer(workspace)

    try:
        if sub == "create":
            name = getattr(args, "name", "") or ""
            if not name:
                ui.error("用法: qxt worktree create <name>")
                return 1
            info = layer.create(name)
            ui.success(f"已创建 worktree: {info.name} → {info.path} (分支 {info.branch})")
            ui.info("  在该目录里实验, 满意后 git merge 回主分支; 不满意 qxt worktree remove "
                    + name)
            return 0

        if sub == "remove":
            name = getattr(args, "name", "") or ""
            if not name:
                ui.error("用法: qxt worktree remove <name>")
                return 1
            path = layer.remove(name)
            ui.success(f"已删除 worktree: {path}")
            return 0

        if sub == "switch":
            name = getattr(args, "name", "") or ""
            if not name:
                ui.error("用法: qxt worktree switch <name>")
                return 1
            path = layer.switch(name)
            ui.success(f"worktree 路径: {path}")
            ui.info("  交互式会话中可在此输入目录后继续; 或终端: cd " + path)
            return 0

        # list (默认)
        items = layer.list()
        if not items:
            ui.info("(不是 git 仓库, 或没有 worktree; 先 git init)")
            return 0
        ui.info(f"worktree {len(items)} 个:")
        for it in items:
            ui.info(f"  {it.name:<16} {it.head:<9} {it.branch:<20} {it.path}")
        return 0
    except WorktreeError as exc:
        ui.error(str(exc))
        return 1
