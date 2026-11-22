"""审计归档只读查询工具 —— 把内核事件归档接入 Agent 工具面。

此前 auditstore 只有 CLI 入口 (cmd_auditstore.py): stats/recent/query。
Agent 侧没有对应工具, 模型无法回答「刚才内核到底发生了什么」。

本插件提供只读的 ``audit_query`` 工具, 直接复用 tuan_cli/audit/store.py
的 AuditStore 只读方法 (stats/recent/query), 与 CLI 同一条真实链路:

- op=stats   总量/类型分布/时间跨度
- op=recent  最近 N 条事件 (可按 type 过滤)
- op=query   按 type/关键词/时间窗过滤

安全边界: 纯只读 —— 未初始化 (无 audit.log) 时不构造 AuditStore,
避免其 __init__ 的目录创建副作用; 不调用 log() 写盘。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

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


def _open_store(ctx: ToolContext) -> Any:
    """打开 AuditStore; 未初始化 (无 audit.log) 时返回 None。

    与 cmd_auditstore._open_store 同口径: 仅当归档文件存在才构造,
    保证纯只读 (不触发 mkdir)。
    """
    home = _home(ctx)
    adir = home / "audit"
    has_log = (adir / "audit.log").exists() or any(
        (adir / f"audit.log.{i}").exists() for i in range(1, 6))
    if not has_log:
        return None
    from ..audit.store import AuditStore
    return AuditStore(home=home)


def _fmt_ts(ts: Any) -> str:
    try:
        tsf = float(ts or 0)
    except (TypeError, ValueError):
        return str(ts or "-")
    if not tsf:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(tsf))


def _ev_line(ev: Any) -> str:
    """把 AuditEvent 渲染成一行 (payload 截断, 模型可读)。"""
    seq = getattr(ev, "seq", 0)
    etype = getattr(ev, "type", "?") or "?"
    ts = _fmt_ts(getattr(ev, "ts", 0.0))
    line = f"#{seq:<6} [{etype:<24}] {ts}"
    payload = getattr(ev, "payload", None)
    if payload:
        try:
            text = payload if isinstance(payload, str) else json.dumps(
                payload, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 - 渲染失败不影响事件行
            text = str(payload)
        line += f"\n          {text[:160]}"
    return line


def _audit_handler(ctx: ToolContext, op: str = "stats", **kw: Any) -> str:
    try:
        store = _open_store(ctx)
    except Exception as exc:  # noqa: BLE001 - 读档失败要反馈而非炸循环
        log.debug("audit_query 打开归档失败: %s", exc)
        return f"[audit] 审计归档读取失败: {exc}"

    if store is None:
        return ("内核审计归档未初始化 (尚无 audit/audit.log; 内核事件发生后"
                "自动建立)。可用 op: stats / recent / query。")

    if op == "stats":
        s = store.stats()
        by_type: dict = s.get("by_type", {}) or {}
        lines = [
            f"内核审计归档统计 ({_home(ctx) / 'audit' / 'audit.log'}):",
            f"  总事件 {s.get('total', 0)} · 类型 {len(by_type)} 种 · "
            f"内存缓冲 {s.get('buffered', 0)} · enabled {s.get('enabled', True)}",
            f"  最早 {s.get('oldest_iso', '-')} · 最近 {s.get('newest_iso', '-')}",
        ]
        if by_type:
            lines.append("  按类型分布 (Top 10):")
            for t, c in sorted(by_type.items(), key=lambda kv: kv[1],
                               reverse=True)[:10]:
                lines.append(f"    {t:<28} {c}")
        return "\n".join(lines)

    if op == "recent":
        try:
            limit = int(kw.get("limit", 20) or 20)
        except (TypeError, ValueError):
            return "[audit] limit 非法 (需要整数)"
        limit = max(1, min(limit, 200))
        type_f = str(kw.get("type", "") or "").strip() or None
        evs = store.recent(n=limit, types=(type_f,) if type_f else ())
        if not evs:
            return "最近没有审计事件" + (f" (type={type_f})" if type_f else "") + "。"
        head = f"最近审计事件 {len(evs)} 条" + (f" (type={type_f})" if type_f else "") + ":"
        return head + "\n" + "\n".join(_ev_line(e) for e in evs)

    if op == "query":
        from ..audit.store import AuditQuery
        type_f = str(kw.get("type", "") or "").strip() or None
        keyword = str(kw.get("keyword", "") or "")
        since_h = kw.get("since_hours")
        until_h = kw.get("until_hours")
        try:
            limit = max(1, min(int(kw.get("limit", 50) or 50), 500))
        except (TypeError, ValueError):
            return "[audit] limit 非法 (需要整数)"
        now = time.time()
        try:
            since = (now - float(since_h) * 3600.0) if since_h else None
            until = (now - float(until_h) * 3600.0) if until_h else None
        except (TypeError, ValueError):
            return "[audit] since_hours/until_hours 非法 (需要数字, 单位小时)"
        q = AuditQuery(
            types=(type_f,) if type_f else (),
            since=since, until=until, keyword=keyword, limit=limit,
        )
        evs = store.query(q)
        if not evs:
            return "查询无结果 (可放宽 type/keyword/时间窗)。"
        return f"审计查询结果 {len(evs)} 条:\n" + "\n".join(_ev_line(e) for e in evs)

    return f"[audit] 未知 op: {op!r}。可用: stats / recent / query"


class AuditToolPlugin(Plugin):
    """把内核审计归档接入 Agent 工具面 (此前仅 cmd_auditstore.py 可用)。"""

    name = "tools.audit"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config is not None and not config.get("tools.audit.enabled", True):
            return
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="audit_query",
            description=(
                "只读查询内核审计归档 (audit/audit.log, 全量内核事件)。"
                "op=stats 统计 (总量/类型分布/时间跨度); op=recent 最近 N 条 "
                "(可按 type 过滤); op=query 按 type/keyword/since_hours/"
                "until_hours 过滤。纯只读, 不写盘。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "op": {"type": "string",
                            "description": "动作: stats / recent / query"},
                    "type": string_prop("事件类型过滤, 如 tool.executed / model.call"),
                    "keyword": string_prop("payload 关键词 (op=query)"),
                    "since_hours": {"type": "number",
                                     "description": "仅看 N 小时前至今 (op=query)"},
                    "until_hours": {"type": "number",
                                     "description": "仅看截止 N 小时前 (op=query)"},
                    "limit": {"type": "integer",
                               "description": "返回条数上限 (recent 默认 20, query 默认 50)"},
                },
                "required": ["op"],
            },
            handler=_audit_handler,
            group="tools",
        ))
