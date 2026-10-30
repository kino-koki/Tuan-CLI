"""斜杠命令 —— Auto Memory 管理域 (/memory)。

拆分自 cmd_slash.py: list/search/add/delete/on/off。
"""

from __future__ import annotations

from typing import Any

from ._ui_singleton import ui
from ..memory.store import MEMORY_KINDS


def _cmd_memory(agent: Any, config: Any, arg: str) -> None:
    """/memory — Auto Memory 管理: list/search/add/delete/on/off + 长期记忆增强。

    子命令:
      /memory list [kind]   列出记忆 (kind=user/feedback/project/reference)
      /memory search <q>    全文搜索
      /memory add <kind> <text>   手动写一条记忆
      /memory delete <id>   按 id 删除
      /memory on|off        开关自动提取
      /memory stats         记忆库统计 (跨会话持久化规模)
      /memory recall <任务> 上下文感知召回 (注入长期记忆到当前任务)
      /memory recent [小时] [kind]  按时间范围检索最近记忆
      /memory tags <标签...>        按标签检索记忆
    """
    from rich.console import Console
    from rich.table import Table

    store = agent.kernel.get("memory_store") if agent.kernel else None
    if store is None:
        ui.error("记忆存储未初始化。")
        return

    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""

    console = Console()

    if sub in ("on", "off"):
        on = (sub == "on")
        config.set_user("memory.auto_extract", on)
        state = "已开启 (回合结束自动抽取)" if on else "已关闭"
        ui.success(f"自动记忆提取: {state}")
        return

    if sub == "list":
        kind = rest.strip().lower() or None
        if kind and kind not in MEMORY_KINDS:
            ui.info(f"用法: /memory list [{'|'.join(MEMORY_KINDS)}]")
            return
        items = store.list_by_kind(kind=kind, limit=50)
        if not items:
            ui.info("(暂无记忆)")
            return
        table = Table(title="Auto Memory 记忆库", show_lines=False)
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("分类", style="magenta")
        table.add_column("内容", style="white", overflow="fold")
        for it in items:
            table.add_row(str(it["id"]), it["kind"], it["content"])
        console.print(table)
        return

    if sub == "search":
        if not rest.strip():
            ui.info("用法: /memory search <关键词>")
            return
        hits = store.search(rest.strip(), limit=10)
        if not hits:
            ui.info("(无命中)")
            return
        table = Table(title=f"搜索: {rest.strip()}")
        table.add_column("分类", style="magenta")
        table.add_column("内容", overflow="fold")
        for h in hits:
            k = h.get("kind", "").split(":", 1)[-1]
            table.add_row(k, h["content"][:200])
        console.print(table)
        return

    if sub == "add":
        kv = rest.strip().split(None, 1)
        if len(kv) < 2 or kv[0].lower() not in MEMORY_KINDS:
            ui.info(f"用法: /memory add <{'|'.join(MEMORY_KINDS)}> <内容>")
            return
        kind = kv[0].lower()
        text = kv[1].strip()
        new_id = store.add_auto_memory(text, kind=kind, source="manual")
        if new_id is None:
            ui.info("该记忆与已有条目相似, 已跳过 (去重)。")
        else:
            ui.success(f"已写入记忆 [id={new_id}] [{kind}] {text}")
        return

    if sub == "delete":
        rid = rest.strip()
        if not rid.isdigit():
            ui.info("用法: /memory delete <id>  (id 来自 /memory list)")
            return
        ok = store.delete_by_id(int(rid))
        if ok:
            ui.success(f"已删除记忆 id={rid}")
        else:
            ui.error(f"未找到记忆 id={rid}")
        return

    if sub == "stats":
        _cmd_memory_stats(store, console)
        return

    if sub == "recall":
        if not rest.strip():
            ui.info("用法: /memory recall <当前任务描述>  — 注入相关长期记忆")
            return
        ctx = store.recall_context(rest.strip(), limit=6)
        if not ctx:
            ui.info("(当前任务无相关长期记忆)")
        else:
            console.print(ctx)
        return

    if sub == "recent":
        _cmd_memory_recent(store, console, rest)
        return

    if sub == "tags":
        tags = rest.strip().split()
        if not tags:
            ui.info("用法: /memory tags <标签...>  — 按标签检索")
            return
        hits = store.search_by_tags(tags, limit=15)
        if not hits:
            ui.info("(无命中标签)")
            return
        table = Table(title=f"标签: {' '.join(tags)}")
        table.add_column("分类", style="magenta")
        table.add_column("内容", overflow="fold")
        for h in hits:
            k = h.get("mkind") or h.get("kind", "").split(":", 1)[-1]
            table.add_row(k, h["content"][:200])
        console.print(table)
        return

    # 默认帮助
    ui.info(
        "Auto Memory 用法:\n"
        "  /memory list [kind]        列出记忆 (kind: " + "/".join(MEMORY_KINDS) + ")\n"
        "  /memory search <关键词>    全文搜索\n"
        "  /memory add <kind> <内容>  手动写一条\n"
        "  /memory delete <id>        按 id 删除\n"
        "  /memory on|off             开关自动提取\n"
        "  /memory stats              记忆库统计\n"
        "  /memory recall <任务>      上下文感知召回\n"
        "  /memory recent [小时] [kind]  最近记忆\n"
        "  /memory tags <标签...>     按标签检索"
    )


def _cmd_memory_stats(store: Any, console: Any) -> None:
    """/memory stats — 展示跨会话持久化规模与分类分布 (长期记忆体检)。"""
    from rich.table import Table

    stats = store.get_stats()
    table = Table(title="记忆库统计 (跨会话持久化)")
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="magenta", justify="right")
    table.add_row("MEMORY.md 事实行", str(stats.get("memory_lines", 0)))
    table.add_row("USER.md 画像行", str(stats.get("user_lines", 0)))
    table.add_row("FTS5 索引条目", str(stats.get("fts_entries", 0)))
    table.add_row("标签索引条目", str(stats.get("tag_entries", 0)))
    console.print(table)

    # 分类分布 (Auto Memory 四类)
    if hasattr(store, "search_by_kind"):
        dist = Table(title="分类分布 (Auto Memory)")
        dist.add_column("分类", style="magenta")
        dist.add_column("条目数", style="cyan", justify="right")
        for kind in MEMORY_KINDS:
            items = store.search_by_kind(kind, limit=1000)
            dist.add_row(kind, str(len(items)))
        console.print(dist)


def _cmd_memory_recent(store: Any, console: Any, rest: str) -> None:
    """/memory recent [小时] [kind] — 按时间范围检索最近记忆 (默认 24h)。"""
    from rich.table import Table

    parts = rest.strip().split()
    hours = 24
    kind: str | None = None
    if parts:
        try:
            hours = max(1, min(int(parts[0]), 24 * 365))
            parts = parts[1:]
        except ValueError:
            pass
    if parts and parts[0].lower() in MEMORY_KINDS:
        kind = parts[0].lower()
    rows = store.search_by_time(hours=hours, kind=kind, limit=30)
    if not rows:
        ui.info("(该时间范围内无记忆)")
        return
    table = Table(title=f"最近 {hours}h 记忆" + (f" [{kind}]" if kind else ""))
    table.add_column("分类", style="magenta")
    table.add_column("内容", overflow="fold")
    for r in rows:
        k = r.get("mkind") or r.get("kind", "").split(":", 1)[-1]
        table.add_row(k, r["content"][:200])
    console.print(table)
