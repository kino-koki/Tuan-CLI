"""四层边界 + Rewind 的斜杠命令处理器。

- /rewind [list|to <N>]      会话时间线回溯
- /handoff                   会话交接 (Chat 层)
- /worktree create|list|remove|switch   (Worktree 层)
- /subagent run <任务> | status         (Subagent 层增强)

从 cmd_slash.py 的 _handle_slash 分发进来, 保持斜杠命令表集中登记。
"""

from __future__ import annotations

import os
from typing import Any

from ..core.chat_handoff import ChatHandoff
from ..core.rewind import RewindError, RewindManager
from ..core.worktree_layer import WorktreeError, WorktreeLayer
from ._ui_singleton import ui


# ------------------------------------------------------------ /rewind

def _cmd_rewind(agent, arg: str, workspace: str) -> None:
    """/rewind [list] [to <N>] —— 回退会话到之前的快照。"""
    mgr = RewindManager(workspace)
    parts = arg.strip().split()
    sub = parts[0].lower() if parts else ""

    if sub == "list":
        snaps = mgr.list_snapshots()
        if not snaps:
            ui.info("(没有可回退的快照)")
            return
        ui.info(f"快照 {len(snaps)} 个:")
        for s in snaps:
            ui.info(f"  [{s.index}] {__import__('time').strftime('%Y-%m-%d %H:%M:%S', __import__('time').localtime(s.ts))}"
                    f" · {s.reason} · {s.message_count} 条消息")
        ui.info("  /rewind           回退一步 (到上一个快照)")
        ui.info("  /rewind to <N>    回退到序号 N")
        return

    if sub == "to":
        try:
            idx = int(parts[1])
        except (IndexError, ValueError):
            ui.error("用法: /rewind to <序号> (序号见 /rewind list)")
            return
        try:
            n = mgr.restore(agent.messages, idx)
            ui.success(f"已回退到快照 [{idx}], 会话恢复为 {n} 条消息 (其后对话已丢弃)")
        except RewindError as exc:
            ui.error(str(exc))
        return

    # 无参: 回退一步
    try:
        n = mgr.restore_previous(agent.messages)
        ui.success(f"已 Rewind: 会话恢复为 {n} 条消息 (/rewind list 查看可用快照)")
    except RewindError as exc:
        ui.error(str(exc))


# ------------------------------------------------------------ /handoff

def _cmd_handoff(agent, config, workspace: str) -> None:
    """/handoff —— 手动触发会话交接。"""
    sid = getattr(getattr(agent, "session", None), "session_id", "") or ""
    handoff = ChatHandoff(workspace, config)
    # 注入项目 ID (若 Project 层已初始化)
    from ..core.project_layer import ProjectLayer
    pid = ProjectLayer(workspace).info().project_id
    report = handoff.handoff(sid, list(agent.messages), project_id=pid)
    ui.success("会话交接完成:")
    ui.info(f"  旧会话 (已归档): {report.old_session_id}")
    ui.info(f"  新会话 ID:       {report.new_session_id}")
    ui.info("  交接摘要:")
    for line in report.summary.splitlines():
        ui.info("    " + line)
    ui.info("  提示: 退出后 `qxt session resume " + report.new_session_id + "` 即可带着摘要继续。")


# ------------------------------------------------------------ /worktree

def _cmd_worktree(agent, arg: str, workspace: str) -> None:
    """/worktree create|list|remove|switch —— git worktree 并行实验。"""
    layer = WorktreeLayer(workspace)
    parts = arg.strip().split()
    sub = parts[0].lower() if parts else "list"
    name = parts[1] if len(parts) > 1 else ""
    try:
        if sub == "create":
            if not name:
                ui.error("用法: /worktree create <name>")
                return
            info = layer.create(name)
            ui.success(f"已创建 worktree: {info.path} (分支 {info.branch})")
        elif sub == "remove":
            if not name:
                ui.error("用法: /worktree remove <name>")
                return
            ui.success(f"已删除: {layer.remove(name)}")
        elif sub == "switch":
            if not name:
                ui.error("用法: /worktree switch <name>")
                return
            ui.success(f"worktree 路径: {layer.switch(name)}")
        else:  # list
            items = layer.list()
            if not items:
                ui.info("(不是 git 仓库或没有 worktree; 先 git init)")
                return
            for it in items:
                ui.info(f"  {it.name:<16} {it.head:<9} {it.branch:<18} {it.path}")
    except WorktreeError as exc:
        ui.error(str(exc))


# ------------------------------------------------------------ /subagent run|status

def _cmd_subagent_enhanced(agent, arg: str) -> None:
    """/subagent run <任务> | status —— Subagent 层: 派发 / 查看。"""
    from ..tools.subagent_tool import _run_subagent
    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""

    if sub == "status":
        # 展示最近派发的子任务状态 (由 SubAgentPool 追踪)
        pool = getattr(agent, "_subagent_pool", None)
        if pool is None:
            ui.info("(本会话尚未派发过子任务; 用 /subagent run <任务> 派出)")
            return
        rows = pool.task_status()
        if not rows:
            ui.info("(暂无子任务记录)")
            return
        ui.info(f"子任务 {len(rows)} 个:")
        for r in rows:
            ui.info(f"  [{r.get('status','?'):<8}] {r.get('task_id','?'):<10} "
                    f"{r.get('elapsed','')}s  {r.get('prompt','')[:50]}")
        return

    if sub == "run":
        task = parts[1].strip() if len(parts) > 1 else ""
        if not task:
            ui.error("用法: /subagent run <任务描述>")
            return
        ui.info("[子代理] 已派出, 独立工作目录 + 独立上下文执行中…")
        ui.answer_md(_run_subagent(agent.ctx, task))
        return

    # 兼容旧用法: /subagent <任务>
    if not arg:
        ui.info("用法:")
        ui.info("  /subagent run <任务描述>   派发隔离子代理 (独立工作目录)")
        ui.info("  /subagent status            查看子任务状态")
        return
    ui.info("[子代理] 已派出, 独立上下文执行中…")
    ui.answer_md(_run_subagent(agent.ctx, arg.strip()))
