"""记忆工具插件: 让 Agent 主动记事实、查记忆 (Hermes 自学习能力的一部分)。

包含两类并存的记忆:
- FTS5 结构化长期记忆: memory_write / memory_update_user / memory_search;
- 文件型记忆笔记 MEMORY.md (对标 Claude Code): memory_note_append 直接写自由文本笔记,
  下次会话自动注入 system prompt 动态段。

管理域工具 (与 /memory 斜杠命令同源, 复用同一 MemoryStore 后端):
memory_delete (按 id/标签/前缀删除) / memory_stats (库统计) /
memory_recall (上下文感知召回) / memory_recent (按时间范围取最近条目)。
"""

from __future__ import annotations

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop


def memory_write(ctx: ToolContext, fact: str, section: str = "事实") -> str:
    store = ctx.kernel.require("memory_store")
    line = store.append_memory(fact, section)
    return f"已记住: {line}"


def memory_update_user(ctx: ToolContext, key: str, value: str) -> str:
    store = ctx.kernel.require("memory_store")
    return f"已更新用户画像: {store.update_user(key, value)}"


def memory_search(ctx: ToolContext, query: str, limit: int = 5) -> str:
    store = ctx.kernel.require("memory_store")
    hits = store.search(query, limit=limit)
    if not hits:
        return "没有找到相关记忆。"
    return "\n".join(f"- [{h['kind']}] {h['content'][:300]} (来源: {h['source']})" for h in hits)


def memory_note_append(ctx: ToolContext, content: str) -> str:
    """追加一条文件型记忆笔记 (MEMORY.md)。

    用于记录用户偏好 / 纠正 / 项目决策 —— 下次会话会自动注入 system prompt。
    超过行数上限时返回警告, 提示用户整理。
    """
    from ..memory.memory_notes import MemoryNotesStore

    config = ctx.kernel.require("config")
    enabled = bool(config.get("memory.notes_enabled", True))
    if not enabled:
        return "记忆笔记已关闭 (memory.notes_enabled=false), 未写入。"
    max_lines = int(config.get("memory.notes_max_lines", 200))
    store = MemoryNotesStore(home=config.home, workspace=ctx.workspace, max_lines=max_lines)
    total = store.append(content)
    if total > max_lines:
        return (f"已写入 MEMORY.md (当前 {total} 行，超过上限 {max_lines} 行)。"
                "建议整理/精简旧笔记后再继续写入，否则下次会话将只注入前 200 行。")
    return f"已写入 MEMORY.md (当前 {total} 行)。下次会话自动注入。"


def _memory_entry_tags(entry: dict) -> list:
    """解析条目的 tags JSON (容错: 损坏/缺失时按无标签处理)。"""
    import json

    raw = entry.get("tags") or "[]"
    try:
        tags = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(t) for t in tags] if isinstance(tags, list) else []


def memory_delete(ctx: ToolContext, id: str = "", tag: str = "", prefix: str = "") -> str:
    """删除长期记忆条目: 按条目 id / 标签 / 内容前缀三选一。

    必须显式给出删除目标 (id/tag/prefix 至少一个), 不提供"删除全部"入口;
    实际删除统一走 store.delete_by_id (同步清理 FTS 索引)。
    """
    store = ctx.kernel.require("memory_store")
    rid = str(id or "").strip()
    rtag = str(tag or "").strip()
    rprefix = str(prefix or "").strip()
    if not rid and not rtag and not rprefix:
        return ("[memory] 请显式指定删除目标: id / tag / prefix 至少给一个, "
                "不支持无差别删除全部记忆。")
    if rid:
        if not rid.isdigit():
            return (f"[memory] id 需为数字 (来自 memory_stats / memory_recent "
                    f"的条目 id), 收到: {rid}")
        if store.delete_by_id(int(rid)):
            return f"已删除记忆 id={rid}。"
        return (f"[memory] 未找到 id={rid} 的记忆条目, "
                "可先用 memory_stats / memory_recent 确认。")
    # 按标签 / 前缀: 先列出候选 (带 id), 再逐条走 store.delete_by_id
    entries = store.list_by_kind(limit=1000)
    if rtag:
        matches = [e for e in entries if rtag in _memory_entry_tags(e)]
        label = f"标签 '{rtag}'"
    else:
        matches = [e for e in entries
                   if str(e.get("content", "")).strip().startswith(rprefix)]
        label = f"前缀 '{rprefix}'"
    if not matches:
        return f"[memory] 没有找到匹配 {label} 的记忆条目。"
    removed = sum(1 for e in matches if store.delete_by_id(int(e["id"])))
    return f"已删除 {removed}/{len(matches)} 条匹配 {label} 的记忆。"


def memory_stats(ctx: ToolContext) -> str:
    """记忆库统计: 存储路径 / 规模 / Auto Memory 分类分布 / 标签分布。"""
    from ..memory.store import MEMORY_KINDS

    store = ctx.kernel.require("memory_store")
    stats = store.get_stats()
    lines = [
        f"记忆库路径: {store.dir}",
        f"MEMORY.md 事实行: {stats.get('memory_lines', 0)}",
        f"USER.md 画像行: {stats.get('user_lines', 0)}",
        f"FTS5 索引条目: {stats.get('fts_entries', 0)}",
        f"标签索引条目: {stats.get('tag_entries', 0)}",
    ]
    kind_counts = {k: len(store.search_by_kind(k, limit=1000)) for k in MEMORY_KINDS}
    lines.append("分类分布: " + ", ".join(f"{k}={n}" for k, n in kind_counts.items()))
    tag_counts: dict = {}
    for entry in store.list_by_kind(limit=1000):
        for t in _memory_entry_tags(entry):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    if tag_counts:
        top = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        lines.append("标签分布: " + ", ".join(f"{t}×{n}" for t, n in top))
    return "\n".join(lines)


def memory_recall(ctx: ToolContext, task: str, limit: int = 6) -> str:
    """上下文感知召回: 按当前任务描述检索相关长期记忆 (全文 + 近期 + 分类优先级排序)。"""
    store = ctx.kernel.require("memory_store")
    task = str(task or "").strip()
    if not task:
        return "[memory] 请提供当前任务描述 (task), 以便召回相关长期记忆。"
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 6
    text: str = store.recall_context(task, limit=limit)
    if not text:
        return "当前任务无相关长期记忆。"
    return text


def memory_recent(ctx: ToolContext, hours: int = 24, kind: str = "", limit: int = 30) -> str:
    """按时间范围检索最近的记忆条目 (默认 24h, 可按 Auto Memory 分类过滤)。"""
    from ..memory.store import MEMORY_KINDS

    store = ctx.kernel.require("memory_store")
    try:
        hours = max(1, min(int(hours), 24 * 365))
    except (TypeError, ValueError):
        hours = 24
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 30
    kind_name = str(kind or "").strip().lower() or None
    if kind_name and kind_name not in MEMORY_KINDS:
        return f"[memory] kind 需为 {'/'.join(MEMORY_KINDS)} 之一, 收到: {kind}"
    rows = store.search_by_time(hours=hours, kind=kind_name, limit=limit)
    if not rows:
        return f"最近 {hours}h 内没有记忆条目。"
    # search_by_time 返回的 kind 是索引列 ("auto"/"memory"), 补一次 mkind 映射便于人读
    mkind_map = {e["content"]: e.get("kind", "") for e in store.list_by_kind(limit=1000)}
    lines = [f"最近 {hours}h 记忆 (共 {len(rows)} 条):"]
    for r in rows:
        k = mkind_map.get(r.get("content", "")) or str(r.get("kind", ""))
        lines.append(f"- [{k}] {str(r.get('content', ''))[:200]}")
    return "\n".join(lines)


class MemoryToolPlugin(Plugin):
    name = "tools.memory"
    requires = ["tool_registry", "memory_store"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="memory_write",
            description="写入一条跨会话长期记忆 (偏好/约定/结论)",
            parameters={
                "type": "object",
                "properties": {
                    "fact": string_prop("事实, 一句话"),
                    "section": string_prop("分类, 默认'事实'"),
                },
                "required": ["fact"],
            },
            handler=memory_write, group="memory", dangerous=True,
        ))
        registry.register(Tool(
            name="memory_update_user",
            description="更新用户画像字段",
            parameters={
                "type": "object",
                "properties": {
                    "key": string_prop("字段名"),
                    "value": string_prop("字段值"),
                },
                "required": ["key", "value"],
            },
            handler=memory_update_user, group="memory", read_only=True,
        ))
        registry.register(Tool(
            name="memory_search",
            description="检索长期记忆/技能/历史",
            parameters={
                "type": "object",
                "properties": {
                    "query": string_prop("关键词"),
                    "limit": {"type": "integer", "description": "条数, 默认 5"},
                },
                "required": ["query"],
            },
            handler=memory_search, group="memory", read_only=True,
        ))
        registry.register(Tool(
            name="memory_note_append",
            description="写入一条文件型记忆笔记 (MEMORY.md): 用户偏好/纠正/项目决策, "
                        "下次会话自动注入系统提示。与 memory_write 互补。",
            parameters={
                "type": "object",
                "properties": {
                    "content": string_prop("要写入的笔记文本, 一行或多行"),
                },
                "required": ["content"],
            },
            handler=memory_note_append, group="memory",
        ))
        registry.register(Tool(
            name="memory_delete",
            description="删除长期记忆条目: 按条目 id / 标签 / 内容前缀 "
                        "(必须显式指定目标, 不支持无差别全删)",
            parameters={
                "type": "object",
                "properties": {
                    "id": string_prop("要删除的条目 id (数字)"),
                    "tag": string_prop("按标签删除: 删除所有带该标签的条目"),
                    "prefix": string_prop("按内容前缀删除: 删除所有以该前缀开头的条目"),
                },
                "required": [],
            },
            handler=memory_delete, group="memory", dangerous=True,
        ))
        registry.register(Tool(
            name="memory_stats",
            description="记忆库统计: 存储路径 / 规模 / 分类分布 / 标签分布",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=memory_stats, group="memory", read_only=True,
        ))
        registry.register(Tool(
            name="memory_recall",
            description="上下文感知召回: 按当前任务描述检索相关长期记忆 "
                        "(按分类优先级排序的带序号匹配)",
            parameters={
                "type": "object",
                "properties": {
                    "task": string_prop("当前任务描述"),
                    "limit": {"type": "integer", "description": "召回条数, 默认 6"},
                },
                "required": ["task"],
            },
            handler=memory_recall, group="memory", read_only=True,
        ))
        registry.register(Tool(
            name="memory_recent",
            description="按时间范围检索最近的记忆条目 (默认 24h, 可按分类过滤)",
            parameters={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "时间范围 (小时), 默认 24"},
                    "kind": string_prop("可选分类过滤: user/feedback/project/reference"),
                    "limit": {"type": "integer", "description": "条数上限, 默认 30"},
                },
                "required": [],
            },
            handler=memory_recent, group="memory", read_only=True,
        ))
