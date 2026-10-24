"""pick_files —— 快速文件定位工具 (速度主线 A)。

输入一段任务描述文本, 用 FastFileIndex.rank 在「**不读全文**」的前提下给出
top N 个最相关的候选文件 + 一句中文理由, 供 Agent 决定后续真正 read_file
哪些文件 —— 对标 Claude Code / Freebuff 的 local code map + 省 token 做法。

严格只读: 本工具只增量更新工作区下的索引缓存 (.tuan/fastindex), 不触碰任何
业务源码文件, 不把文件全文读进上下文。
"""

from __future__ import annotations

import re
from typing import List

from ..context.fast_index import FastFileIndex
from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

# 关键词提取: 标识符 (含下划线) 或连续中文词 (>=2 字)。
_KW_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[一-鿿]{2,}")


def _extract_keywords(task: str) -> List[str]:
    """从任务描述里粗提取关键词 (去重、保序)。"""
    return list(dict.fromkeys(_KW_RE.findall(task or "")))


def _pick_files(ctx: ToolContext, task: str, limit: int = 10,
                workspace: str | None = None) -> str:
    """工具 handler: 给任务描述 → 候选文件 top N + 理由。"""
    ws = workspace or getattr(ctx, "workspace", None) or "."
    idx = FastFileIndex(ws)
    idx.build()  # 增量; 已建索引时只 stat 变化文件, 极快
    kws = _extract_keywords(task)
    head = ("[pick_files] 以下为代码地图命中的候选文件"
            "（未读全文、省 token、供你决定后续真正 read_file 哪些文件）:")
    if not kws:
        return head + "\n\n(未从任务描述中提取到有效关键词, 请补充具体模块/符号名)"
    hits = idx.rank(kws, limit=limit)
    lines = [head, f"关键词: {', '.join(kws)}", ""]
    if not hits:
        lines.append("(无命中 —— 可换更具体的词, 或用 find 按文件名搜)")
    else:
        for path, score, reason in hits:
            lines.append(f"- {path}  (score={score})  {reason}")
    lines.append(f"\n[索引规模] {idx.stats()['file_count']} 个文件已建图; "
                 "注意: 以上仅为元信息/符号片段命中, 未读全文。")
    return "\n".join(lines)


class PickerPlugin(Plugin):
    """注册 pick_files 工具 (只读)。"""

    name = "tools.picker"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="pick_files",
            description=(
                "根据任务/需求描述, 用本地代码地图快速定位最相关的 N 个文件"
                "（不读全文, 省 token）。返回候选文件路径 + 一句理由, "
                "供你决定后续真正用 read_file 读哪些文件。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": string_prop("任务/需求描述文本, 如『修复登录超时重试逻辑』"),
                    "limit": {"type": "integer",
                              "description": "返回候选文件数量上限 (默认 10)"},
                    "workspace": {"type": "string",
                                  "description": "工作区根目录 (默认用当前会话工作区)"},
                },
                "required": ["task"],
            },
            handler=_pick_files, group="navigation", read_only=True,
        ))
