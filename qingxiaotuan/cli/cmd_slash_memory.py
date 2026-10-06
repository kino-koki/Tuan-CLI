"""斜杠命令 —— Auto Memory 管理域 (/memory)。

拆分自 cmd_slash.py: list/search/add/delete/on/off。
"""

from __future__ import annotations

from ._ui_singleton import ui


def _cmd_memory(agent, config, arg: str) -> None:
    """/memory — Auto Memory 管理: list/search/add/delete/on/off。

    子命令:
      /memory list [kind]   列出记忆 (kind=user/feedback/project/reference)
      /memory search <q>    全文搜索
      /memory add <kind> <text>   手动写一条记忆
      /memory delete <id>   按 id 删除
      /memory on|off        开关自动提取
    """
    from rich.console import Console
    from rich.table import Table
    from ..memory.store import MEMORY_KINDS

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

    # 默认帮助
    ui.info(
        "Auto Memory 用法:\n"
        "  /memory list [kind]        列出记忆 (kind: " + "/".join(MEMORY_KINDS) + ")\n"
        "  /memory search <关键词>    全文搜索\n"
        "  /memory add <kind> <内容>  手动写一条\n"
        "  /memory delete <id>        按 id 删除\n"
        "  /memory on|off             开关自动提取"
    )
