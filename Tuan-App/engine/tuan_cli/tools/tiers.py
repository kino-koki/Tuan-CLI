"""Tool exposure tiers (core/extended/deferred) and exposure-level resolution.

With 87+ tools, full exposure wastes context and confuses models.

Tiers:
- core     : minimal dev loop (read/write/search/execute/todo/ask/tool_search)
- extended : common enhancers (git/memory/skill/web/subagent/background/sandbox)
- deferred : long-tail (ext_*/codedev_*/pipeline_*/image/templates) —
  not in tools list by default, but callable by name via tool_search.

Exposure (--tools / config tools.exposure):
- minimal  : core only
- standard : core + extended (default)
- full     : all 87
- auto     : by model capability (weak → minimal, strong → standard)

Tiers affect what the model *sees*, not what it *can call* — dispatch
always resolves by name against the full registry.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------- 分层名单
# core: 最小开发闭环 (缺了就没法完成"读-改-跑-验"基本任务)
CORE_TOOLS: FrozenSet[str] = frozenset({
    # 读
    "read_file", "read_files", "list_dir", "glob", "search_files",
    "find",                                   # 合并自 find_references/find_symbol
    # 写
    "write_file", "edit_file", "edit_files", "diff_preview",
    # 跑
    "run_shell", "run_tests",
    # 协作 / 元
    "todo",                                   # 合并自 todo_write/read/list
    "ask_user", "tool_search",
    "enter_plan_mode", "exit_plan_mode",
})

# deferred: 长尾 / 低频 / 专用 —— 默认不暴露, 由 tool_search 按需检索
DEFERRED_TOOLS: FrozenSet[str] = frozenset({
    # ext_* 纯 Python 引擎 (18): 多数场景用不到, 按需检索
    "ext_ansi_strip", "ext_crypto_seal", "ext_crypto_unseal", "ext_diff",
    "ext_index_build", "ext_index_query", "ext_json_diff", "ext_json_merge",
    "ext_json_pointer", "ext_merge3", "ext_notify", "ext_patch",
    "ext_rules_check", "ext_rules_load", "ext_safety_score", "ext_search",
    # sandbox_* (4)
    "sandbox_run", "sandbox_snapshot", "sandbox_diff", "sandbox_cleanup",
    # codedev_* (4)
    "codedev_retrieve", "codedev_spec", "codedev_develop", "codedev_verify",
    # pipeline_* (2)
    "pipeline_list_tools", "pipeline_run",
    # 图像 / 产物 / 模板 (5)
    "image_generate", "image_list_generated", "create_artifact",
    "generate_from_template", "list_templates",
    # 代码分析 / 语言 (3)
    "code_dependency_graph", "codebase_map", "language_checks",
    # 长尾元工具 (6)
    "doctor", "claude_code_run", "workflow", "dispatch_tasks",
    "mcp__tool_search", "receive_messages", "send_message",
    # ---- 合并后的复合工具 (成员已降级为隐藏别名, 只有复合入口需要分层) ----
    "ext_json", "ext_crypto", "ext_index", "ext_rules",
    "sandbox", "codedev", "image", "templates",
})

# extended = 既不在 core 也不在 deferred 的所有已注册工具 (运行时派生, 无需手工维护)

# 暴露档位 → 允许出现的分层
EXPOSURE_MODES: Dict[str, Tuple[str, ...]] = {
    "minimal": ("core",),
    "standard": ("core", "extended"),
    "full": ("core", "extended", "deferred"),
}

DEFAULT_EXPOSURE = "standard"


def tier_of(name: str) -> str:
    """返回工具所属分层: core | extended | deferred。"""
    if name in CORE_TOOLS:
        return "core"
    if name in DEFERRED_TOOLS:
        return "deferred"
    return "extended"


def allowed_tiers(exposure: Optional[str]) -> Tuple[str, ...]:
    """把暴露档位解析为允许的分层元组 (未知档位回退默认)。"""
    key = (exposure or DEFAULT_EXPOSURE).strip().lower()
    return EXPOSURE_MODES.get(key, EXPOSURE_MODES[DEFAULT_EXPOSURE])


def is_exposed(name: str, exposure: Optional[str]) -> bool:
    """给定档位下, 该工具是否应出现在模型可见的 tools 列表里。"""
    return tier_of(name) in allowed_tiers(exposure)


def filter_exposed(tools: Iterable, exposure: Optional[str]) -> List:
    """按档位过滤 Tool 对象列表 (保持原顺序)。"""
    tiers = allowed_tiers(exposure)
    return [t for t in tools if tier_of(getattr(t, "name", "")) in tiers]


# ---------------------------------------------------------------- auto 档位
# 弱模型在长工具列表里更容易产出错格式调用, 且上下文预算小 —— 给最小集。
# 这里只按"是否明显属弱/小模型"做保守判断, 未知模型一律按 standard (不冒险降级)。
_WEAK_MODEL_HINTS: Tuple[str, ...] = (
    "flash-lite", "flash_lite", "lite", "mini", "small", "tiny",
    "7b", "8b", "3b", "1.5b", "0.5b", "qwen2.5:7b", "phi", "gemma",
)
_STRONG_MODEL_HINTS: Tuple[str, ...] = (
    "pro", "max", "opus", "gpt-5", "gpt-4", "o3", "o4", "r1",
    "deepseek-chat", "deepseek-reasoner", "sonnet", "gemini-2.5",
)


def resolve_auto_exposure(model: Optional[str]) -> str:
    """auto 档位: 按模型名启发式选择 minimal / standard。

    规则 (保守优先, 未知一律 standard):
      - 命中弱模型线索 (lite / mini / small / 7b…) → minimal
      - 其余 (含强模型与未知模型) → standard
    只降不升: auto 永不选 full (避免长尾工具回流污染上下文)。
    """
    if not model:
        return DEFAULT_EXPOSURE
    m = model.strip().lower()
    # 强模型线索优先 (如 "gpt-5-mini" 应视为强而非弱)
    if any(h in m for h in _STRONG_MODEL_HINTS):
        return "standard"
    if any(h in m for h in _WEAK_MODEL_HINTS):
        return "minimal"
    return DEFAULT_EXPOSURE


def resolve_exposure(raw: Optional[str], model: Optional[str] = None) -> str:
    """把 --tools / config 的原始值解析为具体档位 (minimal|standard|full)。"""
    if not raw:
        return DEFAULT_EXPOSURE
    key = raw.strip().lower()
    if key == "auto":
        return resolve_auto_exposure(model)
    if key in EXPOSURE_MODES:
        return key
    return DEFAULT_EXPOSURE


# ---------------------------------------------------------------- 统计 (供 CLI 展示)
def exposure_summary(registry_tools: Iterable) -> Dict[str, int]:
    """统计各分层下的工具数量 (供 `tuan tools` 展示; 不含隐藏别名)。"""
    counts = {"core": 0, "extended": 0, "deferred": 0}
    for t in registry_tools:
        if getattr(t, "hidden", False):
            continue
        counts[tier_of(getattr(t, "name", ""))] += 1
    return counts
