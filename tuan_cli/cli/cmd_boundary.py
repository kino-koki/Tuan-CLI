"""四层边界自动决策查询 (第 73 个独特功能: 边界可预判)。

差异化价值: Claude Code 的边界是**执行期黑箱** —— 你发一个重任务, 它可能
直接在主会话跑、也可能悄悄派给子代理, 你不知道为什么。Tuan-CLI 的四层边界
(Project / Subagent / Worktree / Chat) 有纯函数决策器, 本命令把决策暴露为
**可预先查询**: 对任意任务描述, 回答「会不会被自动隔离子代理」「会不会触发
并行 worktree」「触发的是哪一层、由什么关键词/长度触发、由什么开关控制」,
让用户在执行前就清楚边界行为。

    tuan boundary check "实现登录功能, 同时实现注册功能"   # 边界决策预判
    tuan boundary check "写一个很长的架构文档..." --json   # 机器可读
    tuan boundary status                                  # 四层边界开关总览

边界决策 (core.boundary_auto):
- Subagent 层: should_isolate_task() —— 长任务(>500字符)或含并行意图关键词
  (同时/并行/分别/独立/另外) → 建议隔离子代理;
- Worktree 层: detect_parallel_intent() —— 含「方案A/方案B/对比/试一下另一种」
  等并行实验意图 → 建议自动开 experiment-N worktree;
- Project 层: ensure_project_context() —— 会话启动自动确保 .tuan/ 存在;
- Chat 层: ChatHandoff.auto_handoff_if_needed() —— 超阈值自动交接。
"""

from __future__ import annotations

import sys
from typing import Any

from ..config import Config
from ..ui.plain_console import console


def cmd_boundary(args: Any) -> int:
    """四层边界决策查询入口 (第 73 个独特功能)。"""
    sub = getattr(args, "boundary_cmd", None) or "check"

    if sub == "check":
        return _boundary_check(args)
    if sub == "status":
        return _boundary_status(args)

    console.print("[red]未知子命令:[/red] %s (可用: check / status)" % sub)
    return 1


def _boundary_check(args: Any) -> int:
    """对任务描述做边界决策预判 (只读纯函数, 无副作用)。"""
    task = getattr(args, "task", "") or ""
    if not task.strip():
        console.print("[red]用法: tuan boundary check <任务描述> [--json][/red]")
        return 1
    json_mode = bool(getattr(args, "json", False))

    from ..core.boundary_auto import detect_parallel_intent, should_isolate_task
    from ..core.chat_handoff import ChatHandoff

    config = Config()
    isolate = should_isolate_task(task)
    worktree = detect_parallel_intent(task)
    # Chat 层: 超阈值自动交接阈值 (配置读不到用默认)
    chat_threshold = config.get("chat.handoff_threshold", 3) or 3

    result = {
        "task": task,
        "isolate_subagent": bool(isolate),
        "parallel_worktree": worktree,          # None 或 "experiment-N"
        "chat_handoff_threshold": int(chat_threshold),
        "isolate_reason": (_isolate_reason(task)),
        "worktree_reason": (_worktree_reason(task)),
    }

    if json_mode:
        sys.stdout.write(__import__("json").dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 边界决策预判 ===[/bold]\n")
    console.print(f"  [dim]任务: {task[:80]}{'…' if len(task) > 80 else ''}[/dim]\n")

    # Subagent 层
    if isolate:
        console.print(f"  [yellow]Subagent[/yellow]: [bold]建议隔离子代理[/bold]")
        console.print(f"      [dim]→ {result['isolate_reason']}[/dim]")
        cfg = config.get("subagent.auto_isolate", True)
        console.print(f"      [dim]开关: subagent.auto_isolate={cfg} "
                      f"({'生效' if cfg else '已关(不隔离)'})[/dim]")
    else:
        console.print(f"  [green]Subagent[/green]: 不隔离 (主会话直接执行)")

    # Worktree 层
    if worktree:
        console.print(f"  [yellow]Worktree[/yellow]: [bold]建议自动开 {worktree}[/bold]")
        console.print(f"      [dim]→ {result['worktree_reason']}[/dim]")
        cfg = config.get("worktree.auto_create", True)
        console.print(f"      [dim]开关: worktree.auto_create={cfg} "
                      f"({'生效' if cfg else '已关(不开)'})[/dim]")
    else:
        console.print(f"  [green]Worktree[/green]: 不触发并行实验")

    # Chat 层
    console.print(f"  [dim]Chat[/dim]: 超阈值自动交接阈值 = {chat_threshold}")

    console.print(f"\n[dim]注: 本命令是纯决策预判 (不执行任务), 实际执行在 "
                  f"tuan dev / tuan run 时按同一决策函数触发[/dim]")
    return 0


def _boundary_status(args: Any) -> int:
    """四层边界开关总览 (配置面: 用户确认哪些自动边界在生效)。"""
    config = Config()
    cfg = {
        "project.auto_init": config.get("project.auto_init", True),
        "subagent.auto_isolate": config.get("subagent.auto_isolate", True),
        "worktree.auto_create": config.get("worktree.auto_create", True),
        "chat.handoff_threshold": config.get("chat.handoff_threshold", 3),
    }
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        sys.stdout.write(__import__("json").dumps(cfg, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 四层边界开关 ===[/bold]\n")
    for key, val in cfg.items():
        if isinstance(val, bool):
            mark = "[green]✓ 开[/green]" if val else "[red]✗ 关[/red]"
        else:
            mark = str(val)
        console.print(f"  [cyan]{key}[/cyan]  {mark}")
    console.print("\n[dim]边界层: Project(会话启动) / Subagent(重任务隔离) / "
                  "Worktree(并行实验) / Chat(超阈值交接)[/dim]")
    return 0


def _isolate_reason(task: str) -> str:
    """说明 Subagent 隔离触发原因 (与 should_isolate_task 同口径)。"""
    text = task or ""
    if len(text) > 500:
        return f"任务长度 {len(text)} 字符 > 500 (长任务建议隔离)"
    for kw in ("同时", "并行", "分别", "独立", "另外"):
        if kw in text:
            return f"含并行意图关键词「{kw}」"
    return "未触发"


def _worktree_reason(task: str) -> str:
    """说明 Worktree 触发原因 (与 detect_parallel_intent 同口径)。"""
    norm = (task or "").lower().replace(" ", "")
    for pat in ("方案a", "方案b", "对比", "比较", "试一下另一种", "试另一种",
                "两种方式", "两种方法", "另一种思路", "另一个方案", "两个方案",
                "另一种"):
        if pat in norm:
            return f"含并行实验意图「{pat}」"
    return "未触发"
