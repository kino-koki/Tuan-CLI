"""tool_search —— 按需检索未直接暴露的工具 (deferred/extended 长尾)。

配合 `tools/tiers.py` 的工具暴露分层: core/extended 直接进 tools 列表, deferred
(长尾/低频/专用) 默认**不暴露**但**仍可按名调用**。模型遇到"要做某件长尾事但工具
列表里没有"时, 先用本工具按关键词检索, 拿到完整调用签名后再直接调用 —— 既压住了
每次请求的工具数量, 又不牺牲能力可达性。
"""

from __future__ import annotations

import json

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext
from .tiers import tier_of


def _score(tool: Tool, terms: list[str], query: str) -> int:
    """给单个工具打分 (越大越相关); 0 表示不匹配。"""
    name = (tool.name or "").lower()
    desc = (tool.description or "").lower()
    group = (tool.group or "").lower()
    score = 0
    if name == query:
        score += 1000
    if query and query in name:
        score += 200
    for t in terms:
        if not t:
            continue
        if t in name:
            score += 40
        if t in group:
            score += 20
        if t in desc:
            score += 10
    return score


def tool_search(ctx: ToolContext, query: str = "", limit: int = 8, tier: str = "") -> str:
    """检索工具。query 支持空格分隔多关键词; tier 可限定 core/extended/deferred。"""
    registry = ctx.kernel.get("tool_registry") if ctx.kernel else None
    if registry is None:
        return "[错误] 工具注册表不可用"

    try:
        all_tools = registry.searchable_tools()
    except AttributeError:  # 兼容极简双
        all_tools = list(getattr(registry, "tools", []) or [])

    want_tier = (tier or "").strip().lower()
    q = (query or "").strip().lower()
    terms = [t for t in q.replace(",", " ").split() if t]

    # 无关键词且未指定 tier: 默认只浏览 deferred (即"没直接暴露给你"的那批),
    # 否则会把已暴露的 core/extended 也刷一遍, 失去检索意义。
    browse_deferred_only = not terms and not want_tier
    if browse_deferred_only:
        want_tier = "deferred"

    scored: list[tuple[int, Tool]] = []
    for t in all_tools:
        if t.name == "tool_search":
            continue
        if want_tier and tier_of(t.name) != want_tier:
            continue
        if not terms:
            # 无关键词: 按分层浏览 (默认只列 deferred, 即"没暴露给你的那批")
            s = 1
        else:
            s = _score(t, terms, q)
        if s > 0:
            scored.append((s, t))

    if not scored:
        hint = f"关键词={query!r}" if query else "空查询"
        return f"未找到匹配工具 ({hint})。可尝试更短的关键词, 或去掉 tier 过滤。"

    scored.sort(key=lambda x: (-x[0], x[1].name))
    picked = [t for _, t in scored[: max(1, min(int(limit or 8), 20))]]

    lines = [f"命中 {len(picked)} 个工具 (共 {len(scored)} 个匹配, 可直接调用):"]
    for t in picked:
        lines.append(f"\n【{t.name}】({tier_of(t.name)} · {t.group})")
        lines.append(f"  {t.description}")
        lines.append("  参数 schema: " + json.dumps(t.parameters, ensure_ascii=False))
    return "\n".join(lines)


class ToolSearchPlugin(Plugin):
    """注册 tool_search 工具 (元工具: 检索长尾工具)。"""

    name = "tools.tool_search"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="tool_search",
            description=(
                "按关键词检索**未直接暴露在工具列表里**的长尾工具 (deferred/extended), "
                "返回其完整参数 schema, 可直接按返回的签名调用。"
                "当你需要做某件专门的事 (如 ext_* 引擎 / codedev_* / pipeline_* / "
                "图像生成 / 沙箱 / 模板 / 代码图谱) 但当前工具列表里找不到时, 先用本工具检索。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词 (空格分隔多个, 如 'json diff')"},
                    "limit": {"type": "integer", "description": "返回条数上限 (默认 8, 最多 20)"},
                    "tier": {"type": "string", "description": "限定分层: core / extended / deferred (可选)"},
                },
                "required": [],
            },
            handler=tool_search, group="meta", read_only=True,
        ))
