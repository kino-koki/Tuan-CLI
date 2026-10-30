"""background_monitor 工具 —— 流式消费后台任务事件 (对标 Claude Code 的 Monitor)。

GAP A4: background.py 已把 `job.start / job.done / job.error / job.cancel /
job.resume / agent.turn` 事件写入**每个后台任务独立的会话流** (SessionStore JSONL)。
本工具以**增量游标** (JSONL 行数) 订阅这些事件:

- 每次调用只返回「自上次游标以来新增的 job.* 事件」+ 当前状态快照;
- 模型在多轮循环里反复调用即可"流式"观察到后台任务的推进 (start → turns →
  done/error/cancel), 替代/补充轮询式 background_status;
- 通过 ctx.heartbeat() 推送进度心跳 (对标 Periodic Progress Heartbeat),
  让 CLI/TUI 能实时渲染后台任务动态。

设计要点:
- read_only=True: 纯观察, 不改任何状态 (Plan 模式放行);
- long_running=True: 主循环把它当作长运行工具, 周期性回调 (而非一次性阻塞);
- 游标存在 ctx 上 (per-session), 由本插件懒初始化, 不写全局状态。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

if TYPE_CHECKING:
    from ..core.background import BackgroundRunner


# 事件词汇: 本工具订阅的后台生命周期事件 (与 event_protocol.AgentEvent 对齐)
_JOB_EVENTS = {"job.start", "job.done", "job.error", "job.cancel", "job.resume", "agent.turn"}

# 生命周期终态事件: 无论 tail 多小都保留 (它们是 Monitor 的关键信号, 不能被轮次噪声挤出)
_LIFECYCLE_EVENTS = {"job.start", "job.done", "job.error", "job.cancel", "job.resume"}


# ------------------------------------------------------------------ 增量游标

def _get_cursor(ctx: ToolContext, job_id: str) -> int:
    """读取该 job 在 ctx 上的增量游标 (JSONL 行数); 缺省为 0 (从头读)。"""
    if ctx._monitor_cursors is None:
        ctx._monitor_cursors = {}
    return int(ctx._monitor_cursors.get(job_id, 0))


def _set_cursor(ctx: ToolContext, job_id: str, offset: int) -> None:
    if ctx._monitor_cursors is None:
        ctx._monitor_cursors = {}
    ctx._monitor_cursors[job_id] = int(offset)


def _read_from_offset(store: Any, offset: int) -> tuple[List[Dict[str, Any]], int]:
    """增量读: 返回 (新增事件记录, 新的行数游标)。

    以「文件总行数」为游标 (append-only JSONL 单调递增)。读取失败返回 ([], offset)。
    """
    try:
        lines = store.file.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001 - 文件被清理/权限问题: 容错返回空
        return [], offset
    total = len(lines)
    out: List[Dict[str, Any]] = []
    for ln in lines[offset:]:
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        out.append(rec)
    return out, total


# ------------------------------------------------------------------ 快照渲染

def _render_event(rec: Dict[str, Any]) -> str:
    """把一条后台事件渲染成一行可读文本。"""
    et = str(rec.get("type", ""))
    ts = rec.get("ts", 0)
    stamp = f"[{float(ts):.0f}]" if ts else ""
    if et == "job.start":
        return f"{stamp} ▶ 启动: {str(rec.get('task', ''))[:80]}"
    if et == "job.done":
        extra = " (达到轮次上限)" if rec.get("exhausted") else ""
        return f"{stamp} ✔ 完成: {rec.get('turns', '?')} 轮{extra}"
    if et == "job.error":
        return f"{stamp} ✘ 失败: {str(rec.get('error', ''))[:120]}"
    if et == "job.cancel":
        return f"{stamp} ⏹ 已取消"
    if et == "job.resume":
        return f"{stamp} ↻ 续作: {str(rec.get('task', ''))[:80]}"
    if et == "agent.turn":
        return f"{stamp}  轮次 {rec.get('turn', '?')}: {str(rec.get('summary', ''))[:100]}"
    return f"{stamp} {et}: {str(rec)[:100]}"


# ------------------------------------------------------------------ 工具 handler

def _monitor_handler(ctx: ToolContext, job_id: Any = "", tail: Any = 20,
                     **_kwargs: Any) -> str:
    """流式消费后台任务事件。

    - 不传 job_id: 列出全部后台任务的概览 + 各自最新事件 (游标推进到最新);
    - 传 job_id: 返回自上次调用以来新增的 job.* 事件 + 当前状态快照。
    """
    runner: Optional[Any] = getattr(ctx, "background_runner", None)
    if runner is None:
        return "当前会话还没有启动过任何后台子代理任务。"

    jid = str(job_id or "").strip()
    jobs = runner.list_jobs()

    # ---- 全量概览模式 (不传 job_id): 每条任务列状态 + 最新事件 ----
    if not jid:
        if not jobs:
            return "没有后台任务。"
        lines = ["后台任务监控 (流式):"]
        for j in jobs:
            d = j.to_dict()
            lines.append(f"- {d['job_id']} [{d['status']}] 轮次 {d['turns']} · "
                         f"{d['elapsed']}s · {(d.get('task') or '')[:50]}")
            # 概览模式也推进游标到最新, 避免后续按 job_id 查询重放旧事件
            events, total = _read_from_offset(j.store, _get_cursor(ctx, j.job_id))
            _set_cursor(ctx, j.job_id, total)
            # 生命周期终态事件始终展示, 轮次噪声按 tail 截断
            shown = [r for r in events
                     if r.get("type") in _LIFECYCLE_EVENTS and r.get("type") in _JOB_EVENTS]
            tail_cap = int(tail) if tail else 20
            shown += [r for r in events
                      if r.get("type") in _JOB_EVENTS and r.get("type") not in _LIFECYCLE_EVENTS][-tail_cap:]
            shown.sort(key=lambda r: float(r.get("ts", 0) or 0))
            for rec in shown:
                lines.append("   " + _render_event(rec))
        return "\n".join(lines)

    # ---- 单任务增量模式 ----
    job = runner.get(jid)
    if job is None:
        return f"[错误] 未找到后台任务: {jid} (可用不带 job_id 的调用列出全部任务)"

    offset = _get_cursor(ctx, jid)
    events, total = _read_from_offset(job.store, offset)
    _set_cursor(ctx, jid, total)

    # 流式进度心跳: 让 CLI/TUI 实时渲染 (对标 Periodic Progress Heartbeat)
    ctx.heartbeat("background_monitor", f"job {jid} [{job.status}] 新增 {len(events)} 事件")

    # 只展示 job.* / agent.turn 事件 (跳过 session.meta / user / assistant / tool_call 噪声)
    job_events = [r for r in events if r.get("type") in _JOB_EVENTS]
    # tail 只截断轮次噪声 (agent.turn); 生命周期终态事件始终保留 (Monitor 关键信号)
    shown = [r for r in job_events if r.get("type") in _LIFECYCLE_EVENTS]
    tail_cap = int(tail) if tail else 20
    shown += [r for r in job_events if r.get("type") not in _LIFECYCLE_EVENTS][-tail_cap:]
    shown.sort(key=lambda r: float(r.get("ts", 0) or 0))
    parts: List[str] = []
    if shown:
        parts.append(f"[{job.status}] {job.task[:100]} 新增事件:")
        for rec in shown:
            parts.append("  " + _render_event(rec))
    else:
        parts.append(f"[{job.status}] {job.task[:100]} (无新事件)")

    # 终态时附带结果/错误摘要 (与 background_status 对齐, 一次调用拿全)
    if job.status == "done":
        parts.append("结果:\n" + (job.result or "(无输出)"))
    elif job.status == "failed":
        parts.append(f"错误: {job.error}")
    usage = job.usage or {}
    if usage:
        toks = (usage.get("prompt_tokens", 0) or 0) + (usage.get("completion_tokens", 0) or 0)
        parts.append(f"用量: {toks} tokens · {job.turns} 轮")
    return "\n".join(parts)


def build_background_monitor_tool() -> Tool:
    return Tool(
        name="background_monitor",
        description=(
            "流式监控后台子代理任务的事件 (对标 Claude Code 的 Monitor)。"
            "每次调用返回自上次调用以来新增的 job.start / job.done / job.error / "
            "job.cancel / agent.turn 事件 + 当前状态快照, 并用增量游标避免重复推送。"
            "不传 job_id 时列出全部后台任务的概览与最新事件; 传 job_id 时增量消费"
            "该任务的专属事件流 (配合 task 工具的 run_in_background 使用, 在多轮循环中"
            "反复调用即可实时观察后台推进)。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "job_id": string_prop("要监控的后台任务 ID; 留空则列出全部"),
                "tail": {"type": "integer", "default": 20,
                         "description": "单次返回的最大事件条数"},
            },
        },
        handler=_monitor_handler,
        dangerous=False,
        group="agent",
        read_only=True,
        long_running=True,
    )


class MonitorToolPlugin(Plugin):
    """后台任务事件流订阅插件: 注册 background_monitor 工具。"""

    name = "tools.monitor"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(build_background_monitor_tool())
