"""tuan worktree —— Worktree 层: git worktree 并行实验。

基于 ``git worktree`` 在 ``.tuan/worktrees/`` 下开并行实验分支:

    tuan worktree create <name>     创建 worktree (.tuan/worktrees/<name>, 同名分支)
    tuan worktree list              列出所有 worktree
    tuan worktree remove <name>     删除 worktree
    tuan worktree switch <name>     显示 worktree 路径

与 :mod:`tuan_cli.core.worktree_layer` 同一实现; 本模块轻量, 不导入 app 链。
"""

from __future__ import annotations

import os

from ..ui.plain_console import console


def cmd_worktree(args) -> int:
    """Worktree 层: git worktree 并行实验。"""
    from ..core.worktree_layer import WorktreeError, WorktreeLayer

    workspace = getattr(args, "workspace", None) or os.getcwd()
    layer = WorktreeLayer(workspace)
    sub = getattr(args, "worktree_cmd", None) or "list"
    name = getattr(args, "name", "") or ""

    try:
        if sub == "create":
            if not name:
                console.print("用法: tuan worktree create <name>")
                return 1
            info = layer.create(name)
            console.print(f"已创建 worktree: {info.path} (分支 {info.branch})")
            return 0
        if sub == "remove":
            if not name:
                console.print("用法: tuan worktree remove <name>")
                return 1
            console.print(f"已删除: {layer.remove(name)}")
            return 0
        if sub == "switch":
            if not name:
                console.print("用法: tuan worktree switch <name>")
                return 1
            console.print(f"worktree 路径: {layer.switch(name)}")
            return 0
        # list
        items = layer.list()
        if not items:
            console.print("(不是 git 仓库或没有 worktree; 先 git init)")
            return 0
        for it in items:
            console.print(f"  {it.name:<16} {it.head:<9} {it.branch:<18} {it.path}")
        return 0
    except WorktreeError as exc:
        console.print(f"[worktree] {exc}")
        return 1


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_worktree", ".cmd_worktree")
