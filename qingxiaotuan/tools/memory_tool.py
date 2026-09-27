"""记忆工具插件: 让 Agent 主动记事实、查记忆 (Hermes 自学习能力的一部分)。

包含两类并存的记忆:
- FTS5 结构化长期记忆: memory_write / memory_update_user / memory_search;
- 文件型记忆笔记 MEMORY.md (对标 Claude Code): memory_note_append 直接写自由文本笔记,
  下次会话自动注入 system prompt 动态段。
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
