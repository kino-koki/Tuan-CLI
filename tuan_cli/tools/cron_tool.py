"""Cron 定时任务工具 —— 把 tuan cron 子系统能力接入 Agent 工具面。

此前 cron 只有 CLI 入口 (cmd_cron.py): add/list/remove/enable/disable/
edit/logs/start/stop/status/run/tick。Agent 侧没有任何对应工具, 模型
无法替用户管理或触发定时任务。

本插件把 CronStore (tuan_cli/cron/store.py) 与 run_due_jobs
(tuan_cli/cron/runner.py) 接成单个 ``cron`` 工具, 用 ``op`` 参数区分动作:

- add      新增任务 (schedule=5 字段 cron 表达式, 或 interval_minutes 间隔)
- list     列出全部任务
- remove   按 id 删除
- toggle   启用/停用
- run_due  执行全部到期任务 (与 `tuan cron tick` 同一条真实链路;
           无人值守执行, 危险操作按 CronRunner 的安全默认拒绝)
- status   任务统计 + 存储位置

安全边界: 本工具不提供 start/stop 守护进程能力 (进程生命周期不归
Agent 管); run_due 复用 CronRunner 的无人值守安全默认 (confirm 恒 False)。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

import logging
log = logging.getLogger(__name__)


def _home(ctx: ToolContext) -> Path:
    """解析 tuan home 目录 (优先 config.home, 回退 workspace/.tuan)。"""
    config = ctx.kernel.get("config") if ctx.kernel is not None else None
    home = getattr(config, "home", None) if config is not None else None
    if home:
        return Path(home)
    return Path(ctx.workspace) / ".tuan"


def _config(ctx: ToolContext) -> Any:
    return ctx.kernel.get("config") if ctx.kernel is not None else None


def _fmt_age(ts: float) -> str:
    if not ts:
        return "从未运行"
    delta = max(0.0, time.time() - ts)
    if delta < 60:
        return f"{int(delta)} 秒前"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    return f"{int(delta // 86400)} 天前"


def _fmt_job(j: dict) -> str:
    sched = j.get("schedule")
    when = f"cron `{sched}`" if sched else f"每 {j.get('interval_minutes', '?')} 分钟"
    state = "启用" if j.get("enabled") else "停用"
    return (f"[{j.get('id', '?')}] {j.get('name', '?')}  ({when}, {state}, "
            f"上次: {_fmt_age(float(j.get('last_run', 0) or 0))})")


def _cron_handler(ctx: ToolContext, op: str = "list", **kw: Any) -> str:
    from ..cron.store import CronStore
    store = CronStore(_home(ctx))

    if op == "add":
        name = str(kw.get("name", "") or "").strip()
        prompt = str(kw.get("prompt", "") or "").strip()
        schedule = str(kw.get("schedule", "") or "").strip() or None
        interval = kw.get("interval_minutes", 60)
        if not name:
            return "[cron] add 需要 name 参数"
        if not prompt:
            return "[cron] add 需要 prompt 参数 (任务执行时下发给 Agent 的指令)"
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            return f"[cron] interval_minutes 非法: {interval!r} (需要整数分钟)"
        if schedule is None and interval <= 0:
            return "[cron] interval_minutes 必须为正整数 (或改用 schedule 传 cron 表达式)"
        try:
            job = store.add(name=name, prompt=prompt,
                            interval_minutes=interval, schedule=schedule)
        except Exception as exc:  # CronParseError 等: 校验失败不落盘
            return f"[cron] 新增失败: {exc}"
        sched_txt = job.get("schedule") or f"每 {job.get('interval_minutes')} 分钟"
        return (f"定时任务已创建: [{job['id']}] {name} ({sched_txt})\n"
                f"提示: 到期后由 cron 调度执行; `tuan cron start` 启动守护, "
                f"`tuan cron tick` 手动触发一轮。")

    if op == "list":
        jobs = store.list()
        if not jobs:
            return "当前没有定时任务。可用 op=add 创建 (需 name + prompt, 可选 schedule 或 interval_minutes)。"
        lines = [_fmt_job(j) for j in jobs]
        return f"定时任务 {len(jobs)} 个:\n" + "\n".join(lines)

    if op == "remove":
        job_id = str(kw.get("job_id", "") or "").strip()
        if not job_id:
            return "[cron] remove 需要 job_id 参数"
        return ("任务已删除: " + job_id) if store.remove(job_id) else \
            f"[cron] 未找到任务 {job_id} (用 op=list 查看现有 id)"

    if op == "toggle":
        job_id = str(kw.get("job_id", "") or "").strip()
        enabled = kw.get("enabled")
        if not job_id:
            return "[cron] toggle 需要 job_id 参数"
        if enabled is None:
            cur = store.get(job_id)
            if cur is None:
                return f"[cron] 未找到任务 {job_id}"
            enabled = not cur.get("enabled", True)
        ok = store.set_enabled(job_id, bool(enabled))
        if not ok:
            return f"[cron] 未找到任务 {job_id}"
        return f"任务 {job_id} 已{'启用' if enabled else '停用'}"

    if op == "run_due":
        kernel = ctx.kernel
        config = _config(ctx)
        if kernel is None or config is None:
            return "[cron] run_due 需要完整内核 (缺少 kernel/config), 请改用 `tuan cron tick`"
        from ..cron.runner import run_due_jobs
        try:
            count = run_due_jobs(kernel, config, ctx.workspace, _home(ctx),
                                 stream=False)
        except Exception as exc:  # noqa: BLE001 - 执行失败要反馈给模型而不是炸循环
            log.debug("cron run_due 失败: %s", exc)
            return f"[cron] 到期任务执行失败: {exc}"
        return (f"本轮执行了 {count} 个到期任务。" if count
                else "当前没有到期的任务。")

    if op == "status":
        jobs = store.list()
        enabled = [j for j in jobs if j.get("enabled")]
        due = store.due()
        return (f"定时任务: 共 {len(jobs)} 个, 启用 {len(enabled)} 个, "
                f"当前到期 {len(due)} 个。存储: {_home(ctx) / 'cron' / 'jobs.json'}")

    return (f"[cron] 未知 op: {op!r}。可用: add / list / remove / toggle / "
            "run_due / status")


class CronToolPlugin(Plugin):
    """把 cron 子系统接入 Agent 工具面 (此前仅 CLI 可用)。"""

    name = "tools.cron"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config is not None and not config.get("tools.cron.enabled", True):
            return
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="cron",
            description=(
                "管理并触发定时任务 (tuan cron)。"
                "op=add 新增 (name + prompt, 可选 schedule=『0 9 * * 1-5』式 "
                "cron 表达式或 interval_minutes 间隔); op=list 列出; "
                "op=remove 删除; op=toggle 启停; op=run_due 立即执行全部到期任务 "
                "(无人值守, 危险操作会被安全默认拒绝); op=status 查看统计。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "op": {"type": "string",
                           "description": "动作: add/list/remove/toggle/run_due/status"},
                    "name": string_prop("任务名称 (op=add)"),
                    "prompt": string_prop("任务执行时下发给 Agent 的指令 (op=add)"),
                    "schedule": string_prop("5 字段 cron 表达式, 如 '0 9 * * 1-5' (op=add, 可选)"),
                    "interval_minutes": {"type": "integer",
                                          "description": "间隔分钟数 (op=add, 无 schedule 时生效)"},
                    "job_id": string_prop("任务 id (op=remove/toggle)"),
                    "enabled": {"type": "boolean",
                                 "description": "目标状态 (op=toggle, 缺省取反)"},
                },
                "required": ["op"],
            },
            handler=_cron_handler,
            group="tools",
        ))
